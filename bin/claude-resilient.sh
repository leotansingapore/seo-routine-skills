#!/bin/bash
# claude-resilient.sh - resilience wrapper for ALL headless `claude -p` automation
# (Leo directive 2026-07-16: unattended work must survive network blips, Claude
# usage limits, and account switches - he swaps claude.ai accounts but keeps the
# terminal). Every launchd job that spawns a claude session routes through this.
#
# Usage: claude-resilient.sh [claude args...] < /dev/null
#   e.g. claude-resilient.sh -p --model claude-opus-5 "prompt"
# Env:  CR_BASE_URL  optional ANTHROPIC_BASE_URL (pxpipe proxy)
#
# Behavior:
#   - GLOBAL LIMIT FLAG ~/.local/state/claude-limit/until (epoch seconds):
#     if set and in the future, exit 75 immediately (EX_TEMPFAIL) - callers skip
#     this tick; the backlog is caught on the next tick after the limit resets.
#     Work is deferred, never lost (watchdog re-counts pending every tick).
#   - USAGE LIMIT detected -> parse "resets H:MMam/pm" if present, else +60 min;
#     write the flag; exit 75.
#   - NETWORK errors -> 3 retries with 30/90/270s backoff.
#   - AUTH errors (mid account-switch) -> wait 60s, retry twice (the CLI picks
#     up whatever account the terminal is now logged into).
#   - Every outcome appended to ~/.local/state/claude-limit/runs.log (ASCII).
set -u
STATE="$HOME/.local/state/claude-limit"
mkdir -p "$STATE"
LOG="$STATE/runs.log"
FLAG="$STATE/until"
now() { date +%s; }
say() { echo "[$(date '+%F %T')] $1" >> "$LOG"; }
# Fingerprint the logged-in Claude account (keychain). When Leo switches accounts
# for limit-swapping, this hash changes -> a stale limit flag from the OLD account
# is auto-cleared so the fresh account's quota is used immediately.
acct_fp() { security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null | shasum 2>/dev/null | cut -c1-16; }

# 0) respect an active limit flag - UNLESS the account was switched since it was set
if [ -f "$FLAG" ]; then
  until_ts=$(cat "$FLAG" 2>/dev/null || echo 0)
  cur_fp=$(acct_fp); saved_fp=$(cat "$STATE/account" 2>/dev/null || echo "")
  if [ -n "$cur_fp" ] && [ -n "$saved_fp" ] && [ "$cur_fp" != "$saved_fp" ]; then
    say "ACCOUNT SWITCHED since limit (fp ${saved_fp}->${cur_fp}) - clearing stale flag, resuming on fresh account"
    rm -f "$FLAG" "$STATE/account"
  elif [ "$(now)" -lt "${until_ts:-0}" ]; then
    say "SKIP: limit flag active until $(date -r "$until_ts" '+%F %T') (same account)"
    exit 75
  else
    rm -f "$FLAG" "$STATE/account"
    say "limit flag expired - resuming"
  fi
fi

parse_reset_epoch() {
  # from text like "resets 4:50pm" (local tz). Echo epoch or nothing.
  local t
  t=$(echo "$1" | /usr/bin/grep -oE 'resets [0-9]{1,2}(:[0-9]{2})?(am|pm)' | head -1 | sed 's/resets //')
  [ -z "$t" ] && return 1
  local e
  e=$(date -j -f '%I:%M%p' "$t" +%s 2>/dev/null || date -j -f '%I%p' "$t" +%s 2>/dev/null) || return 1
  # if that time already passed today, it means tomorrow
  [ "$e" -le "$(now)" ] && e=$((e + 86400))
  echo "$e"
}

attempt=0
delays=(30 90 270)
while :; do
  attempt=$((attempt + 1))
  ERRFILE=$(mktemp); OUTFILE=$(mktemp)
  # stdout is TEED, not swallowed: the caller still gets every byte on its own
  # stdout, and we keep a copy to classify. "You've hit your session limit" is
  # printed on STDOUT, so a stderr-only classifier called it a plain failure and
  # the job reported BROKEN instead of deferring (runs.log, 2026-09-21 10:47:52).
  if [ -n "${CR_BASE_URL:-}" ]; then
    ANTHROPIC_BASE_URL="$CR_BASE_URL" claude "$@" 2>"$ERRFILE" | tee "$OUTFILE"
  else
    claude "$@" 2>"$ERRFILE" | tee "$OUTFILE"
  fi
  rc=${PIPESTATUS[0]}
  # Hand the caller its stderr back. It used to be read and deleted, so every
  # job that logs claude with 2>&1 lost the real error and kept only the exit
  # code - the same blindness this wrapper was written to end.
  cat "$ERRFILE" >&2
  # Classify on everything, log BOTH ends: the real error is usually first and the
  # settings warning last, so a tail-only slice logged neither usefully.
  err="$(cat "$ERRFILE")
$(cat "$OUTFILE")"; errlog="$(head -c 300 "$ERRFILE") ... $(tail -c 300 "$ERRFILE")"; rm -f "$ERRFILE" "$OUTFILE"
  if [ $rc -eq 0 ]; then
    say "OK (attempt $attempt)"
    exit 0
  fi

  case "$err" in
    *"session limit"*|*"usage limit"*|*"rate limit"*|*"limit reached"*|*overloaded*)
      reset_epoch=$(parse_reset_epoch "$err") || reset_epoch=$(( $(now) + 3600 ))
      echo "$reset_epoch" > "$FLAG"
      acct_fp > "$STATE/account"   # record WHICH account got limited (for switch-detect)
      say "LIMIT: deferring until $(date -r "$reset_epoch" '+%F %T') on account $(acct_fp) - switch accounts to resume sooner :: ${errlog:0:100}"
      exit 75 ;;
    *"401"*|*Unauthorized*|*"not logged in"*|*authentication*|*"OAuth"*)
      if [ $attempt -le 2 ]; then
        say "AUTH (attempt $attempt) - account switch in progress? retry in 60s :: ${errlog:0:100}"
        sleep 60; continue
      fi
      say "AUTH FAILED after retries :: ${errlog:0:150}"; exit 1 ;;
    *ECONN*|*ETIMEDOUT*|*ENOTFOUND*|*"fetch failed"*|*"network"*|*"ENETDOWN"*|*"socket"*|*"529"*|*"503"*|*"Could not resolve host"*|*"getaddrinfo"*|*"Name or service not known"*|*"Temporary failure in name resolution"*|*"Connection reset"*|*"EAI_AGAIN"*)
      if [ $attempt -le 3 ]; then
        d=${delays[$((attempt - 1))]}
        say "NET (attempt $attempt) - retry in ${d}s :: ${errlog:0:100}"
        sleep "$d"; continue
      fi
      say "NET FAILED after retries :: ${errlog:0:150}"; exit 1 ;;
    *)
      say "FAIL rc=$rc :: ${errlog:0:200}"; exit $rc ;;
  esac
done
