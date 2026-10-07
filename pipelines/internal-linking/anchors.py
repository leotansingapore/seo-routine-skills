#!/usr/bin/env python3
"""Anchor grounding: code finds the real phrases, Jev only picks one of them.

The known defect of asking a model for anchor text is NAMING - it writes a phrase the
page does not contain. So every candidate here is a verbatim span lifted out of the
source page's own body text, and applying a choice is a single-occurrence string
replacement inside the <article> element. Nothing is generated.
"""
import re

TAG = re.compile(r"<[^>]+>")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
SKIP_BLOCK = re.compile(r'<div[^>]*class="(?:dma-tldr|dma-related|dma-cta|dma-fz)[^"]*"[^>]*>', re.I)
CLOSE_SKIP = re.compile(r"^</(h[1-6]|figure|figcaption|script|style|table)\b", re.I)
OPEN_SKIP = re.compile(r"^<(h[1-6]|figure|figcaption|script|style|table)\b", re.I)
CLOSE_TXT = re.compile(r"^</(p|li)\b", re.I)
OPEN_TXT = re.compile(r"^<(p|li)\b", re.I)
DIVTAG = re.compile(r"</?div\b", re.I)
STOP = set("""the a an and or of to in for on with your you our is are be this that it as at by from
how what why when where which who will can do does if not but""".split())


def article_span(raw):
    i = raw.find('<article class="dma-body"')
    if i < 0:
        return None
    j = raw.find("</article>", i)
    return (i, j) if j > i else None


def segments(body):
    pos = 0
    for m in TAG.finditer(body):
        if m.start() > pos:
            yield ("text", body[pos:m.start()], pos, m.start())
        yield ("tag", m.group(0), m.start(), m.end())
        pos = m.end()
    if pos < len(body):
        yield ("text", body[pos:], pos, len(body))


def block_ranges(body):
    """Raw ranges of template blocks that must never receive a new link."""
    out = []
    for m in SKIP_BLOCK.finditer(body):
        depth, pos = 1, m.end()
        while depth and pos < len(body):
            nxt = DIVTAG.search(body, pos)
            if not nxt:
                pos = len(body)
                break
            depth += -1 if body[nxt.start():nxt.start() + 2] == "</" else 1
            pos = nxt.end()
        out.append((m.start(), pos))
    return out


def linkable_text(body):
    """Raw offsets of text that may carry a new link: inside <p>/<li>, outside any existing
    <a>, outside headings and figures, outside template blocks, and free of HTML entities
    (so a replacement is a plain substring swap)."""
    skipped = block_ranges(body)
    out, depth_a, skip = [], 0, 0
    inside = False
    for kind, text, s, e in segments(body):
        if kind == "tag":
            t = text.lower()
            if t.startswith("</a"):
                depth_a = max(0, depth_a - 1)
            elif t.startswith("<a ") or t == "<a>":
                depth_a += 1
            elif CLOSE_SKIP.match(t):
                skip = max(0, skip - 1)
            elif OPEN_SKIP.match(t):
                skip += 1
            elif CLOSE_TXT.match(t):
                inside = False
            elif OPEN_TXT.match(t):
                inside = True
            continue
        if not (inside and depth_a == 0 and skip == 0):
            continue
        if not text.strip():
            continue
        if any(a <= s < b for a, b in skipped):
            continue
        out.append((s, e, text))
    return out


BRAND = re.compile(r"\s*[-|]\s*(DMA|D.?Marketing Agency|Digital Marketing Agency).*$", re.I)
EDGE_STOP = set("""the a an and or of to in for on with your you our us we is are be been was were this
that it as at by from how what why when where which who will can do does if not but more most best top
they their them its his her i my me so such very just about into over under other some any each""".split())
GENERIC = set("""month months monthly year years yearly annual day days daily week weeks weekly guide guides
complete ultimate review reviews singapore singaporean sg update updated new list tips things ways step steps
explained overview basics beginner beginners""".split())
# a clean anchor holds letters, digits, spaces and word-internal - or '
CLEAN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-]*[A-Za-z0-9]$")


def target_phrases(tgt_page, tgt_path):
    """Phrases that NAME the target, taken from the target's own title, heading and slug.

    Anchors are built from the destination, not sliced out of the source at random: that
    is what keeps 'local SEO' from becoming 'realms. Local SEO'.
    """
    slug = tgt_path.rsplit("/", 1)[-1].replace("-", " ")
    seeds = [BRAND.sub("", tgt_page["title"]), BRAND.sub("", tgt_page["h1"]), slug]
    out, seen = [], set()
    for seed in seeds:
        if not seed:
            continue
        for chunk in re.split(r"[^A-Za-z0-9 '\-]+", seed):
            ws = [w for w in chunk.split() if w]
            for n in (4, 3, 2):
                for i in range(len(ws) - n + 1):
                    phrase = " ".join(ws[i:i + n])
                    low = [w.lower().strip("'-") for w in ws[i:i + n]]
                    if low[0] in EDGE_STOP or low[-1] in EDGE_STOP:
                        continue
                    if not any(w not in EDGE_STOP and w not in GENERIC and len(w) > 2 and not w.isdigit() for w in low):
                        continue      # "month in 2026" names nothing; a phrase needs one distinctive word
                    if not CLEAN.match(phrase):
                        continue
                    k = phrase.lower()
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append(phrase)
    out.sort(key=lambda p: -len(p.split()))
    return out[:14]


def find_spans(body, tgt_page, tgt_path, max_spans=5):
    """Locate the target's own phrases verbatim in the source body's linkable text."""
    phrases = target_phrases(tgt_page, tgt_path)
    if not phrases:
        return []
    nodes = linkable_text(body)
    found, seen = [], set()
    for phrase in phrases:
        # the boundary must reject a hyphen too, or "long-tail keywords" yields "tail keywords"
        pat = re.compile(r"(?<![A-Za-z0-9'\-])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![A-Za-z0-9'\-])", re.I)
        for s, e, text in nodes:
            if len(text.split()) < 6:
                continue      # a 2-3 word node is a label or a pseudo-heading, not prose
            m = pat.search(text)
            if not m:
                continue
            got = text[m.start():m.end()]
            if "&" in got or "\n" in got:
                continue
            k = got.lower()
            if k in seen:
                continue
            seen.add(k)
            found.append({"phrase": got, "start": s + m.start(), "end": s + m.end(),
                          "words": len(phrase.split()),
                          "context": text[max(0, m.start() - 130):min(len(text), m.end() + 130)].strip()})
            break
    found.sort(key=lambda x: -x["words"])
    # a fragment of a longer phrase that also matched is never the better anchor
    kept = []
    for c in found:
        low = c["phrase"].lower()
        if any(low != k["phrase"].lower() and low in k["phrase"].lower() for k in kept):
            continue
        kept.append(c)
    return kept[:max_spans]


def apply_link(raw, span, href):
    """Wrap exactly one verbatim span in an <a>. Offsets are into the article substring."""
    sp = article_span(raw)
    if not sp:
        return None
    i, _ = sp
    a, b = i + span["start"], i + span["end"]
    if raw[a:b] != span["phrase"]:
        return None
    return raw[:a] + '<a href="' + href + '">' + span["phrase"] + "</a>" + raw[b:]
