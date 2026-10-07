#!/bin/bash
# Unattended weekly blog builds (launchd com.leo.weekly-builds, Mon 10:00, after the 08:00 detectors).
# Leo 2026-10-03: "allow blogs to write unattended so I dont need to keep saying run the X weekly build".
# Runs the weekly-builds skill headless once per ISO week. The week stamp is written only on a clean
# finish, so a usage limit (exit 75), a crash or a missed Monday is retried by weekly-catchup.sh.
set -u
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
DIR="$HOME/.local/share/weekly-builds"; mkdir -p "$DIR/logs"
WEEK=$(date +%G-W%V)
[ "$(cat "$DIR/last-ok-week" 2>/dev/null)" = "$WEEK" ] && exit 0
mkdir "$DIR/lock" 2>/dev/null || { echo "$(date '+%F %T') already running" >> "$DIR/run.log"; exit 0; }
trap 'rmdir "$DIR/lock" 2>/dev/null' EXIT
LOG="$DIR/logs/$WEEK-$(date +%H%M).log"
PROMPT="Use the weekly-builds skill and run this week's builds for every site in it, end to end and unattended. \
Leo approved unattended building and publishing on 2026-10-03. Nobody is watching: do not ask questions. \
Where the skill or a site brief needs Leo (a missing credential, a fact only he has, a gate that cannot reach 100), \
skip that item, record it as an ISSUE line in the Lark summary, and carry on with the rest. \
Finish with the Lark summary the skill describes. \
This is a headless run: it ends the moment you stop, and anything still running then is killed. So work in the \
foreground only. Never use run_in_background, background shell jobs, nohup, or background subagents; run each site's \
build to completion before the next. (2026-10-03 the first run handed FinanceBlog and DMA to background agents, stopped \
while they were mid-ship, and left their work uncommitted.) \
The very last line of your final message must be exactly WEEKLY_BUILDS_COMPLETE, written only after the Lark summary is posted.${1:+ $1}"
echo "$(date '+%F %T') start $WEEK" >> "$DIR/run.log"
gtimeout --kill-after=120 5h /bin/bash "$HOME/.local/bin/claude-resilient.sh" -p "$PROMPT" --model opus \
  --dangerously-skip-permissions < /dev/null > "$LOG" 2>&1
rc=$?
echo "$(date '+%F %T') end $WEEK rc=$rc log=$LOG" >> "$DIR/run.log"
# exit 0 alone is not proof: the first run exited 0 with two sites half-shipped and no summary
if [ $rc -eq 0 ] && tail -c 400 "$LOG" | grep -q "WEEKLY_BUILDS_COMPLETE"; then
  echo "$WEEK" > "$DIR/last-ok-week"; date '+%F %T' > "$DIR/last-ok"
elif [ $rc -eq 0 ]; then
  echo "$(date '+%F %T') $WEEK exited 0 without WEEKLY_BUILDS_COMPLETE; not stamped, catch-up retries" >> "$DIR/run.log"
fi
exit $rc
