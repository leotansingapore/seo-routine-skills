#!/bin/bash
# ask-chatgpt-search.sh "<query>"
#
# One non-interactive, read-only Codex CLI run with the native Responses API
# web_search tool enabled (web_search="live"). Auth is Leo's ChatGPT Plus login
# stored by `codex login` in ~/.codex/auth.json (no API key, no per-call cost).
#
# What this is: OpenAI's Codex agent model answering with live web search.
# What this is NOT: the chatgpt.com consumer "ChatGPT Search" product. Answers,
# ranking and citations can differ from what a user sees on chatgpt.com.
#
# Output: product line, model, web_search call count + queries, the answer,
# then the de-duplicated cited URLs. Exit 3 when the model never searched
# (answer is ungrounded), 2 on usage error, codex's exit code on failure.
#
# Env: ASK_CHATGPT_MODEL overrides the model (default: `model` in
# ~/.codex/config.toml). ASK_CHATGPT_TIMEOUT seconds (default 300).
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
  echo "usage: $0 \"<query>\"" >&2
  exit 2
fi
QUERY="$1"
TIMEOUT="${ASK_CHATGPT_TIMEOUT:-300}"

CFG="$HOME/.codex/config.toml"
MODEL="${ASK_CHATGPT_MODEL:-}"
if [ -z "$MODEL" ] && [ -f "$CFG" ]; then
  MODEL=$(grep -m1 -E '^model *= *"' "$CFG" | sed -E 's/^model *= *"([^"]+)".*/\1/')
fi
EFFORT=$(grep -m1 -E '^model_reasoning_effort *= *"' "$CFG" 2>/dev/null | sed -E 's/.*"([^"]+)".*/\1/')

WORK=$(mktemp -d /private/tmp/ask-chatgpt-search.XXXXXX)
trap 'rm -rf "$WORK"' EXIT

PROMPT="Use web search to answer the question below as you would for a member of the public. After the answer, add a line 'Sources:' and list every source you relied on as a full https URL, one per line.

Question: $QUERY"

ARGS=(exec --ignore-user-config -c 'web_search="live"' -s read-only --skip-git-repo-check --ephemeral --json -C "$WORK" -o "$WORK/last.txt")
[ -n "$MODEL" ] && ARGS+=(-m "$MODEL")
[ -n "$EFFORT" ] && ARGS+=(-c "model_reasoning_effort=\"$EFFORT\"")

if command -v timeout >/dev/null 2>&1; then
  timeout "$TIMEOUT" codex "${ARGS[@]}" "$PROMPT" </dev/null >"$WORK/events.jsonl" 2>"$WORK/stderr.txt"
else
  codex "${ARGS[@]}" "$PROMPT" </dev/null >"$WORK/events.jsonl" 2>"$WORK/stderr.txt"
fi
RC=$?
if [ $RC -ne 0 ]; then
  echo "codex exec failed (exit $RC). stderr tail:" >&2
  tail -20 "$WORK/stderr.txt" >&2
  exit $RC
fi

CODEX_VERSION=$(codex --version 2>/dev/null | awk '{print $NF}')
python3 - "$WORK/events.jsonl" "$WORK/last.txt" "${MODEL:-codex default}" "${CODEX_VERSION:-unknown}" <<'PY'
import json, re, sys
events, last, model, version = sys.argv[1:5]
searches, usage = [], {}
for line in open(events, errors="ignore"):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    item = e.get("item") or {}
    if e.get("type") == "item.completed" and item.get("type") == "web_search":
        act = item.get("action") or {}
        qs = act.get("queries") or ([act["query"]] if act.get("query") else []) or ([act["url"]] if act.get("url") else [])
        searches.append((act.get("type") or "search", qs or [item.get("query", "")]))
    if e.get("type") == "turn.completed":
        usage = e.get("usage") or {}
try:
    answer = open(last, errors="ignore").read().strip()
except OSError:
    answer = ""
urls = []
for u in re.findall(r"https?://[^\s)\]>\"'<`]+", answer):
    u = u.rstrip(".,;:")
    if u not in urls:
        urls.append(u)
print(f"product: Codex CLI {version} exec, ChatGPT-account login, Responses API web_search tool (live). Not the chatgpt.com ChatGPT Search product.")
print(f"model: {model}")
print(f"web_search_calls: {len(searches)}")
for kind, qs in searches:
    print(f"  - {kind}: " + " | ".join(q for q in qs if q))
if usage:
    print(f"tokens: input={usage.get('input_tokens')} output={usage.get('output_tokens')}")
print("--- answer ---")
print(answer or "(empty answer)")
print("--- cited_urls ---")
print("\n".join(urls) if urls else "(none)")
sys.exit(0 if searches else 3)
PY
