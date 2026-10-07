"""Clean CLI description drafts, gate them mechanically, and ask Jev whether each
claims only what its article states. Usage: desc_faithful.py <dir>"""
import json, sys, re, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev
D = pathlib.Path(sys.argv[1])
arts = {a["slug"]: a for a in json.load(open(D / "examprep-articles.json"))}
drafts = json.load(open(D / "drafts.json"))
BANNED = r"comprehensive|ultimate|complete guide|everything you need|unlock|master|dive|navigate|seamless|crucial|essential|key insights|in today's"
out = {}
for slug, d in drafts.items():
    d = [p.strip() for p in (d or "").split("\n") if p.strip()][-1] if d else ""
    d = d.strip('"')
    probs = []
    if not 110 <= len(d) <= 160: probs.append(f"length {len(d)}")
    if re.search(r"[^\x00-\x7f]", d): probs.append("non-ASCII")
    if re.search(BANNED, d, re.I): probs.append("banned word")
    body = re.sub(r"\s+", " ", arts[slug]["body"])[:9000] + " FAQ: " + " ".join(f"{f['q']} {f['a']}" for f in arts[slug].get("faqs", []))[:2000]
    a = jev.ask({"article": {"title": arts[slug]["title"], "text": body}, "description": d},
                {"faithful": {"type": "noul", "instructions": "Is every claim in `description` (each number, name, comparison and promise about what the page covers) stated or directly implied by `article`? A single unsupported claim means no."}},
                label=slug)
    out[slug] = {"desc": d, "old": arts[slug]["description"], "faithful": round(a["faithful"]["noul"], 3) if a else None, "problems": probs}
json.dump(out, open(D / "checked.json", "w"), indent=1)
for s, v in sorted(out.items(), key=lambda x: x[1]["faithful"] or 0):
    print(f"{v['faithful']}  {len(v['desc'])}  {s}: {v['desc']}" + (f"  PROBLEMS {v['problems']}" if v["problems"] else ""))
print(jev.report())
