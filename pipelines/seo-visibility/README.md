# SEO visibility pipeline

Runs an SEO + AI visibility audit prompt library (Notion, set in `SEO_LIBRARY_NOTION_PAGE`) against its sites (table below) on the library's own cadence, fixes the safe findings, and checks every fix on the live site.

| Site | Repo | Specialist day |
| --- | --- | --- |
| digitalmarketingagency.sg | ~/Documents/dma-site | Tuesday |
| catalystoutsourcing.com | ~/Documents/catalyst-refresh-glow | Wednesday |
| vepco.example | ~/vepco-reimagined | Thursday |
| cleaningco.example | ~/cleaningco-cleaning-clone | Friday |
| financeblog.example | ~/Documents/New project/tiny-word-hive | Saturday (added 2026-09-17) |
| immigrationco.example | ~/immigrationco-clone | Tuesday (added 2026-09-17, audit-only) |
| parentingblog.example | ~/parentingblog-clone | Wednesday (added 2026-09-17) |
| paintingco.example | ~/paintingco-clone | Thursday (added 2026-09-17) |
| examprep.example | ~/examprep-clone | Friday (added 2026-09-17) |
| internshipsite.example | ~/Documents/internshipsite-web | Saturday (added 2026-09-17) |
| searchblueprint.io | ~/Documents/seo-audit-tool | Sunday (added 2026-09-17; fixes only outside 09:00-20:00) |
| activity-tracker.io | ~/remix-of-activity-tracker | Sunday (added 2026-10-02; clone from GitHub; fixes push only 03:00-06:59) |

## Schedule

- Baseline (prompt 1): once per site, and again when a single change touches 30% of a repo's files.
- Weekly pulse (prompt 2): Mondays. A site with no commits for 30 days drops to the first Monday of the month.
- Monthly specialists, on the site's own weekday: week 1 technical (3), week 2 content and internal links (4), week 3 backlinks (5, quarterly for a site quiet for 90 days), week 4 AI visibility (6).
- Quarterly strategy (7): first weekend of January, April, July and October. It is skipped when the quarter lacks a technical, content and AI audit.
- Pre-publish gate (8): before every merge the pipeline makes.
- Live validation (9): straight after each deploy, then at 7 and 28 days.
- Digest: Monday 16:00. Each site in config.json `site_lark_webhooks` gets its own update in its own Lark group (read by Leo and his team): what went live, which checks ran, what needs Leo with a paste-into-Claude line per item, and the next checks. Between digests a site group hears only when a NEW item starts waiting on Leo (checked every tick; the first tick after a site is added records what is already waiting and sends nothing). The combined SEO updates group (`lark_webhook`) keeps pipeline alerts and covers only sites without their own group. Site messages are Lark cards (schema 2.0): yellow header when something waits on Leo, each ask in its own highlighted block with the ask and the paste-into-Claude line in bold, fixes in a green block; a refused card falls back to plain text. Preview one site: `seo-visibility report <site>` (text) or `--json` (card). Prompt re-sync from Notion and a data-access probe run on Sundays.

A run the Mac sleeps through catches up later in the same week or month. A Claude usage limit defers the run, and it does not count as a failure. The pipeline reads the limit message from the run's own output, because `claude -p` prints it on stdout, where claude-resilient.sh does not look. Claude jobs then pause until the reset time, or until the CLI switches account. A run that fails three times stops for that period and posts an alert. A failed baseline gets another round every three days.

Fixing starts switched off (`implement.enabled` in config.json), and an unreadable config keeps it off.

## What ships without asking

A finding is fixed unattended only when it is a P0 to P2 in one of these classes, verified, high confidence, low risk and fixable in the repo: broken links, sitemap errors, structured data errors, missing or duplicate metadata, headings, accessibility, performance, and single contextual internal links.

Before any fix ships, it must pass all of these:

- It touches no never-touch or protected path listed in site.json.
- It uses the leotansingapore commit author.
- It removes no more tracking, lead-form or JSON-LD markers than it adds.
- The build passes.
- The prompt 8 gate returns GO.

Once live, prompt 9 checks the fix. A regression it finds is reverted and pushed automatically.

Just before pushing, the pipeline checks four things again:

- the owner has not rejected an item mid-run
- no deploy blackout has started
- production is not serving unpushed work
- the rebased diff still passes every guard

The clone's push URL is disabled, so only the orchestrator's own push lands through `origin`. An agent with a shell could still push by naming the URL directly. What stops that doing harm: every agent run is checked afterwards, and any change to config, site settings, prompts or ledgers is restored and the run discarded; the orchestrator pushes only after re-checking the diff; and every change is checked live. When Vercel never confirms a deploy, nothing is reverted and an alert goes out instead. A run that dies midway is repaired on the next tick, with an alert if its change was already live.

A decision you answer is context, never an approval: every finding needs its own approval, even when it cites an answered decision. Work that lives outside the repositories (Supabase content, dashboards) goes to your queue, because the pipeline cannot ship it.

Redirects, URL changes, noindex, canonicals, robots and AI-crawler policy, copy rewrites, new pages, prices and claims, tracking and hosting all wait for Leo. So does anything outside the repos, such as Search Console, Bing or outreach.

## Leo's commands

- `seo-visibility status`: what ran, what is next, what needs you (also in STATUS.md)
- `seo-visibility approve <ID>` / `reject <ID>` / `done <ID>` / `decide <DEC-ID> "<answer>"`
- `seo-visibility calendar --days 60`
- `seo-visibility run <site> <type>` forces one run now

Telling any Claude session "approve DMA-TECH-004" does the same.

## Files

- `~/.local/bin/seo-visibility`: the orchestrator. Tests are in `tests/`; run `python3 -m unittest discover -s tests`.
- launchd `com.leo.seo-visibility` runs `dispatch` every 15 minutes.
- `prompts/`: verbatim from Notion. CHANGELOG.md records re-syncs.
- `sites/<site>/`: site.json (its `pipeline` block is what the orchestrator executes), context.md, backlog.json, changes.json, runs/, changes/.
- `work/<site>/`: an APFS clone of each repo reset to origin/main. The shared checkouts are never touched.
- `data-access.md`, `bin/gdata.py`, `bin/ask-chatgpt-search.sh`: the data sources audits may use.
- `state/state.json`, `logs/`.

## Secrets in checkouts

A clone is an APFS copy of the checkout, which also copies git-ignored files. `pipeline.strip_ignored` (globs, e.g. `**/.env*`) deletes matching ignored files from the clone on every refresh, and `pipeline.clone_from_remote: true` makes the clone come from GitHub instead, so nothing ignored ever reaches it. internshipsite and searchblueprint use both.
