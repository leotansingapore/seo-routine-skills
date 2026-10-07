"""Minimal Jev (TypeSafe System One) client for the DMA internal-linking map.

Pinned model, real timeout budget sized for batched questions, retry on 429/529,
and a disk cache so a rerun never pays twice for the same question set.
"""
import json, os, time, hashlib, pathlib, threading
import urllib.request, urllib.error

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"          # pinned, never jev-latest
KEY = os.environ.get("TYPESAFE_API_KEY", "")
CACHE = pathlib.Path(os.environ.get("JEV_CACHE", "/tmp/claude-501/-Users-leo-Documents/48c5bdba-1b95-499f-a1e2-404ed17afbc9/scratchpad/jevcache"))
CACHE.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
USAGE = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cached": 0, "failures": 0}

class JevError(RuntimeError):
    pass

def ask(state, questions, timeout=None, retries=4, label=""):
    """One request, many questions over shared state. Returns the answers map."""
    if not KEY:
        raise JevError("TYPESAFE_API_KEY not set")
    body = {"state": state, "model": MODEL, "questions": questions}
    raw = json.dumps(body, sort_keys=True).encode()
    key = hashlib.sha256(raw).hexdigest()
    cf = CACHE / (key + ".json")
    if cf.exists():
        with _lock:
            USAGE["cached"] += 1
        return json.loads(cf.read_text())["answers"]
    # budget: scale with question count (measured: 12 questions -> ~14s, 24 -> ~24s)
    if timeout is None:
        timeout = max(30, 10 + 1.4 * len(questions))
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(API, data=raw, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
            # Cloudflare in front of the API answers 403 (code 1010) to python-urllib's
            # default agent, seen 2026-09-23; any normal agent string passes.
            "User-Agent": "seo-pipeline/1.0 (+local tooling)"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())
            cf.write_text(json.dumps(out))
            u = out.get("usage", {})
            with _lock:
                USAGE["requests"] += 1
                USAGE["input_tokens"] += u.get("input_tokens", 0)
                USAGE["output_tokens"] += u.get("output_tokens", 0)
            return out["answers"]
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read()[:200]!r}"
            if e.code in (429, 529, 500, 502, 503):
                time.sleep(2 ** attempt + 0.5)
                continue
            break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
    with _lock:
        USAGE["failures"] += 1
    print(f"[jev] {label}: {last}", flush=True)
    return None

def cost_usd():
    # $0.042 per million input tokens; output is not separately billed in the published rate
    return USAGE["input_tokens"] / 1_000_000 * 0.042

def report():
    return (f"jev: {USAGE['requests']} requests, {USAGE['cached']} cached, "
            f"{USAGE['failures']} failures, {USAGE['input_tokens']:,} input tokens, "
            f"~${cost_usd():.4f}")
