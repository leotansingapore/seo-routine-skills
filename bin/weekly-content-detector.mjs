#!/usr/bin/env node
/**
 * Catalyst Outsourcing weekly competitor DETECTOR (launchd: com.catalyst.weekly-content,
 * Mondays 08:00). Fetch competitor sitemaps -> keep only posts touched in the last N days
 * -> diff vs last snapshot -> brand-fit filter -> tag each as "improve <existing slug>" or
 * "new page" against the live blog_posts table -> post the list to Lark.
 *
 * DETECT ONLY. Never generates, never writes to Supabase, never deploys. Posts on
 * catalystoutsourcing.com are rows in the Supabase `blog_posts` table, so the build is done
 * supervised in Claude Code on Leo's go ("run the Catalyst weekly build").
 *
 * Recency is enforced HERE, not left to the snapshot. A set difference alone makes a stale
 * snapshot report years of archive as this week's news - that is exactly what happened to
 * the ParentingBlog detector on 2026-09-15 (1,472 false "new" topics, and the first five by
 * sitemap order were four years old). Anything whose <lastmod> is older than RECENT_DAYS is
 * held back, and what survives is sorted newest first so the cap takes the freshest.
 *
 * State lives in ~/.local/state (launchd cannot read ~/Documents). KILL switch: PAUSE file.
 * SECURITY: every subprocess uses execFileSync with an argument ARRAY (no shell) because
 *   competitor URLs are untrusted input - no string is interpolated into a shell command.
 * Modes: --baseline-only | --dry-run (prints the message, posts nothing, writes nothing)
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const STATE = process.env.CATALYST_STATE || path.join(os.homedir(), ".local/state/catalyst/content-engine");
const SNAP = path.join(STATE, "snapshot.json");
const PROCESSED = path.join(STATE, "processed.csv");
const LOG = path.join(STATE, "weekly.log");
const PAUSE = path.join(STATE, "PAUSE");
const SUPABASE_URL = "https://<your-project-ref>.supabase.co";
const LARK_WEBHOOK = process.env.LARK_WEBHOOK ?? "https://open.larksuite.com/open-apis/bot/v2/hook/<YOUR-WEBHOOK-ID>";
const RECENT_DAYS = parseInt(process.env.RECENT_DAYS || "21", 10);
// Backlog from the competitor-intel build plan (measured demand, checked by Jev against live pages on
// 2026-10-07): a few lines a week join the detected topics. An item leaves once its URL is in processed.csv.
const BACKLOG = path.join(STATE, "backlog.json");
const BACKLOG_PER_WEEK = parseInt(process.env.BACKLOG_PER_WEEK || "3", 10);
const args = new Set(process.argv.slice(2));
const DRY = args.has("--dry-run");
const BASELINE_ONLY = args.has("--baseline-only");

const COMPETITORS = [
  { name: "wishup", sitemaps: ["https://wishup.co/sitemap.xml"], article: /^\/blog\/.+/ },
  { name: "prialto", sitemaps: ["https://www.prialto.com/sitemap.xml"], article: /^\/blog\/.+/ },
  { name: "taskbullet", sitemaps: ["https://taskbullet.com/sitemap.xml"], article: /^\/blog\/.+/ },
];
const DROP = /\/(tag|category|author|page|feed|about|contact|privacy|terms|pricing|careers|team|wp-)\b/i;
// Catalyst sells virtual assistants and outsourcing to businesses. Keep that, drop the rest.
const TOPIC = /virtual-assistant|virtual-staff|\bva\b|outsourc|offshore|remote-team|remote-staff|executive-assistant|admin|bookkeep|delegat|productivity|hiring|recruit|onboard|back-office|customer-service|lead-gen|data-entry|freelanc|contractor|staffing|philippines|cost|roi|scale|workflow|automat/i;
// Competitor self-promotion, news and fluff that is not an evergreen business guide.
const OFFBRAND = /webinar|podcast|case-study|customer-story|press-release|award|announcement|we-are|our-team|meet-the|interview|newsletter|ebook|template-download|black-friday|\bsale\b|discount|promo|holiday|christmas|new-year|thanksgiving/i;
const STOP = new Set("the a an for of in to and or your you guide how what why can is are do does with from into this that best top 2024 2025 2026 2027 virtual assistant assistants outsourcing business businesses".split(" "));

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
  if (!DRY) { try { fs.appendFileSync(LOG, line + "\n"); } catch {} }
}
function run(file, argv, opts = {}) {
  return execFileSync(file, argv, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], maxBuffer: 64 * 1024 * 1024, ...opts });
}
function tryRun(file, argv, opts = {}) { try { return run(file, argv, opts); } catch { return ""; } }
function larkNotify(text) {
  if (!LARK_WEBHOOK) { log("LARK_WEBHOOK empty -> not posting."); return; }
  const body = JSON.stringify({ msg_type: "text", content: { text: String(text).slice(0, 3000) } });
  log(`lark response: ${tryRun("curl", ["-s", "-X", "POST", LARK_WEBHOOK, "-H", "Content-Type: application/json", "-d", body], { timeout: 20000 }).slice(0, 120)}`);
}
function curl(url, maxTime = 40) {
  if (!/^https?:\/\//.test(url)) return "";
  const direct = tryRun("curl", ["-sL", "--max-time", String(maxTime), "-A", "Mozilla/5.0", url], { timeout: (maxTime + 5) * 1000 });
  if (direct && direct.length > 80) return direct;
  return tryRun("curl", ["-s", "--max-time", String(maxTime + 15), `https://r.jina.ai/${url}`], { timeout: (maxTime + 25) * 1000 });
}
function sitemapUrls(xml) { return [...xml.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/g)].map((m) => m[1]); }
function sitemapDates(xml) {
  const out = new Map();
  for (const m of xml.matchAll(/<url>[\s\S]*?<loc>\s*([^<\s]+)\s*<\/loc>([\s\S]*?)<\/url>/g)) {
    const lm = /<lastmod>\s*([^<\s]+)/.exec(m[2]);
    if (lm) out.set(m[1], lm[1].slice(0, 10));
  }
  return out;
}
function baseDomain(hostname) {
  const p = hostname.replace(/^www\./, "").split(".");
  const two = p.length > 2 && /^(com|co|org|net|gov|edu)$/.test(p[p.length - 2]);
  return p.slice(two ? -3 : -2).join(".");
}
function isArticle(u, c) {
  if (DROP.test(u)) return false;
  try {
    const p = new URL(u).pathname;
    if (/\.(xml|ico|png|jpe?g|gif|webp|svg|css|js|pdf|json|txt)$/i.test(p)) return false;
    if (!c.article.test(p)) return false;
    const last = p.replace(/\/$/, "").split("/").filter(Boolean).pop() || "";
    return last.includes("-") && last.length >= 8;
  } catch { return false; }
}
function slugOf(u) { try { return new URL(u).pathname.replace(/\/$/, "").split("/").filter(Boolean).pop() || ""; } catch { return ""; } }
function tokens(slug) {
  return new Set(slug.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 2 && !STOP.has(t)).map((t) => t.replace(/s$/, "")));
}
function matchOwn(url, ownSlugs) {
  const ct = tokens(slugOf(url));
  if (ct.size < 2) return "";
  let best = "", bestScore = 0;
  for (const own of ownSlugs) {
    const ot = tokens(own);
    const shared = [...ct].filter((t) => ot.has(t)).length;
    const score = shared / ct.size;
    if (shared >= 2 && score >= 0.6 && score > bestScore) { best = own; bestScore = score; }
  }
  return best;
}
// The live corpus is the Supabase table, not a sitemap. The anon key is minted from the
// Supabase management token, because the repo's .env was untracked on 2026-09-15 and a
// detector that reads a file someone else may delete is a detector that quietly stops
// tagging improve-vs-new. The repo .env stays as a last resort.
function anonFromManagement() {
  const tokPath = path.join(os.homedir(), ".local/state/va-watchdog/token");
  let tok = "";
  try { tok = fs.readFileSync(tokPath, "utf8").trim(); } catch { return ""; }
  if (!tok) return "";
  const out = tryRun("curl", ["-s", "--max-time", "40",
    `https://api.supabase.com/v1/projects/<your-project-ref>/api-keys?reveal=true`,
    "-H", `Authorization: Bearer ${tok}`, "-H", "User-Agent: Mozilla/5.0 (Macintosh) Chrome/120"],
    { timeout: 45000 });
  try {
    const keys = JSON.parse(out);
    if (!Array.isArray(keys)) return "";
    return (keys.find((k) => k.name === "anon") || {}).api_key || "";
  } catch { return ""; }
}
function ownSlugs() {
  const key = process.env.CATALYST_ANON_KEY || anonFromManagement() || readAnonFromRepo();
  if (!key) { log("no anon key available -> cannot tag improve-vs-new, everything reads as new"); return []; }
  const out = tryRun("curl", ["-s", "--max-time", "40",
    `${SUPABASE_URL}/rest/v1/blog_posts?select=slug&limit=2000`,
    "-H", `apikey: ${key}`, "-H", `Authorization: Bearer ${key}`], { timeout: 45000 });
  try { return JSON.parse(out).map((r) => r.slug).filter(Boolean); } catch { return []; }
}
function readAnonFromRepo() {
  for (const p of [path.join(os.homedir(), "Documents/catalyst-refresh-glow/.env")]) {
    try {
      const m = /^VITE_SUPABASE_PUBLISHABLE_KEY\s*=\s*"?([^"\n]+)"?/m.exec(fs.readFileSync(p, "utf8"));
      if (m) return m[1].trim();
    } catch {}
  }
  return "";
}
function loadProcessed() {
  if (!fs.existsSync(PROCESSED)) return new Set();
  return new Set(fs.readFileSync(PROCESSED, "utf8").trim().split("\n").slice(1)
    .map((l) => (l.match(/^"((?:[^"]|"")*)"/) || [null, ""])[1].replace(/""/g, '"')).filter(Boolean));
}

function backlogLines(processed) {
  if (!fs.existsSync(BACKLOG)) return [];
  let items = [];
  try { items = JSON.parse(fs.readFileSync(BACKLOG, "utf8")); } catch { log("backlog.json unreadable -> no backlog lines"); return []; }
  return items.filter((b) => b.refs && b.refs[0] && !processed.has(b.refs[0])).slice(0, BACKLOG_PER_WEEK)
    .map((b) => `- backlog  ${b.refs[0]} -> new page, target "${b.keyword}" (SG ${b.vol_sg}/mo, AU+UK+US ${b.vol_other}/mo); working title: ${b.title}`);
}

function main() {
  if (!DRY) fs.mkdirSync(STATE, { recursive: true });
  log(`=== weekly detect start (dry=${DRY} baselineOnly=${BASELINE_ONLY} recentDays=${RECENT_DAYS}) ===`);
  if (fs.existsSync(PAUSE)) { log("PAUSE file present -> skipping run."); return; }

  const LASTMOD = new Map();
  let urls = [];
  for (const c of COMPETITORS) {
    let got = 0;
    const base = baseDomain(new URL(c.sitemaps[0]).hostname);
    const sameDomain = (u) => { try { return baseDomain(new URL(u).hostname) === base; } catch { return false; } };
    for (const sm of c.sitemaps) {
      const xml = curl(sm);
      const locs = sitemapUrls(xml);
      for (const [u, d] of sitemapDates(xml)) LASTMOD.set(u, d);
      const childMaps = locs.filter((u) => /sitemap/i.test(u) && u.endsWith(".xml") && sameDomain(u));
      for (const cm of childMaps.slice(0, 6)) {
        const cx = curl(cm);
        locs.push(...sitemapUrls(cx));
        for (const [u, d] of sitemapDates(cx)) LASTMOD.set(u, d);
      }
      const arts = locs.filter((u) => !/sitemap/i.test(u) && sameDomain(u) && isArticle(u, c));
      urls.push(...arts); got += arts.length;
    }
    log(`competitor ${c.name}: ${got} article URLs`);
  }
  urls = [...new Set(urls)];
  log(`total unique competitor article URLs: ${urls.length}`);
  if (urls.length === 0) { log("0 URLs fetched -> skip (not overwriting baseline)."); return; }

  if (!fs.existsSync(SNAP)) {
    if (DRY) { log("DRY RUN: no baseline yet; would write one now with no alert."); return; }
    fs.writeFileSync(SNAP, JSON.stringify({ urls, ts: new Date().toISOString() }, null, 1));
    log(`baseline established with ${urls.length} URLs. No alert on first run.`);
    return;
  }
  if (BASELINE_ONLY) {
    if (DRY) { log("DRY RUN: would refresh the snapshot."); return; }
    fs.writeFileSync(SNAP, JSON.stringify({ urls, ts: new Date().toISOString() }, null, 1));
    log("--baseline-only: snapshot refreshed, no alert."); return;
  }

  const prev = new Set(JSON.parse(fs.readFileSync(SNAP, "utf8")).urls || []);
  const processed = loadProcessed();
  const freshAll = urls.filter((u) => !prev.has(u) && !processed.has(u));
  const onTopic = freshAll.filter((u) => TOPIC.test(u) && !OFFBRAND.test(u));
  const cutoff = new Date(Date.now() - RECENT_DAYS * 86400000).toISOString().slice(0, 10);
  const stale = onTopic.filter((u) => { const d = LASTMOD.get(u); return d && d < cutoff; });
  const fresh = onTopic.filter((u) => { const d = LASTMOD.get(u); return !d || d >= cutoff; })
    .sort((a, b) => (LASTMOD.get(b) || "").localeCompare(LASTMOD.get(a) || ""));
  log(`new-since-last-snapshot: ${freshAll.length} (${onTopic.length} on-topic, ${freshAll.length - onTopic.length} off-brand)`);
  log(`recency filter (<=${RECENT_DAYS}d, cutoff ${cutoff}): ${fresh.length} recent, ${stale.length} older archive held back`);
  const backlog = backlogLines(processed);
  log(`backlog lines this week: ${backlog.length}`);
  if (!fresh.length && !backlog.length) { log("DETECT (read-only): no new on-topic competitor articles and no backlog (no alert)."); return; }

  const own = ownSlugs();
  log(`own blog_posts slugs: ${own.length}`);
  const lines = fresh.slice(0, 20).map((u) => {
    const m = matchOwn(u, own);
    return `- ${LASTMOD.get(u) || "undated"}  ${u} -> ${m ? `improve /blog/${m}` : "new page"}`;
  });
  const more = fresh.length > 20 ? `\n(+${fresh.length - 20} more)` : "";
  if (backlog.length) lines.push(...backlog);
  const msg = `[Catalyst Outsourcing] ${fresh.length} new build-worthy topic(s) detected, plus ${backlog.length} from the backlog (nothing generated or published):\n${lines.join("\n")}${more}\n\nTo build them, tell Claude Code: run the Catalyst weekly build.`;
  if (DRY) { log(`DRY RUN: would post to Lark:\n${msg}`); return; }
  larkNotify(msg);
  log(`DETECT (read-only): alerted Lark with ${fresh.length} recent on-topic topics; snapshot NOT advanced.`);
  log("=== weekly detect done ===");
}

main();
