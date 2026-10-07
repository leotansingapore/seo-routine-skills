# seo-routine-skills

The skills, scripts and pipelines behind Leo's routine SEO work across a fleet of sites. They run unattended on one Mac under launchd: each job finds the work, does it in a throwaway worktree, checks it, ships it and posts a summary to a Lark group.

Client sites are renamed to placeholders (CleaningCo, ParentingBlog, FinanceBlog, ImmigrationCo, VepCo and so on), and webhooks, project IDs and paths are templates. Fill in your own before running anything.

## Install

```bash
git clone https://github.com/leotansingapore/seo-routine-skills.git
cd seo-routine-skills
mkdir -p ~/.claude/skills ~/.local/bin
cp -R skills/* ~/.claude/skills/
cp bin/* ~/.local/bin/
```

Run the weekly content cycle by hand in Claude Code with "run the weekly builds", or headless with `weekly-builds-run.sh`. Example launchd files are in `launchd/`; change `/Users/you` to your home folder before loading them.

## What runs, and when

| Job | Schedule | What it does |
|---|---|---|
| `weekly-builds` skill via `weekly-builds-run.sh` | Monday 10:00 | For each site: pick up new competitor topics, build articles with that site's own tooling, gate them, ship them, check every new page in a browser, then post one summary to Lark. |
| `pipelines/seo-visibility` | every 15 minutes (`seo-visibility dispatch`) | Runs an audit prompt library per site on its own cadence (baseline, weekly pulse, monthly technical, content, backlink and AI-visibility audits, quarterly strategy), fixes the safe findings behind a pre-publish gate, and re-checks each fix on the live site. |
| `pipelines/internal-linking` via `internal-linking-weekly` | Tuesday 03:00 | Finds this week's new pages, scores link candidates with Jev, writes in-text links and a "Keep reading" block, and gives each new page two inbound links. |
| `weekly-content-detector.mjs` | Monday | Diffs competitor sitemaps against last week's snapshot and posts new topics. One reference version; copy it per site. |
| `og-cards-weekly.sh` | Monday 10:30 | Checks and regenerates social share cards. |
| `local-maps-watch` | 1st of the month, 10:20 | A 3x3 Google Maps rank grid per keyword, plus the Business Profile and latest reviews. |
| `rank-watch` | weekly | Top-30 Google ranks for a keyword list via DataForSEO; notifies when a page enters or moves 3+ places. |
| `newsroom-sweep.py`, `newsroom-audit.py` | Monday 09:30, monthly | Watches source newsrooms for changes a content site must reflect, scores them with Jev, and audits the site's links to those sources. |
| `seo-audit-lark-daily.py` | daily | Posts the day's SEO audit results to Lark. |

## Skills

| Skill | Use it to |
|---|---|
| `weekly-builds` | Run the weekly content cycle for every site: detect, build, gate, ship, judge each post against its competitor, improve last month's weakest posts, check every page, post the summary. |
| `anti-ai-writing` | The writing rules every article follows. `aicheck` reads its banned-patterns list. |
| `humanize` | Fix a draft that reads like AI wrote it. Adapted from [MADEVAL/HumanAI](https://github.com/MADEVAL/HumanAI) (MIT, license in the folder). |

The research and page-building skills (`competitor-intel`, `academy-builder` and others) are in [web-dev-skills](https://github.com/leotansingapore/web-dev-skills).

## Helper scripts

| Script | What it does |
|---|---|
| `weekly-builds-run.sh` | The Monday job. Runs the skill once per ISO week and marks the week done only when the run ends with `WEEKLY_BUILDS_COMPLETE`. Needs `gtimeout` (`brew install coreutils`). It runs Claude with `--dangerously-skip-permissions` over scraped competitor pages, so only schedule it on a machine set up for unattended runs. |
| `claude-resilient.sh` | Wraps `claude -p`. Retries on network errors and defers on usage limits with exit 75. |
| `blog-judge` | Jev judges whether a searcher would rather land on our post or the competitor's. Needs Python with `scrapling[fetchers]`. |
| `weekly-visual-qa` | Opens every shipped URL at 390, 768 and 1280px and fails on overflow, page errors, broken images or thin pages. Needs Chrome and playwright-core; set `PLAYWRIGHT_CORE` to its `index.mjs`. |
| `vercel-await-git-deploy` | Waits for Vercel's git build of a pushed commit, so nobody runs `vercel --prod` on top of it. |
| `aicheck` | Scores a draft for AI-writing patterns. Under 15 ships. |

## Pipeline setup

1. `pipelines/seo-visibility` expects its home at `~/.local/share/seo-visibility/`: copy `bin/` and `prompts/` there and `seo-visibility` itself to `~/.local/bin/`, rename `config.example.json` to `config.json`, and add one `sites/<slug>/site.json` per site (repo path, never-touch paths, crawl policy).
2. The audit prompts are not included. The pipeline was built around a third-party Notion prompt library that is not Leo's to publish. Set `SEO_LIBRARY_NOTION_PAGE` to a library you have rights to and `seo-visibility sync` pulls it into `prompts/`.
3. Fixing starts switched off. Set `implement.enabled` in `config.json` once a few audits look right.
4. `pipelines/internal-linking` goes in `~/.local/share/internal-linking/pipeline/`, which is where `internal-linking-weekly` looks for it. Add one `~/.local/share/internal-linking/sites/<slug>.json` per site, and that site's link-file format to the table at the top of `weekly.py`.

## Keys

Put these in your shell profile or `~/.config/agents.env`. Never commit them.

- `TYPESAFE_API_KEY` for Jev (blog-judge, aicheck, internal linking, newsroom scoring)
- `LARK_WEBHOOK` for the summaries, plus one webhook per site group
- DataForSEO login and password for `rank-watch` and `local-maps-watch`
- A Google service account with Search Console access for `gdata.py`
- `VEPCO_SUPABASE_SERVICE_KEY` and `CATALYST_SUPABASE_SERVICE_KEY` to publish on the two sites whose posts live in Supabase

## Not in this repo

- Each site's own detector and content kit (the per-site `*-weekly.mjs` scripts and `~/.local/share/*-content/` kits) and the site repos. Ask Leo for access.
- The seo-visibility audit prompts (see Pipeline setup).
- `copy-corpus`, which the copy pipeline reads. It quotes other companies' copy word for word, so it stays private.

## License

MIT, see `LICENSE`. `skills/humanize` keeps its own MIT license from MADEVAL/HumanAI.
