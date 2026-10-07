#!/bin/bash
# Weekly link preview pass for activity-tracker.io (was monthly until 2026-09-27;
# Leo: "a cron job every week also where new links are identified and the
# preview is always improved").
#
# Leo, 2026-09-15: the roadmap and help links unfurled in Telegram as the app's
# generic corgi card, and new features and pages keep arriving, so each needs
# its own card without anyone remembering to make one. Each run:
#   1. lists pages the app mounts that still unfurl as the site card
#      (~/.local/bin/og-coverage.mjs) and, if any, has one Opus session give
#      them rows, aliases or an ignore line (monthly-task.md next to this job's
#      state);
#   1b. improves the weakest existing previews: Jev scores every row the way a
#      colleague sent the link reads it, Opus drafts rewrites for the 3 weakest
#      under 2.6, and a rewrite is kept only if Jev scores it 0.4 higher
#      (~/.local/bin/og-improve.mjs);
#   2. redraws every card whose words or picture moved since it was drawn
#      (build-og-cards.mjs --changed in the app, tools/og-cards.mjs --changed
#      in the help centre);
#   3. tests, commits by pathspec, pushes the app (a push is its deploy),
#      CLI-deploys the help centre, then checks the live previews;
#   4. posts to the Lark alerts group every time, including "nothing changed"
#      and every way it can fail.
#
# launchd com.leo.og-cards-weekly, Mondays at 10:30.
# DRY_RUN=1 prints the coverage and the stale app cards, and commits, pushes,
# deploys and posts nothing.
set -uo pipefail

HOME_DIR=/Users/you
SHARE="$HOME_DIR/.local/share/og-cards"
APP="$HOME_DIR/remix-of-activity-tracker"
HELP="$HOME_DIR/Documents/at-help"
WT="$SHARE/remix-worktree"
DATE="$(date +%F)"
LOG="$SHARE/weekly.log"
TRANSCRIPT="$SHARE/reports/$DATE-transcript.txt"
export REPORT_PATH="$SHARE/reports/$DATE.json"
export IMPROVE_REPORT="$SHARE/reports/$DATE-improve.json"
# Jev key for the improve step; launchd does not read ~/.zshenv.
export TYPESAFE_API_KEY="$(sed -n 's/^[[:space:]]*\(export[[:space:]]*\)\{0,1\}TYPESAFE_API_KEY=//p' "$HOME_DIR/.zshenv" | head -1 | tr -d "\"'")"
export IGNORE_FILE="$SHARE/remix-ignore.txt"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME_DIR/.local/bin"
export HOME="$HOME_DIR" USER=leo LOGNAME=leo
DRY_RUN="${DRY_RUN:-0}"
mkdir -p "$SHARE/reports"

LARK_WEBHOOK="https://open.larksuite.com/open-apis/bot/v2/hook/<YOUR-WEBHOOK-ID>"
log() { echo "[$(date '+%F %H:%M:%S')] $*" >> "$LOG"; }
notify() {
  local payload resp
  if [ "$DRY_RUN" = 1 ]; then printf '%s\n%s\n' "--- would post to Lark ---" "$1"; return; fi
  payload="$(printf '%s' "$1" | /usr/bin/python3 -c 'import json,sys; print(json.dumps({"msg_type":"text","content":{"text":sys.stdin.read()}}))')"
  # Lark answers 200 with a non-zero "code" when it refuses a message.
  resp="$(curl -s -m 20 -X POST "$LARK_WEBHOOK" -H 'Content-Type: application/json' -d "$payload")"
  case "$resp" in *'"code":0'*) ;; *) log "lark notify failed: ${resp:-no response}" ;; esac
}
abort() { log "ABORT: $1"; notify "Link preview weekly pass stopped: $1"; exit 1; }

# One run at a time. A lock older than four hours belongs to a run that died.
if ! mkdir "$SHARE/lock" 2>/dev/null; then
  if [ -n "$(find "$SHARE/lock" -maxdepth 0 -mmin +240 2>/dev/null)" ]; then
    rm -rf "$SHARE/lock" && mkdir "$SHARE/lock"
  else
    abort "another run still holds $SHARE/lock, so this one did nothing."
  fi
fi
trap 'rm -rf "$SHARE/lock"' EXIT
log "start (dry_run=$DRY_RUN)"

# ---- The app: a private worktree at origin/main, never the shared checkout ----
git -C "$APP" fetch -q origin main >> "$LOG" 2>&1 \
  || abort "could not fetch the app repo, so nothing was checked. Run it by hand: bash ~/.local/bin/og-cards-weekly.sh"
git -C "$APP" worktree remove --force "$WT" >/dev/null 2>&1
rm -rf "$WT"
git -C "$APP" worktree add -q --detach "$WT" origin/main >> "$LOG" 2>&1 \
  || abort "could not create the app worktree at $WT. See $LOG"
ln -s "$APP/node_modules" "$WT/node_modules"
for c in "$APP/.env" "$HOME_DIR/Documents/New project/remix-of-activity-tracker/.env"; do
  [ -s "$c" ] && cp "$c" "$WT/.env" 2>/dev/null && break
done
cd "$WT" || abort "could not enter $WT"

node "$HOME_DIR/.local/bin/og-coverage.mjs" "$WT" "$IGNORE_FILE" > "$SHARE/coverage.json" 2>> "$LOG" \
  || abort "the coverage check failed, so no page was looked at. See $LOG"
UNCOVERED="$(/usr/bin/python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["uncovered"]))' "$SHARE/coverage.json")"
N_UNCOVERED="$(printf '%s' "$UNCOVERED" | grep -c . || true)"
log "uncovered=$N_UNCOVERED"

SESSION_NOTE=""
rm -f "$REPORT_PATH"
if [ "$N_UNCOVERED" -gt 0 ] && [ "$DRY_RUN" != 1 ]; then
  PROMPT="$(cat "$SHARE/monthly-task.md")

## Pages with no card this month ($N_UNCOVERED)

$UNCOVERED

REPORT_PATH=$REPORT_PATH
IGNORE_FILE=$IGNORE_FILE"
  claude -p "$PROMPT" --model opus \
    --tools "Read,Edit,Write,Bash,Glob,Grep" \
    --strict-mcp-config --mcp-config "$SHARE/no-mcp.json" \
    --dangerously-skip-permissions > "$TRANSCRIPT" 2>> "$LOG"
  RC=$?
  log "session rc=$RC"
  if [ "$RC" -ne 0 ] || ! /usr/bin/python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$REPORT_PATH" 2>/dev/null; then
    LIMIT="$(grep -hoiE "hit your [a-z ]*limit[^.]*" "$TRANSCRIPT" 2>/dev/null | head -1)"
    SESSION_NOTE="The writing session failed (exit $RC${LIMIT:+, $LIMIT}) and wrote no report, so its edits were thrown away and no new page got a card."
    git checkout -q -- . && git clean -fdq -- public/og scripts
    rm -f "$REPORT_PATH"
  fi
fi

# Anything the session touched outside its lane goes back.
ALLOWED='^(scripts/app-routes\.mjs|scripts/app-routes\.test\.mjs|scripts/og-cards\.lock\.json|public/og/.*|\.env|node_modules)$'
STRAY="$(git status --porcelain --untracked-files=all | cut -c4- | grep -vE "$ALLOWED" || true)"
if [ -n "$STRAY" ]; then
  log "reverting stray changes: $(echo "$STRAY" | tr '\n' ' ')"
  echo "$STRAY" | while read -r f; do
    git checkout -q -- "$f" 2>/dev/null || rm -rf -- "$f"
  done
  SESSION_NOTE="$SESSION_NOTE Reverted edits outside the card files: $(echo "$STRAY" | tr '\n' ' ')"
fi

# ---- 1b. Improve the weakest previews (never fatal) ----
IMPROVE_NOTE=""
if [ "$DRY_RUN" = 1 ]; then
  node "$HOME_DIR/.local/bin/og-improve.mjs" "$WT" --dry-run >> "$LOG" 2>&1
else
  node "$HOME_DIR/.local/bin/og-improve.mjs" "$WT" >> "$LOG" 2>&1 || IMPROVE_NOTE="The improve step crashed; see $LOG."
fi
IMPROVE_SUMMARY="$(/usr/bin/python3 - "$IMPROVE_REPORT" <<'PY'
import json, sys
try:
    r = json.load(open(sys.argv[1]))
except Exception:
    print(""); sys.exit()
out = [f"Previews scored by Jev: {r.get('scored', 0)}"]
for c in r.get("changed", []):
    out.append(f"  ~ {c['path']}  \"{c['old']}\" ({c['old_score']}) -> \"{c['new']}\" ({c['new_score']})")
for k in r.get("kept", []):
    out.append(f"  = {k['path']} kept: {k.get('reason','')}")
for e in r.get("errors", []):
    out.append(f"  ! {e}")
print("\n".join(out))
PY
)"

RENDER_OUT="$(node scripts/build-og-cards.mjs --changed 2>&1)"; RENDER_RC=$?
echo "$RENDER_OUT" >> "$LOG"
[ "$RENDER_RC" -eq 0 ] || abort "the app card render failed: $(echo "$RENDER_OUT" | tail -3). Nothing was committed."

TEST_OUT="$(npx vitest run scripts/app-routes.test.mjs scripts/marketing-routes.test.mjs api/page-og.test.ts 2>&1)"; TEST_RC=$?
echo "$TEST_OUT" | tail -15 >> "$LOG"

NEW_CARDS="$(git status --porcelain --untracked-files=all -- public/og | grep -c '^??' || true)"
REDRAWN="$(git status --porcelain -- public/og | grep -c '^ M' || true)"
ROWS_CHANGED="$(git status --porcelain -- scripts/app-routes.mjs | grep -c . || true)"

if [ "$DRY_RUN" = 1 ]; then
  echo "coverage: $(cat "$SHARE/coverage.json")"
  echo "stale app cards redrawn in the throwaway worktree: $REDRAWN (new: $NEW_CARDS)"
  echo "tests rc=$TEST_RC"
  [ -r "$HELP/src/content/docs/index.mdx" ] && echo "help centre: readable" || echo "help centre: NOT readable"
  exit 0
fi

APP_NOTE="no app card needed a change."
if [ "$TEST_RC" -ne 0 ]; then
  APP_NOTE="the card tests failed, so nothing was pushed: $(echo "$TEST_OUT" | grep -E 'FAIL|AssertionError|Tests ' | head -4 | tr '\n' ' ')"
elif [ "$NEW_CARDS" -gt 0 ] || [ "$REDRAWN" -gt 0 ] || [ "$ROWS_CHANGED" -gt 0 ]; then
  git add -- scripts/app-routes.mjs scripts/app-routes.test.mjs scripts/og-cards.lock.json public/og
  if [ "$NEW_CARDS" -gt 0 ]; then
    MSG="improve: $NEW_CARDS more app pages unfurl as their own card in chats"
    [ "$REDRAWN" -gt 0 ] && MSG="$MSG, $REDRAWN cards redrawn"
  else
    MSG="improve: $REDRAWN link preview cards redrawn to match their pages"
  fi
  IMPROVED_N="$(/usr/bin/python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("changed",[])))' "$IMPROVE_REPORT" 2>/dev/null || echo 0)"
  [ "${IMPROVED_N:-0}" -gt 0 ] && MSG="$MSG; $IMPROVED_N weak previews rewritten"
  git commit -q -m "$MSG

Weekly link preview pass (og-cards-weekly.sh). Rewrites kept only where Jev
scored the new preview at least 0.4 higher.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" >> "$LOG" 2>&1
  PUSHED=0
  for attempt in 1 2 3; do
    git fetch -q origin main >> "$LOG" 2>&1
    if ! git rebase -q origin/main >> "$LOG" 2>&1; then git rebase --abort >/dev/null 2>&1; break; fi
    if git push -q origin HEAD:main >> "$LOG" 2>&1; then PUSHED=1; break; fi
  done
  SHA="$(git rev-parse --short=9 HEAD)"
  if [ "$PUSHED" -ne 1 ]; then
    APP_NOTE="committed $SHA but could not land it on main (a conflict with another session's edit, most likely). It stays in $WT until the next run."
  else
    # A push is the deploy. Wait for that build, then check every preview live.
    TOK="$(/usr/bin/python3 -c 'import json; print(json.load(open("/Users/you/Library/Application Support/com.vercel.cli/auth.json"))["token"])' 2>/dev/null)"
    PID="$(/usr/bin/python3 -c 'import json; print(json.load(open("/Users/you/remix-of-activity-tracker/.vercel/project.json"))["projectId"])' 2>/dev/null)"
    STATE=NONE
    for i in $(seq 1 90); do
      STATE="$(curl -s -m 20 -H "Authorization: Bearer $TOK" "https://api.vercel.com/v6/deployments?projectId=$PID&limit=15&target=production" \
        | /usr/bin/python3 -c 'import json,sys; sha=sys.argv[1]; print(next((d["state"] for d in json.load(sys.stdin).get("deployments",[]) if d.get("meta",{}).get("githubCommitSha","").startswith(sha)),"NONE"))' "$SHA" 2>/dev/null)"
      case "$STATE" in READY|ERROR|CANCELED|BLOCKED) break ;; esac
      sleep 20
    done
    if [ "$STATE" = READY ]; then
      QA_OUT="$(node scripts/qa/og-previews.mjs 2>&1)"; QA_RC=$?
      echo "$QA_OUT" | tail -20 >> "$LOG"
      if [ "$QA_RC" -eq 0 ]; then QA="live check passed on every route"
      else QA="live check FAILED: $(echo "$QA_OUT" | grep -A2 -m3 'got:' | tr '\n' ' ' | cut -c1-400)"; fi
    else
      QA="deploy state $STATE after 30 minutes, so the live check did not run"
    fi
    APP_NOTE="pushed $SHA ($NEW_CARDS new cards, $REDRAWN redrawn); $QA."
  fi
fi

# ---- The help centre: its own Vercel project, deployed from the CLI ----
HELP_NOTE=""
if [ ! -r "$HELP/src/content/docs/index.mdx" ]; then
  HELP_NOTE="skipped: this launchd job cannot read ~/Documents/at-help until /bin/bash has Full Disk Access (System Settings > Privacy & Security)."
else
  cd "$HELP" || true
  DIRTY="$(git status --porcelain | cut -c4- | grep -vE '^(public/og/|tools/og-cards\.lock\.json)' || true)"
  H_OUT="$(node tools/og-cards.mjs --changed 2>&1)"; H_RC=$?
  echo "$H_OUT" >> "$LOG"
  H_N="$(echo "$H_OUT" | grep -cE '^(og card|removed card):' || true)"
  if [ "$H_RC" -ne 0 ]; then
    HELP_NOTE="card render failed: $(echo "$H_OUT" | tail -2 | tr '\n' ' ')"
  elif [ "$H_N" -eq 0 ]; then
    HELP_NOTE="all cards current."
  else
    git add -- public/og tools/og-cards.lock.json
    git commit -q -m "improve: $H_N help centre preview cards redrawn to match their categories

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" >> "$LOG" 2>&1
    if [ -n "$DIRTY" ]; then
      HELP_NOTE="$H_N cards redrawn and committed, NOT deployed: the help repo holds someone's uncommitted work ($(echo "$DIRTY" | head -3 | tr '\n' ' ')), and a CLI deploy would publish it. The next help deploy carries the cards."
    elif ! npx astro build >> "$LOG" 2>&1; then
      HELP_NOTE="$H_N cards redrawn and committed, NOT deployed: astro build failed. See $LOG"
    elif ! vercel --prod --yes --scope leotansingapores-projects >> "$LOG" 2>&1; then
      HELP_NOTE="$H_N cards redrawn and committed, NOT deployed: vercel --prod failed. See $LOG"
    else
      BAD=""
      for slug in $(echo "$H_OUT" | sed -n 's#^og card: /help/og/\(.*\)\.jpg$#\1#p'); do
        code="$(curl -s -o /dev/null -w '%{http_code}' "https://activity-tracker.io/help/og/$slug.jpg")"
        [ "$code" = 200 ] || BAD="$BAD $slug=$code"
      done
      HELP_NOTE="$H_N cards redrawn and deployed${BAD:+, but these did not answer 200:$BAD}."
    fi
  fi
fi

# ---- Report ----
SUMMARY="$(/usr/bin/python3 - "$REPORT_PATH" <<'PY'
import json, sys
try:
    r = json.load(open(sys.argv[1]))
except Exception:
    print(""); sys.exit()
out = []
for a in r.get("added", []):
    out.append(f"  + {a.get('path')}  \"{a.get('headline')}\"")
if r.get("aliased"):
    out.append("  aliased: " + ", ".join(f"{x.get('from')} -> {x.get('to')}" for x in r["aliased"]))
if r.get("ignored"):
    out.append(f"  marked as never shared: {len(r['ignored'])} (" + ", ".join(x.get('path', '') for x in r["ignored"][:8]) + (")" if len(r["ignored"]) <= 8 else ", ...)"))
if r.get("deferred"):
    out.append("  deferred to next week: " + ", ".join(x.get('path', '') for x in r["deferred"]))
if r.get("notes"):
    out.append("  note: " + r["notes"])
print("\n".join(out))
PY
)"

notify "Link preview weekly pass, $DATE
App pages with no card before this run: $N_UNCOVERED
${SUMMARY:+$SUMMARY
}${IMPROVE_SUMMARY:+$IMPROVE_SUMMARY
}${IMPROVE_NOTE:+$IMPROVE_NOTE
}App: $APP_NOTE${SESSION_NOTE:+
$SESSION_NOTE}
Help centre: $HELP_NOTE
Log: $LOG"
date +%F > "$SHARE/last-run"
log "done"
