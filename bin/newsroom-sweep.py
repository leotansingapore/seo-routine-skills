#!/usr/bin/env python3
"""Weekly sweep for the financeillustrator Newsroom.

Reads Singapore's primary sources, drops anything already on the wall, and asks Jev
whether each remaining headline is worth a consultant's time, using Leo's own four
questions. The shortlist goes to Lark. NOTHING is published: a clipping still needs a
person to verify the figures and write the card, which is the whole point of the wall.

Stdlib only and Python 3.9 clean, so launchd can run it without a venv.

  newsroom-sweep.py            sweep, score, post to Lark
  newsroom-sweep.py --dry      sweep and score, print, post nothing
  newsroom-sweep.py --no-jev   sweep only, skip scoring (source health check)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

TYPESAFE = "https://api.typesafe.ai/v1/systemone"
# Pinned, never jev-latest: a model change must be a decision, not a surprise.
MODEL = "jev-1.13.0"

LARK_NOTIFY = os.path.expanduser("~/.local/bin/lark-notify")
STATE_DIR = os.path.expanduser("~/.local/share/newsroom-sweep")
# The stamp automation-health watches. Written on any clean run, including a week
# where nothing cleared the bar, because a quiet week is still a working job.
STAMP = os.path.expanduser("~/.local/state/newsroom-sweep/last-ok")
SEEN_PATH = os.path.join(STATE_DIR, "seen.json")

# The wall itself, so a headline already carried is never proposed again.
REPO = os.path.expanduser("~/Documents/your-site-repo")
NEWSROOM_DATA = ["src/data/newsroom.ts", "src/data/ipNewsEvidence.ts"]

# Each source is (label, listing url, regex that finds article paths, url builder).
# Everything here is a primary source. Outlets are deliberately absent: a headline is
# cheap and a regulator's own page is what a client can check.
SOURCES = [
    ("MOH", "https://www.moh.gov.sg/newsroom",
     r'/newsroom/([a-z0-9][a-z0-9\-]{20,150})/',
     "https://www.moh.gov.sg/newsroom/%s/"),
    ("CPF", "https://www.cpf.gov.sg/member/infohub/news/cpf-related-announcements",
     r'/member/infohub/news/cpf-related-announcements/([a-z0-9][a-z0-9\-]{10,150})',
     "https://www.cpf.gov.sg/member/infohub/news/cpf-related-announcements/%s"),
    # SPF is deliberately absent: police.gov.sg renders its news listing in the
    # browser, so a plain fetch returns 250KB with no article links in it. Its scam
    # and cybercrime briefs come out twice a year and are added by hand.
    ("MAS", "https://www.mas.gov.sg/news",
     r'/news/(media-releases/20\d\d/[a-z0-9][a-z0-9\-]{5,150})',
     "https://www.mas.gov.sg/news/%s"),
]


def log(msg):
    sys.stderr.write("[newsroom-sweep] %s\n" % msg)


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-SG,en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def already_on_the_wall():
    """Every source url the wall already carries, read from origin/main.

    Deliberately NOT the working tree: ~/Documents/your-site-repo sits on a
    months-old branch point, so reading it would re-propose clippings that shipped
    weeks ago. A fetch first, then `git show`, is what the deployed site actually has.
    """
    import subprocess
    urls = set()
    subprocess.run(["git", "-C", REPO, "fetch", "origin", "--quiet"],
                   check=False, capture_output=True, timeout=120)
    for rel in NEWSROOM_DATA:
        r = subprocess.run(["git", "-C", REPO, "show", "origin/main:%s" % rel],
                           capture_output=True, text=True, check=False, timeout=60)
        if r.returncode != 0:
            log("could not read %s from origin/main: %s" % (rel, r.stderr.strip()[:120]))
            continue
        urls.update(u.rstrip("/") for u in re.findall(r'url:\s*"(https://[^"]+)"', r.stdout))
    return urls


def load_seen():
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_seen(seen):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


MONTHS = ("January February March April May June July August September "
          "October November December").split()


def _published(html, url):
    """The page's own date, as a datetime, or None.

    Tried in order: the meta tag, a spelled-out date in the body, then the year in
    the url. Without this the first run put a 2024 Budget at the top of the list.
    """
    m = re.search(r'<meta[^>]+(?:article:published_time|datePublished)[^>]+content="([^"]+)"', html, re.I)
    if not m:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    if m:
        try:
            return datetime.strptime(m.group(1)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s+(%s)\s+(20\d\d)" % "|".join(MONTHS),
                  re.sub(r"<[^>]+>", " ", html))
    if m:
        try:
            return datetime(int(m.group(3)), MONTHS.index(m.group(2)) + 1,
                            int(m.group(1)), tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.search(r"/(20\d\d)[/-]", url) or re.search(r"[-/](20\d\d)\b", url)
    if m:
        # Only a year, so assume the END of it: a 2024 slug must not look recent.
        return datetime(int(m.group(1)), 12, 31, tzinfo=timezone.utc)
    return None


def page_of(url):
    """(title, published, lead) for a candidate, or None if it cannot be read.

    The lead matters: scoring a bare title like "CPFB | Budget Highlights 2024" gave
    Jev almost nothing to work with and every score landed in the same narrow band.
    """
    try:
        html = fetch(url, timeout=25)
    except Exception as e:  # a dead candidate must not end the run
        log("  page fetch failed %s: %s" % (url, type(e).__name__))
        return None
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if not m:
        return None
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    t = re.split(r"\s+[|\u2013-]\s+(?:Ministry of Health|CPFB|Singapore Police Force|MAS|Base)\b", t)[0]
    t = re.sub(r"^(?:CPFB|MAS)\s*\|\s*", "", t).strip()
    if not t:
        return None

    body = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body)
    # Sentences long enough to be prose, taken from after the headline where possible.
    start = body.find(t[:40]) if len(t) >= 40 else -1
    tail = body[start + len(t):] if start >= 0 else body
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", tail) if len(x.strip()) > 60]
    lead = " ".join(sentences[:4])[:900]
    return t, _published(html, url), lead


def sweep(limit_per_source=12):
    """(source, url, title) for everything the listings offer today."""
    found = []
    health = {}
    for label, listing, pattern, builder in SOURCES:
        try:
            html = fetch(listing)
        except Exception as e:
            health[label] = "FETCH FAILED (%s)" % type(e).__name__
            log("%s: listing fetch failed: %s" % (label, e))
            continue
        slugs = []
        for s in re.findall(pattern, html):
            if s not in slugs:
                slugs.append(s)
        health[label] = "%d found" % len(slugs)
        if not slugs:
            # A source that silently yields nothing is the failure mode that makes a
            # weekly job look healthy while it stops working. It gets reported.
            log("%s: listing parsed but matched nothing - selector may have moved" % label)
        for s in slugs[:limit_per_source]:
            found.append((label, builder % s))
    return found, health


def ask_jev(source, title, lead, key):
    """Leo's four questions, one request per headline. Jev reads text; this is text."""
    state = {"source": source, "headline": title, "opening": lead, "market": "Singapore"}
    common = ("`headline` and `opening` are a real, published item from `source`, a "
              "Singapore government body. The reader is a Singapore financial adviser "
              "who meets retail clients about insurance, CPF, retirement, property and "
              "savings. Judge the item itself, not how the headline is worded. ")
    questions = {
        "talking_point": {
            "type": "noul",
            "instructions": common + (
                "Could the adviser open or steer a client conversation with this "
                "headline? A change to a rule, a price, a payout or a published "
                "figure can be. An internal appointment, an award, an enforcement "
                "action against one company, or a notice aimed at industry rather "
                "than the public, cannot."),
            "criteria": {"true": "An adviser could raise it with a client unprompted.",
                         "false": "Raising it with a client would puzzle them."},
        },
        "adds_value": {
            "type": "noul",
            "instructions": common + (
                "Does this change what a client should know or do, rather than only "
                "being news? Something that moves a sum, a date, a limit, an "
                "eligibility rule or a cost adds value. A restatement of existing "
                "policy, or a ministerial speech with no decision in it, does not."),
            "criteria": {"true": "A client's plan or knowledge would change.",
                         "false": "Nothing a client does would change."},
        },
        "helps_presentation": {
            "type": "noul",
            "instructions": common + (
                "Would a screenshot of this page strengthen a financial review or a "
                "sales presentation, as evidence the adviser can point at? Official "
                "figures, dated rule changes and published limits do. Vague or "
                "purely reassuring announcements do not."),
            "criteria": {"true": "It works as evidence on a slide or on a table.",
                         "false": "It would be filler on a slide."},
        },
        "client_cares": {
            "type": "noul",
            "instructions": common + (
                "Would an ordinary Singaporean earning a normal wage care about "
                "this, because it touches their money, their home, their health "
                "cover or their retirement? Professional, industry-facing or "
                "technical items do not clear this."),
            "criteria": {"true": "It touches an ordinary person's own money.",
                         "false": "Only a professional would care."},
        },
    }
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(
        TYPESAFE, data=body,
        headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.load(r)
            a = out["answers"]
            return {k: float(a[k]["noul"]) for k in questions}
        except urllib.error.HTTPError as e:
            # TypeSafe answers 503/529 under load. Retry, then give up on THIS
            # headline rather than the whole run.
            if e.code in (429, 503, 529) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            log("  jev HTTP %s for %r" % (e.code, title[:60]))
            return None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < 2:
                time.sleep(2 ** attempt + 1)
                continue
            return None


# Thresholds set from a real run on 24 Sep 2026, not guessed. Eight live headlines from
# MOH, CPF and MAS scored:
#
#   0.80  CPF  Budget 2026 Highlights            care .85 talk .91 value .71 pres .71
#   0.68  CPF  CareShield Life 2025 Review       care .80 talk .87 value .56 pres .49
#   0.48  CPF  CPF (Amendment) Bill Highlights   care .25 talk .61 value .50 pres .57
#   0.46  MOH  Colorectal screening start age    care .58 talk .76 value .23 pres .28
#   0.35  MOH  Treatment cost disclosure         care .49 talk .60 value .15 pres .18
#   0.15  MOH  School vape deterrence            care .17 talk .27 value .06 pres .11
#   0.14  MOH  Children's sleep health           care .17 talk .25 value .07 pres .08
#   0.07  MOH  National Medical Excellence Award care .10 talk .08 value .04 pres .05
#
# The break is between 0.48 and 0.68 and the ranking matched a hand review of the same
# eight: Budget 2026 was already picked for the wall by hand before Jev ever saw it.
# Three gates, because one strong answer must not carry an item: the CPF Amendment Bill
# reads well to an adviser (talk .61) and means nothing to a client (care .25).
MIN_SCORE = 0.55
MIN_CLIENT_CARES = 0.55
MIN_TALKING_POINT = 0.70
SHORTLIST = 8


def score_of(s):
    return (s["talking_point"] + s["adds_value"] + s["helps_presentation"] + s["client_cares"]) / 4.0


def passes(s):
    return (score_of(s) >= MIN_SCORE
            and s["client_cares"] >= MIN_CLIENT_CARES
            and s["talking_point"] >= MIN_TALKING_POINT)


def post_to_lark(kept, health, dry):
    """One card in the house shape, built by lark-notify.

    Flags match lark-notify's real interface (--product/--job/--status/--headline/
    --body/--action/--paste); an earlier guess at --title/--subtitle/--tag would have
    failed silently every Monday. `your-site` is this app's id in the shared product list.
    """
    lines = []
    for src, url, title, sc in kept:
        lines.append("**%s** %s" % (src, title))
        lines.append("score %.2f - client cares %.2f, talking point %.2f, adds value %.2f, presentation %.2f"
                     % (score_of(sc), sc["client_cares"], sc["talking_point"],
                        sc["adds_value"], sc["helps_presentation"]))
        lines.append(url)
        lines.append("")
    lines.append("Sources read: " + ", ".join("%s %s" % (k, v) for k, v in sorted(health.items())))
    lines.append("Nothing has been published. Each one still needs its figures checked "
                 "against the source, a screenshot, and a card written.")
    body = "\n".join(lines).strip()

    if kept:
        headline = "%d headline%s worth a clipping" % (len(kept), "" if len(kept) == 1 else "s")
        status = "info"
        action = "Read the shortlist and decide which ones go on the wall."
        paste = ("Add these to the financeillustrator Newsroom: verify every figure against "
                 "the primary source, screenshot each page, write the card and the client "
                 "line, then ship. " + " ".join(u for _, u, _, _ in kept))
    else:
        headline = "Nothing cleared the bar this week"
        status = "ok"
        action = ""
        paste = ""

    argv = ["--product", "your-site", "--job", "Newsroom sweep",
            "--status", status, "--headline", headline, "--body", body]
    if action:
        argv += ["--action", action, "--paste", paste]
    if dry:
        argv.append("--dry-run")

    if not os.path.exists(LARK_NOTIFY):
        log("no lark-notify at %s, printing instead" % LARK_NOTIFY)
        print(headline)
        print(body)
        return
    import subprocess
    r = subprocess.run([LARK_NOTIFY] + argv, check=False)
    if r.returncode != 0:
        log("lark-notify exited %d" % r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="print the card, post nothing")
    ap.add_argument("--no-jev", action="store_true", help="sweep only, no scoring")
    ap.add_argument("--limit", type=int, default=12, help="candidates per source")
    ap.add_argument("--days", type=int, default=120,
                    help="ignore anything published longer ago than this")
    args = ap.parse_args()

    log("run at %s" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    carried = already_on_the_wall()
    seen = load_seen()
    log("wall carries %d urls, %d headlines seen before" % (len(carried), len(seen)))

    found, health = sweep(args.limit)
    fresh = [(src, url) for src, url in found
             if url.rstrip("/") not in carried and url not in seen]
    log("%d candidates, %d fresh" % (len(found), len(fresh)))

    if args.no_jev:
        for src, url in fresh:
            print("%-5s %s" % (src, url))
        return 0

    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        log("no TYPESAFE_API_KEY: cannot score, reporting the raw list instead")
        post_to_lark([], health, args.dry)
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    kept = []
    for src, url in fresh:
        page = page_of(url)
        if not page:
            continue
        title, published, lead = page
        if published is not None and published < cutoff:
            log("  stale  %-5s %s (%s)" % (src, title[:64], published.date()))
            seen.add(url)
            continue
        s = ask_jev(src, title, lead, key)
        if s is None:
            continue
        log("  avg %.2f | care %.2f talk %.2f value %.2f pres %.2f | %-4s %s"
            % (score_of(s), s["client_cares"], s["talking_point"], s["adds_value"],
               s["helps_presentation"], src, title[:60]))
        if passes(s):
            kept.append((src, url, title, s))
        seen.add(url)

    kept.sort(key=lambda k: score_of(k[3]), reverse=True)
    post_to_lark(kept[:SHORTLIST], health, args.dry)
    if not args.dry:
        save_seen(seen)
        os.makedirs(os.path.dirname(STAMP), exist_ok=True)
        with open(STAMP, "w", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%d") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
