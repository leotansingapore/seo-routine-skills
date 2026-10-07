#!/usr/bin/env python3
"""Daily Lark digest of who committed what to leotansingapore/seo-audit-tool.

Pulls the last 24h of commits on main via the GitHub API (gh CLI auth),
builds a per-contributor breakdown plus a human-readable summary
(claude CLI, with a deterministic fallback), and posts an interactive
card to the Lark webhook. Runs under launchd daily at 18:00.

Deliberately avoids the local checkout: launchd cannot read ~/Documents (TCC).
ASCII only in all output.
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

REPO = "leotansingapore/seo-audit-tool"
BRANCH = "main"
WEBHOOK = "https://open.larksuite.com/open-apis/bot/v2/hook/<YOUR-WEBHOOK-ID>"
GH = "/opt/homebrew/bin/gh"
CLAUDE = "/Users/you/.local/bin/claude"
LOG = os.path.expanduser("~/.local/state/seo-audit-lark-daily.log")
WINDOW_HOURS = 24


def log(msg):
    line = "%s %s" % (datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def to_ascii(s):
    return s.encode("ascii", "replace").decode("ascii")


def fetch_commits(since_utc):
    commits = []
    page = 1
    while page <= 10:
        url = "repos/%s/commits?sha=%s&since=%s&per_page=100&page=%d" % (
            REPO, BRANCH, since_utc, page)
        out = subprocess.run([GH, "api", url], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError("gh api failed: %s" % out.stderr.strip()[:500])
        batch = json.loads(out.stdout)
        commits.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return commits


def group_by_author(commits):
    groups = {}
    for c in commits:
        if len(c.get("parents", [])) > 1:
            continue  # skip merge commits
        author = (c.get("author") or {}).get("login") or c["commit"]["author"]["name"]
        subject = c["commit"]["message"].split("\n")[0][:120]
        groups.setdefault(author, []).append(subject)
    return groups


def ai_summary(groups):
    lines = []
    for author, subjects in groups.items():
        for s in subjects[:60]:
            lines.append("%s|%s" % (author, s))
    prompt = (
        "Write a daily standup summary of git commits for a team lead. "
        "Input below is one line per commit in the form author|subject.\n"
        "Rules:\n"
        "- Output exactly one line per author, formatted: - <author>: <summary>\n"
        "- Summarize into themes in plain English; do not list every commit.\n"
        "- Max 2 sentences per author. Order authors by commit count, highest first.\n"
        "- Plain ASCII text only. No markdown, no emojis, no preamble, no closing line.\n\n"
        + "\n".join(lines)
    )
    out = subprocess.run(
        [CLAUDE, "-p", "--model", "sonnet"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError("claude CLI failed: %s" % out.stderr.strip()[:300])
    return to_ascii(out.stdout.strip())


def fallback_summary(groups):
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    lines = []
    for author, subjects in ordered:
        shown = "; ".join(subjects[:4])
        more = len(subjects) - 4
        if more > 0:
            shown += " (+%d more)" % more
        lines.append("- %s: %s" % (author, shown))
    return "\n".join(lines)


def build_card(groups, since_local, now_local):
    window = "%s - %s" % (since_local.strftime("%a %d %b %I:%M%p").lower(),
                          now_local.strftime("%a %d %b %I:%M%p").lower())
    title = "SEO Audit Tool - Daily Commit Report (%s)" % now_local.strftime("%a %d %b")

    if not groups:
        body = "No commits pushed to %s in the last %dh.\nWindow: %s" % (BRANCH, WINDOW_HOURS, window)
        return {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}, "template": "grey"},
                "elements": [{"tag": "markdown", "content": body}],
            },
        }

    total = sum(len(v) for v in groups.values())
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    table = ["**%d commits** on %s by %d contributor%s:" % (
        total, BRANCH, len(ordered), "" if len(ordered) == 1 else "s"), ""]
    for author, subjects in ordered:
        share = 100.0 * len(subjects) / total
        table.append("**%s** - %d commits (%.1f%%)" % (author, len(subjects), share))

    try:
        summary = ai_summary(groups)
        log("summary source: claude")
    except Exception as e:
        log("claude summary failed, using fallback: %s" % e)
        summary = fallback_summary(groups)

    return {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [
                {"tag": "markdown", "content": to_ascii("\n".join(table))},
                {"tag": "hr"},
                {"tag": "markdown", "content": to_ascii("**Who did what:**\n" + summary)},
                {"tag": "note", "elements": [{"tag": "plain_text",
                    "content": "Window: %s (merge commits excluded)" % window}]},
            ],
        },
    }


def post_to_lark(payload):
    req = urllib.request.Request(
        WEBHOOK,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("code", body.get("StatusCode", -1)) not in (0,):
        raise RuntimeError("Lark webhook rejected: %s" % body)
    return body


def main():
    now_local = datetime.now().astimezone()
    since_local = now_local - timedelta(hours=WINDOW_HOURS)
    since_utc = since_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    commits = fetch_commits(since_utc)
    groups = group_by_author(commits)
    total = sum(len(v) for v in groups.values())
    log("fetched %d commits (%d after merge filter) across %d authors since %s"
        % (len(commits), total, len(groups), since_utc))

    card = build_card(groups, since_local, now_local)
    post_to_lark(card)
    log("posted to Lark OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("ERROR: %s" % e)
        sys.exit(1)
