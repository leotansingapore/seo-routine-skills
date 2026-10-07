#!/usr/bin/env python3
"""Candidate generation, in code. Jev never sees a page it could not sensibly link to.

Shortlists per source page:
  - service pages in the same cluster (equity destinations)
  - nearest guides/roundups by TF-IDF over title + headings + opening text
  - proof pages (case studies) in the same cluster
Deterministic guards live here, not in the model: no self-links, no utility targets,
no links that already exist in the page body, no archive/form/account pages.
"""
import json, math, re, collections, pathlib

STOP = set("""a an the and or but if then than that this these those of in on at to for with from by as is are was were be been being it its it's you your we our us they them their he she his her i my me not no nor so such very can could should would will just about into over under more most other some any each how what when where which who why all both few own same too s t don now d ll m o re ve y ain aren couldn didn doesn hadn hasn haven isn ma mightn mustn needn shan shouldn wasn weren won wouldn get gets got make makes made use uses used using also may might must want need like well best top guide guides tips tip ways way how-to vs 2020 2021 2022 2023 2024 2025 2026 singapore sg dma marketing agency business businesses company companies service services""".split())
TOK = re.compile(r"[a-z][a-z0-9'\-]{2,}")

def tokens(*parts):
    t = TOK.findall(" ".join(p for p in parts if p).lower())
    return [w for w in t if w not in STOP and len(w) > 2]

def build(pages, profiles):
    docs, tf = {}, {}
    for p, pg in pages.items():
        toks = tokens(pg["title"], pg["h1"], " ".join(pg["h2s"]), pg["desc"], pg["sample"][:900],
                      p.rsplit("/", 1)[-1].replace("-", " "))
        # title/heading terms count triple: they say what the page is FOR
        toks += tokens(pg["title"], pg["h1"]) * 2
        docs[p] = toks
        tf[p] = collections.Counter(toks)
    N = len(docs)
    df = collections.Counter()
    for p, c in tf.items():
        df.update(c.keys())
    idf = {w: math.log(N / (1 + d)) for w, d in df.items()}
    vec = {}
    for p, c in tf.items():
        v = {w: (1 + math.log(n)) * idf.get(w, 0) for w, n in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vec[p] = {w: x / norm for w, x in v.items()}
    return vec

def cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0) for w, x in a.items())

def shortlist(src, pages, profiles, vec, existing, n_service=6, n_peer=12, n_proof=2):
    fs = profiles.get(src)
    if not fs:
        return []
    cl = fs["cluster"]
    out, seen = [], {src} | existing.get(src, set())
    def add(p, why):
        if p in seen or p not in profiles:
            return
        if profiles[p]["role"] == "utility":
            return
        seen.add(p)
        out.append({"path": p, "why": why, "sim": round(cosine(vec[src], vec[p]), 3)})
    pool = [p for p in pages if p not in seen and profiles.get(p, {}).get("role") != "utility"]
    sims = sorted(pool, key=lambda p: -cosine(vec[src], vec[p]))
    # 1. same-cluster service pages, nearest first
    svc = [p for p in sims if profiles[p]["role"] == "service_page" and profiles[p]["cluster"] == cl]
    for p in svc[:n_service]:
        add(p, "service_same_cluster")
    # 2. nearest peers (guides / roundups), any cluster - Jev decides the cut
    peers = [p for p in sims if profiles[p]["role"] in ("guide", "roundup")]
    for p in peers[:n_peer]:
        add(p, "nearest_peer")
    # 3. same-cluster proof
    proof = [p for p in sims if profiles[p]["role"] == "proof" and profiles[p]["cluster"] == cl]
    for p in proof[:n_proof]:
        add(p, "proof_same_cluster")
    # 4. cross-cluster service page only if the text is genuinely close
    xsvc = [p for p in sims if profiles[p]["role"] == "service_page" and profiles[p]["cluster"] != cl]
    for p in xsvc[:max(2, n_service // 2)]:
        if cosine(vec[src], vec[p]) >= 0.12:
            add(p, "service_cross_cluster")
    return out
