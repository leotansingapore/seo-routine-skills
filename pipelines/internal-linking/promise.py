"""Anchor promise check: does the linked phrase promise the page it lands on?
A generic phrase ('personal loan') aimed at a specific page ('CIMB Personal Loan review') fails
this even when the phrase is on topic, which the anchor Choice cannot see."""
import jev
def question(anchor, context, tgt):
    return {"type": "noul",
      "instructions": {"link_text": anchor, "sentence": context,
                       "link_target": {"url": tgt["path"], "title": tgt["title"], "heading": tgt["h1"], "meta_description": tgt["desc"]},
                       "question": ("A reader sees `link_text`, underlined as a link inside `sentence`. Would a reader who clicks it "
                                    "expect to land on a page like `link_target`?")},
      "criteria": {"true": "The link text names what the target page is actually about, at the same level of detail: a named product, scheme, term or topic that the target page covers as its main subject.",
                   "false": "The link text is broader or vaguer than the target (a general phrase leading to one specific brand, case or sub-topic), or it names something the target only touches on, so the click would surprise the reader."}}
def check(state, picks, P, label=""):
    """picks: list of (dst, phrase, context). Returns list of promise probabilities (None on failure)."""
    qs = {f"p{i}": question(ph, ctx, P[d]) for i, (d, ph, ctx) in enumerate(picks)}
    a = jev.ask(state, qs, label=label)
    return [round(a[f"p{i}"]["noul"], 3) if a and a.get(f"p{i}") else None for i in range(len(picks))]
