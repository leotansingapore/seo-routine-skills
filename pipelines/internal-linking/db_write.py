#!/usr/bin/env python3
"""Write changed post bodies back to a Supabase table through the Management API.
Safety: every original body is backed up to ~/.local/share/internal-linking-backups first, and
each UPDATE only lands if the row still holds exactly the body that was read (a concurrent
edit by a publishing engine is skipped, never overwritten). Dollar-quoting uses a tag that is
checked not to occur in either body.
Usage: db_write.py <ref> <table> <column> <edits.json> <label> [--check]"""
import json, os, sys, time, secrets, pathlib, urllib.request
ref, table, col, edits_path, label = sys.argv[1:6]; CHECK = "--check" in sys.argv
edits = json.load(open(edits_path))      # [{"id":..., "old":..., "new":...}]
TOKEN = os.environ["SUPABASE_ACCESS_TOKEN"]
def sql(q):
    req = urllib.request.Request(f"https://api.supabase.com/v1/projects/{ref}/database/query", data=json.dumps({"query": q}).encode(),
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=120).read())
        except Exception as e:
            last = e; time.sleep(3 * (attempt + 1))
    raise last
bk = pathlib.Path.home() / ".local/share/internal-linking-backups" / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}.json"
bk.write_text(json.dumps({"ref": ref, "table": table, "column": col, "rows": [{"id": e["id"], col: e["old"]} for e in edits]}, ensure_ascii=False))
print(f"backup: {bk} ({len(edits)} rows)")
if CHECK: print("check only, nothing written"); sys.exit(0)
done = skipped = 0
for e in edits:
    tag = "il" + secrets.token_hex(4)
    while f"${tag}$" in e["old"] or f"${tag}$" in e["new"]: tag = "il" + secrets.token_hex(4)
    q = (f"update {table} set {col} = ${tag}${e['new']}${tag}$ where id = '{e['id']}' "
         f"and {col} = ${tag}${e['old']}${tag}$ returning id")
    out = sql(q)
    if isinstance(out, list) and len(out) == 1: done += 1
    else: skipped += 1; print("  skipped (row changed since read or error):", e["id"], str(out)[:120])
print(f"updated {done}, skipped {skipped}")
