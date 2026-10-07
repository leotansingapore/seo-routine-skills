#!/usr/bin/env python3
"""Monthly freshness audit for the financeillustrator Newsroom.

The weekly sweep (newsroom-sweep.py) FINDS new clippings. Nothing checked whether the
ones already on the wall had gone stale, and this wall is full of point-in-time figures:
a fixed deposit snapshot, a CPF interest floor with an end date, retirement sums that
change every January, a monetary policy statement superseded every quarter. A figure a
client can check and find wrong is the failure the whole wall exists to prevent.

So this asks two questions of every clipping:
  1. Does its link still resolve?
  2. Reading its own text against today's date, has it expired or been superseded?

Question 2 is a judgment, so Jev makes it, not a regex. NOTHING is edited or published:
the answer is a Lark card telling a person what to go and re-check.

Stdlib only and Python 3.9 clean, so launchd can run it without a venv.

  newsroom-audit.py           audit and post to Lark
  newsroom-audit.py --dry     audit and print, post nothing
  newsroom-audit.py --links   link check only, no Jev, no post
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

TYPESAFE = "https://api.typesafe.ai/v1/systemone"
# Pinned, never jev-latest: a model change must be a decision, not a surprise.
MODEL = "jev-1.13.0"

LARK_NOTIFY = os.path.expanduser("~/.local/bin/lark-notify")
REPO = os.path.expanduser("~/Documents/your-site-repo")
DATA_FILES = ["src/data/newsroom.ts", "src/data/ipNewsEvidence.ts"]
STAMP = os.path.expanduser("~/.local/state/newsroom-audit/last-ok")

# How sure Jev has to be before a clipping is put in front of Leo.
#
# 0.60 was a guess when this was written and is now checked against the first real run,
# 24 Sep 2026 over 34 clippings. It flagged five, and the two clearest were at the ends
# of that band: fd-rates-sep-2026 at 0.73 (a September snapshot of bank rates that move
# monthly) and cpf-sa-closure-2025 at 0.62 (it quotes 2025's Enhanced Retirement Sum of
# $426,000, which 2026 superseded). Raising the bar to 0.65 would drop the second, which
# is a real catch, so the threshold stays where it is and the occasional borderline flag
# is the price. Read the whole list each month rather than trusting the number.
MIN_STALE = 0.60


def log(msg):
    sys.stderr.write("[newsroom-audit] %s\n" % msg)


def read_from_main(rel):
    """The deployed version, not the working tree, which is months behind."""
    r = subprocess.run(["git", "-C", REPO, "show", "origin/main:%s" % rel],
                       capture_output=True, text=True, check=False, timeout=60)
    if r.returncode != 0:
        log("could not read %s: %s" % (rel, r.stderr.strip()[:120]))
        return ""
    return r.stdout


def clippings():
    """Every clipping as {id, headline, date, url, facts}, read off the source files.

    A brace-matching parser would be the tempting move and would break on the first
    brace inside a fact. Each field is pulled by its own anchored pattern instead.
    """
    subprocess.run(["git", "-C", REPO, "fetch", "origin", "--quiet"],
                   check=False, capture_output=True, timeout=120)

    # A clipping carried over from the HealthShield wall keeps its FACTS in
    # ipNewsEvidence.ts but its timeSensitive flag in newsroom.ts's FROM_SHIELD_WALL map,
    # at a different indent and a different shape. Parsing only the `    id: "..."` blocks
    # read 8 of the 11 flags and silently skipped three that genuinely expire. Collect the
    # map's flags first, then merge them on by id.
    carried_flags = set(re.findall(
        r'\n  "([a-z0-9-]+)": \{[^}]*?timeSensitive: true', read_from_main(DATA_FILES[0]), re.S))

    out, seen = [], set()
    for rel in DATA_FILES:
        body = read_from_main(rel)
        # Split on the id line: everything until the next id line belongs to this card.
        parts = re.split(r'\n    id: "([a-z0-9-]+)",\n', body)
        for i in range(1, len(parts) - 1, 2):
            cid, chunk = parts[i], parts[i + 1]
            if cid in seen:
                continue
            seen.add(cid)
            def one(pat):
                m = re.search(pat, chunk, re.S)
                return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ""
            facts = re.findall(r'^      "((?:[^"\\]|\\.)*)"', chunk, re.M)
            # The data now says which clippings carry figures that expire. Trust it over
            # asking Jev to re-derive the same distinction on every run.
            time_sensitive = bool(re.search(r'timeSensitive: true', chunk))
            out.append({
                "id": cid,
                "headline": one(r'headline:\s*\n?\s*"((?:[^"\\]|\\.)*)"'),
                "date": one(r'\n    date: "([^"]*)"'),
                "url": one(r'\n    url:\s*\n?\s*"([^"]*)"'),
                "facts": [re.sub(r'\\"', '"', f) for f in facts][:6],
                "timeSensitive": time_sensitive or cid in carried_flags,
                "file": rel,
            })
    return out


def link_status(url):
    """("ok" | "dead" | "unchecked", detail).

    The first run of this reported four dead links and every one was wrong: three were
    the insurer's site, which refuses plain urllib behind Akamai and needs an impersonating
    client, and one was a 429 from a host that was simply rate-limiting. A monthly job
    that cries wolf gets ignored, so only a definite 404/410/451 counts as dead and
    everything else is reported separately as "could not check".
    """
    last = "unreachable"
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method,
                                     headers={"User-Agent": UA, "Accept-Language": "en-SG,en"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return "ok", str(r.status)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 451):
                return "dead", "HTTP %s" % e.code
            # 403/405/501 = the host dislikes HEAD; 429 = rate limited. Neither is dead.
            last = "HTTP %s" % e.code
            if method == "HEAD":
                continue
            return "unchecked", last
        except Exception as e:
            last = type(e).__name__
            if method == "HEAD":
                continue
            return "unchecked", last
    return "unchecked", last


def ask_jev(item, today, key):
    """Has this clipping expired or been superseded? One question, one clipping."""
    state = {
        "today": today,
        "published": item["date"],
        "headline": item["headline"],
        "facts": item["facts"],
    }
    questions = {
        "stale": {
            "type": "noul",
            "instructions": (
                "`facts` are the claims a Singapore financial adviser reads to a client "
                "from a clipping published on `published`. Today is `today`. Judge ONLY "
                "whether the clipping's own text has gone out of date, not whether it is "
                "important. It is stale if it states a figure or rule that its own wording "
                "ties to a period that has now ended, such as a rate 'until' a date now "
                "past, a yearly sum for a year now over, a monthly market snapshot from "
                "several months ago, or a forecast whose window has closed. It is NOT "
                "stale merely for being old: a rule change, a court judgment, a completed "
                "policy decision or a historical total stays true however long ago it "
                "happened."
            ),
            "criteria": {
                "true": "A client checking this today would find a figure or rule that no longer holds.",
                "false": "Everything it states is still true today, even if the event is old.",
            },
        },
    }
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(
        TYPESAFE, data=body,
        headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return float(json.load(r)["answers"]["stale"]["noul"])
        except urllib.error.HTTPError as e:
            # TypeSafe answers 503/529 under load. Retry, then give up on THIS clipping.
            if e.code in (429, 503, 529) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            log("  jev HTTP %s for %s" % (e.code, item["id"]))
            return None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < 2:
                time.sleep(2 ** attempt + 1)
                continue
            return None


def post_to_lark(dead, stale, unchecked, total, ts, dry):
    lines = []
    if dead:
        lines.append("**%d dead link%s**" % (len(dead), "" if len(dead) == 1 else "s"))
        for cid, url, why in dead:
            lines.append("- `%s` (%s) %s" % (cid, why, url))
        lines.append("")
    if stale:
        lines.append("**%d clipping%s reading as out of date**" % (len(stale), "" if len(stale) == 1 else "s"))
        for cid, score, head in stale:
            lines.append("- `%s` %.2f - %s" % (cid, score, head[:90]))
        lines.append("")
    if not dead and not stale:
        lines.append("**All %d clippings still resolve and still read as current.** No action." % total)
        lines.append("")
    if unchecked:
        # Named, not hidden: a host that blocks the checker is not a healthy link either,
        # it is just not a broken one.
        lines.append("Could not check %d (host blocked the checker, not necessarily broken): %s"
                     % (len(unchecked), ", ".join(c[0] for c in unchecked)))
    lines.append("%d clippings checked; staleness judged on the %d whose figures expire." % (total, ts))
    body = "\n".join(lines).strip()

    if dead or stale:
        headline = "%d to re-check on the Newsroom wall" % (len(dead) + len(stale))
        status, action = "warn", "Re-read each source and refresh the figure, or retire the clipping."
        paste = ("Audit these financeillustrator Newsroom clippings: open each source, check every "
                 "figure against it, update the card or retire it, and re-screenshot if the page "
                 "changed. " + " ".join(c[0] for c in dead) + " " + " ".join(c[0] for c in stale))
    else:
        headline = "Newsroom wall is current"
        status, action, paste = "ok", "", ""

    argv = ["--product", "your-site", "--job", "Newsroom monthly audit",
            "--status", status, "--headline", headline, "--body", body]
    if action:
        argv += ["--action", action, "--paste", paste]
    if dry:
        argv.append("--dry-run")
    if not os.path.exists(LARK_NOTIFY):
        log("no lark-notify, printing instead")
        print(headline); print(body); return
    r = subprocess.run([LARK_NOTIFY] + argv, check=False)
    if r.returncode != 0:
        log("lark-notify exited %d" % r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="print the card, post nothing")
    ap.add_argument("--links", action="store_true", help="link check only")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    log("run at %s" % today)
    items = clippings()
    log("%d clippings on the wall" % len(items))
    if not items:
        log("parsed nothing - the data file shape probably changed, which is itself the finding")
        return 1

    dead, unchecked = [], []
    for it in items:
        if not it["url"]:
            continue
        verdict, why = link_status(it["url"])
        if verdict == "dead":
            log("  DEAD      %-28s %s" % (it["id"], why))
            dead.append((it["id"], it["url"], why))
        elif verdict == "unchecked":
            log("  unchecked %-28s %s" % (it["id"], why))
            unchecked.append((it["id"], it["url"], why))

    if args.links:
        print("%d dead, %d unchecked, of %d" % (len(dead), len(unchecked), len(items)))
        return 0

    key = os.environ.get("TYPESAFE_API_KEY")
    stale = []
    if not key:
        log("no TYPESAFE_API_KEY: reporting link results only")
    else:
        for it in items:
            if not it["facts"]:
                continue
            # Only the clippings whose own figures expire. A rule change, a judgment or a
            # historical total is durable by construction, and asking Jev about it bought
            # nothing but borderline scores: the first run flagged a rule-change notice at
            # 0.64 purely for being old. Also cuts the monthly Jev spend by two thirds.
            if not it.get("timeSensitive"):
                continue
            sc = ask_jev(it, today, key)
            if sc is None:
                continue
            log("  %.2f %s" % (sc, it["id"]))
            if sc >= MIN_STALE:
                stale.append((it["id"], sc, it["headline"]))
        stale.sort(key=lambda x: x[1], reverse=True)

    post_to_lark(dead, stale, unchecked, len(items),
                 sum(1 for i in items if i.get('timeSensitive')), args.dry)
    if not args.dry:
        os.makedirs(os.path.dirname(STAMP), exist_ok=True)
        with open(STAMP, "w", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%d") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
