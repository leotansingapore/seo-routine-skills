#!/usr/bin/env node
/**
 * Visual QA for freshly published articles. Run at the end of every weekly build,
 * before the Lark summary, on every URL the run shipped.
 *
 *   weekly-visual-qa https://site/a https://site/b
 *   weekly-visual-qa --from-file urls.txt          # one URL per line, blank/# ignored
 *   weekly-visual-qa --json                        # machine-readable to stdout
 *   weekly-visual-qa --out DIR                     # where screenshots land
 *
 * Exit 0 = every page passed. Exit 1 = at least one FAIL. Exit 2 = could not run.
 *
 * A page passes only if, at EVERY viewport, it: navigates, renders exactly one non-empty
 * h1, has no horizontal overflow, throws no JS errors, loads every image it asks for,
 * shows real text above the fold, and carries JSON-LD. Screenshots are written whether
 * or not the page passes, because the failure is usually easier to see than to describe.
 *
 * Uses playwright-core against the system Chrome (no bundled browser download) - see the
 * playwright-mcp-profile-lock note. If that install moves, set PLAYWRIGHT_CORE.
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1280, height: 900 },
];

const args = process.argv.slice(2);
const JSON_OUT = args.includes("--json");
const outIdx = args.indexOf("--out");
const OUT = outIdx >= 0 ? args[outIdx + 1] : path.join(os.tmpdir(), "weekly-visual-qa");
const fileIdx = args.indexOf("--from-file");

let urls = [];
if (fileIdx >= 0) {
  urls = fs.readFileSync(args[fileIdx + 1], "utf8").split("\n")
    .map((l) => l.split("|")[0].trim())
    .filter((l) => l && !l.startsWith("#"));
} else {
  urls = args.filter((a) => /^https?:\/\//.test(a));
}
if (!urls.length) {
  console.error("usage: weekly-visual-qa <url>... | --from-file <file> [--json] [--out DIR]");
  process.exit(2);
}

const CORE = process.env.PLAYWRIGHT_CORE
  || `${process.env.HOME}/remix-of-activity-tracker/node_modules/playwright-core/index.mjs`;
let chromium;
try {
  ({ chromium } = await import(CORE));
} catch (e) {
  console.error(`cannot load playwright-core at ${CORE}: ${e.message}`);
  console.error("set PLAYWRIGHT_CORE to an index.mjs that exists");
  process.exit(2);
}

// Vercel's Security Checkpoint answers automated browsers instead of the site. A
// Protection Bypass for Automation secret gets QA through it while the protection stays
// fully on for everyone else. Sent ONLY to the hosts it belongs to, because a bypass
// secret posted to an arbitrary origin is a leaked secret.
function readAgentsEnv(name) {
  if (process.env[name]) return process.env[name];
  try {
    const txt = fs.readFileSync(path.join(os.homedir(), ".config/agents.env"), "utf8");
    const m = new RegExp(`^\\s*(?:export\\s+)?${name}\\s*=\\s*"?([^"\n]+)"?`, "m").exec(txt);
    return m ? m[1].trim() : "";
  } catch { return ""; }
}
const BYPASS = readAgentsEnv("VERCEL_PROTECTION_BYPASS");
const BYPASS_HOSTS = new Set(readAgentsEnv("VERCEL_BYPASS_HOSTS").split(",").map((h) => h.trim()).filter(Boolean));
function bypassHeadersFor(url) {
  if (!BYPASS) return null;
  let host = "";
  try { host = new URL(url).host; } catch { return null; }
  if (!BYPASS_HOSTS.has(host)) return null;
  return { "x-vercel-protection-bypass": BYPASS, "x-vercel-set-bypass-cookie": "true" };
}

fs.mkdirSync(OUT, { recursive: true });
const slug = (u) => u.replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 80);

// Third-party noise that says nothing about whether OUR page is broken.
const IGNORE_ERR = /gtag|googletag|doubleclick|facebook|fbq|hotjar|clarity|analytics|ResizeObserver loop|Non-Error promise rejection/i;

// Evaluated once, and again if the first look is suspiciously thin.
const PROBE = () => {
      const de = document.documentElement;
      const h1s = [...document.querySelectorAll("h1")].filter((h) => h.textContent.trim().length > 0);
      // Which elements actually stick out past the viewport - naming them makes the fix obvious.
      const offenders = [];
      const vw = window.innerWidth;
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.right > vw + 2 || r.left < -2) {
          const cs = getComputedStyle(el);
          if (cs.position === "fixed" || cs.visibility === "hidden" || cs.display === "none") continue;
          offenders.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.split(" ")[0] : ""} (${Math.round(r.width)}px)`);
          if (offenders.length >= 4) break;
        }
      }
      const imgs = [...document.querySelectorAll("img")];
      // A lazy image the browser has deliberately not fetched reports complete:true and
      // naturalWidth:0, which is indistinguishable from a broken one unless you also ask
      // where it is. Off-screen lazy images are skipped; a genuinely broken one still gets
      // caught once it scrolls into range, and every in-view image is checked as before.
      // (Caught 2026-09-15: a perfectly good SVG on catalystoutsourcing.com/blog was
      // reported broken on two consecutive runs purely for being below the fold.)
      const broken = imgs.filter((i) => {
        if (!i.currentSrc || !i.complete || i.naturalWidth !== 0) return false;
        const r = i.getBoundingClientRect();
        const near = r.top < window.innerHeight * 2 && r.bottom > -window.innerHeight;
        return !(i.loading === "lazy" && !near);
      }).map((i) => (i.currentSrc || i.src).slice(-70));
      // Real text in the first screen, so a blank or hero-only render is caught.
      let foldText = 0;
      for (const el of document.querySelectorAll("p, li, td, h1, h2")) {
        const r = el.getBoundingClientRect();
        if (r.top < window.innerHeight && r.bottom > 0) foldText += el.textContent.trim().length;
      }
      return {
        overflow: de.scrollWidth > vw + 1,
        overflowBy: Math.max(0, de.scrollWidth - vw),
        offenders,
        h1Count: h1s.length,
        h1: h1s.length ? h1s[0].textContent.trim().slice(0, 70) : null,
        brokenImages: broken,
        imgCount: imgs.length,
        foldText,
        jsonLd: document.querySelectorAll('script[type="application/ld+json"]').length,
        bodyText: document.body.innerText.trim().length,
      };
    };

const browser = await chromium.launch({ channel: "chrome", headless: true });
const results = [];

for (const url of urls) {
  const page_result = { url, viewports: {}, fails: [], warns: [] };

  const bypass = bypassHeadersFor(url);
  if (bypass) page_result.usedBypass = true;
  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({
      viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1,
    });
    // Per request, not context-wide: extraHTTPHeaders would send the secret to every
    // third-party subresource. route.continue() header overrides are re-sent on every
    // redirect hop, so fetch with redirects off and hand the 3xx back for the browser to follow.
    // ponytail: the browser follows that hop without the bypass, so a redirected URL behind the
    // Security Checkpoint reports SKIP; pass final URLs, or follow allowlisted hops here if needed.
    if (bypass) await ctx.route("**/*", async (route) => {
      const req = route.request();
      if (!bypassHeadersFor(req.url())) return route.continue();
      const response = await route.fetch({ headers: { ...req.headers(), ...bypass }, maxRedirects: 0 });
      return route.fulfill({ response });
    });
    const page = await ctx.newPage();
    const jsErrors = [];
    page.on("pageerror", (e) => { const s = String(e); if (!IGNORE_ERR.test(s)) jsErrors.push(s.slice(0, 160)); });
    page.on("console", (m) => { if (m.type() === "error") { const s = m.text(); if (!IGNORE_ERR.test(s)) jsErrors.push(s.slice(0, 160)); } });

    let status = 0;
    try {
      const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
      status = resp ? resp.status() : 0;
      await page.waitForTimeout(1800);
    } catch (e) {
      page_result.fails.push(`${vp.name}: navigation failed - ${String(e).slice(0, 90)}`);
      await ctx.close();
      continue;
    }

    const probe = await page.evaluate(PROBE);

    // A bot challenge is not a broken page. Vercel's Attack Challenge Mode serves a
    // checkpoint to automated browsers while curl still gets the real HTML, so five
    // "no h1 / too thin / JS error" lines would be pure noise. Say what it is instead.
    // Title-only detection races the challenge page: if it has not set its title within
    // the wait above, a checkpoint reads as a broken article instead (seen 2026-09-15).
    // A 403/503 carrying almost no text is a challenge or a block either way, and calling
    // it "no h1, body too thin" would be a confident wrong answer.
    const challenged = await page.evaluate(() =>
      /Security Checkpoint|Just a moment|Checking your browser|Attention Required|Access denied/i.test(document.title)
      || /Failed to verify your browser|Enable JavaScript and cookies to continue/i.test(document.body.innerText)
      || !!document.querySelector('[data-astro-cid-4wdtffzm] .spinner, #challenge-running'))
      || ((status === 403 || status === 503) && probe.bodyText < 400);
    if (challenged) {
      page_result.challenged = true;
      page_result.warns.push(`${vp.name}: bot challenge intercepted the request (HTTP ${status}, title "${await page.title()}") - the page itself was never reached`);
      await page.screenshot({ path: path.join(OUT, `${slug(url)}__${vp.name}__challenged.png`) });
      page_result.viewports[vp.name] = { status, challenged: true, jsErrors: [] };
      await ctx.close();
      continue;
    }

    // Client-rendered pages can still be settling when the probe runs, which reads as
    // "only 72 chars above the fold" on a page whose h1 is plainly visible a second later
    // (seen on a finance blog, 2026-09-15). Give a thin-looking page one more chance
    // before calling it broken, rather than reporting a confident false positive.
    let settled = probe;
    if (settled.foldText < 120 || settled.bodyText < 1200) {
      await page.waitForTimeout(3000);
      settled = await page.evaluate(PROBE);
    }

    const shot = path.join(OUT, `${slug(url)}__${vp.name}.png`);
    await page.screenshot({ path: shot, fullPage: false });

    page_result.viewports[vp.name] = { status, ...settled, jsErrors, screenshot: shot };

    if (status >= 400 || status === 0) page_result.fails.push(`${vp.name}: HTTP ${status}`);
    if (settled.overflow) page_result.fails.push(`${vp.name}: horizontal overflow by ${settled.overflowBy}px - ${settled.offenders.join(", ") || "source not identified"}`);
    if (settled.h1Count === 0) page_result.fails.push(`${vp.name}: no non-empty h1`);
    if (settled.h1Count > 1) page_result.warns.push(`${vp.name}: ${settled.h1Count} h1 elements`);
    if (jsErrors.length) page_result.fails.push(`${vp.name}: ${jsErrors.length} JS error(s) - ${jsErrors[0]}`);
    if (settled.brokenImages.length) page_result.fails.push(`${vp.name}: ${settled.brokenImages.length} broken image(s) - ${settled.brokenImages[0]}`);
    // A warning, not a failure: an image-led hero legitimately carries little text in the
    // first screen, and calling that "not rendering" was a false positive on a page whose
    // h1 was plainly visible. A genuinely blank page is caught by the body-length check.
    if (settled.foldText < 120) page_result.warns.push(`${vp.name}: only ${settled.foldText} chars of text above the fold - check the hero is not all image`);
    if (settled.bodyText < 1200) page_result.fails.push(`${vp.name}: body text ${probe.bodyText} chars, too thin for an article`);
    if (settled.jsonLd === 0) page_result.warns.push(`${vp.name}: no JSON-LD`);

    await ctx.close();
  }

  page_result.pass = page_result.fails.length === 0;
  // Every viewport bounced off a challenge: we learned nothing about this page.
  if (page_result.challenged && page_result.fails.length === 0) page_result.unknown = true;
  results.push(page_result);

  if (!JSON_OUT) {
    const d = page_result.viewports.desktop || {};
    console.log(`${page_result.unknown ? "SKIP" : page_result.pass ? "PASS" : "FAIL"}  ${page_result.url}`);
    console.log(`      h1: ${d.h1 ?? "-"}`);
    console.log(`      ${d.bodyText ?? 0} chars | ${d.imgCount ?? 0} images | ld+json ${d.jsonLd ?? 0}`);
    for (const f of page_result.fails) console.log(`      FAIL ${f}`);
    for (const w of page_result.warns) console.log(`      warn ${w}`);
  }
}

await browser.close();

const failed = results.filter((r) => !r.pass);
const unknown = results.filter((r) => r.unknown);
if (JSON_OUT) {
  console.log(JSON.stringify({ total: results.length, passed: results.length - failed.length, failed: failed.length, out: OUT, results }, null, 2));
} else {
  console.log(`\n${results.length - failed.length - unknown.length}/${results.length - unknown.length} inspectable pages passed across ${VIEWPORTS.map((v) => v.width + "px").join(", ")}`);
  if (unknown.length) console.log(`${unknown.length} page(s) could not be inspected - a bot challenge answered instead of the site. Not a verdict either way.`);
  console.log(`screenshots: ${OUT}`);
  if (failed.length) console.log(`FAILED: ${failed.map((f) => f.url).join(", ")}`);
}
process.exit(failed.length ? 1 : 0);
