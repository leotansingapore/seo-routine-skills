#!/usr/bin/env python3
"""gdata.py - read-only Search Console, GA4 and Bing Webmaster data for the seo-visibility audits.

Credentials stay where they already live (nothing is copied):
  Google: service account ~/.local/bin/credentials.json
          (seo-reporting@your-gcp-project.iam.gserviceaccount.com), JWT signed with openssl
  Bing:   BING_WEBMASTER_API_KEY in ~/.config/agents.env

  gdata.py probe                                  JSON: what this machine can read right now, per site
  gdata.py gsc-sites
  gdata.py gsc-query <slug|property> <start> <end> [--dims query,page] [--limit 100] [--type web] [--country sgp]
  gdata.py gsc-sitemaps <slug|property>
  gdata.py gsc-inspect <slug|property> <url>
  gdata.py gsc-sync-sitemaps <slug> [--dry-run yes]   WRITE: submit the sitemaps robots.txt and site.json declare,
                                                  delete listed ones that no longer answer 200 (all properties)
  gdata.py ga4-properties
  gdata.py ga4-report <slug|propertyId> <start> <end> --dims sessionSource,landingPage --metrics sessions,keyEvents [--limit 100]
  gdata.py bing-sites
  gdata.py bing <Method> <slug|siteUrl> [extra=value ...]   e.g. bing GetQueryStats cleaningco, bing GetLinkCounts dma

Dates are YYYY-MM-DD. Output is JSON on stdout. Exit 4 = no access (403/401/missing key).
Until Leo grants the service account access in Search Console / GA4, Google calls exit 4.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

SA_PATH = os.path.expanduser("~/.local/bin/credentials.json")
ENV_PATH = os.path.expanduser("~/.config/agents.env")
SITES = {
    "dma": "digitalmarketingagency.sg",
    "catalyst": "catalystoutsourcing.com",
    "vepco": "vepco.example",
    "cleaningco": "cleaningco.example",
    "activitytracker": "activity-tracker.io",
}
SITES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sites")
for _f in __import__("glob").glob(os.path.join(SITES_DIR, "*", "site.json")):
    try:
        _d = json.load(open(_f))
        SITES.setdefault(_d["slug"], urllib.parse.urlparse(_d["production_url"]).netloc.replace("www.", "", 1))
    except Exception:
        pass
WRITE_SCOPE = "https://www.googleapis.com/auth/webmasters"
SCOPES = "https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/analytics.readonly"


class NoAccess(Exception):
    pass


def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def env_value(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in open(ENV_PATH):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


_TOKENS = {}


def google_token(scopes=None):
    scopes = scopes or SCOPES
    _TOKEN = _TOKENS.setdefault(scopes, {})
    if _TOKEN.get("exp", 0) > time.time() + 60:
        return _TOKEN["token"]
    sa = json.load(open(SA_PATH))
    now = int(time.time())
    header = b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64u(json.dumps({"iss": sa["client_email"], "scope": scopes, "aud": sa["token_uri"],
                              "iat": now, "exp": now + 3600}).encode())
    unsigned = ("%s.%s" % (header, claims)).encode()
    fd, keyfile = tempfile.mkstemp(prefix="gdata-", dir="/private/tmp")
    try:
        os.chmod(keyfile, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(sa["private_key"])
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", keyfile], input=unsigned,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    finally:
        os.remove(keyfile)
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": "%s.%s" % (unsigned.decode(), b64u(sig))}).encode()
    resp = json.loads(urllib.request.urlopen(sa["token_uri"], data=body, timeout=30).read().decode())
    _TOKEN.update({"token": resp["access_token"], "exp": now + int(resp.get("expires_in", 3600))})
    return _TOKEN["token"]


def call(url, body=None, method=None, bearer=True, scopes=None):
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + google_token(scopes)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read().decode() or "{}")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:400]
        if e.code in (401, 403):
            raise NoAccess("%s %s" % (e.code, text))
        raise RuntimeError("%s %s" % (e.code, text))


def gsc_sites():
    return call("https://www.googleapis.com/webmasters/v3/sites").get("siteEntry", [])


def gsc_property(ident):
    if ident not in SITES:
        return ident
    domain = SITES[ident]
    entries = [s for s in gsc_sites() if domain in s.get("siteUrl", "") and s.get("permissionLevel") != "siteUnverifiedUser"]
    if not entries:
        raise NoAccess("no Search Console property for %s is shared with the service account" % domain)
    entries.sort(key=lambda s: (not s["siteUrl"].startswith("sc-domain:"), len(s["siteUrl"])))
    return entries[0]["siteUrl"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def url_final(url, hops=6):
    """(final status, final url), following redirects by hand: Python 3.9 urllib does not follow 308."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(hops):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) seo-visibility"})
        try:
            return opener.open(req, timeout=30).status, url
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            return e.code, url
        except Exception:
            return None, url
    return None, url


def url_status(url):
    return url_final(url)[0]


def gsc_sync_sitemaps(slug, dry_run=False):
    """Make every Search Console property of a site list exactly the live sitemaps it declares."""
    site = json.load(open(os.path.join(SITES_DIR, slug, "site.json")))
    base = site["production_url"].rstrip("/")
    declared = []
    try:
        robots = urllib.request.urlopen(urllib.request.Request(base + "/robots.txt", headers={
            "User-Agent": "Mozilla/5.0 (Macintosh) seo-visibility"}), timeout=30).read().decode("utf-8", "replace")
        declared += [l.split(":", 1)[1].strip() for l in robots.splitlines() if l.lower().startswith("sitemap:")]
    except Exception:
        pass
    for sm in site.get("sitemaps") or []:
        declared.append(sm if isinstance(sm, str) else sm.get("url"))
    live = [u for u in dict.fromkeys(u for u in declared if u) if url_status(u) == 200]
    domain = SITES[slug]
    props = [s["siteUrl"] for s in gsc_sites() if domain in s["siteUrl"] and s.get("permissionLevel") in ("siteOwner", "siteFullUser")]
    if not props:
        raise NoAccess("no writable Search Console property for %s" % domain)
    main_prop = gsc_property(slug)
    q = lambda v: urllib.parse.quote(v, safe="")
    out = {"site": slug, "declared_live": live, "submitted": [], "deleted": [], "kept": [], "dry_run": dry_run}
    for prop in props:
        root = "https://www.googleapis.com/webmasters/v3/sites/%s/sitemaps" % q(prop)
        for sm in call(root, scopes=WRITE_SCOPE).get("sitemap", []):
            path = sm["path"]
            if path in live:
                out["kept"].append([prop, path, sm.get("errors"), sm.get("lastDownloaded")])
                continue
            code, final = url_final(path)
            # gone for good, or a redirect onto a sitemap already declared; anything else
            # (5xx, 403 checkpoint, timeout, a live undeclared file) is left alone
            if code in (404, 410) or (code == 200 and final != path and final in live):
                if not dry_run:
                    call(root + "/" + q(path), method="DELETE", scopes=WRITE_SCOPE)
                out["deleted"].append([prop, path, code if final == path else "%s via %s" % (code, final)])
            else:
                out["kept"].append([prop, path, "undeclared, answers %s" % code])
        if prop == main_prop:
            listed = {k[1] for k in out["kept"] if k[0] == prop}
            for u in live:
                if u not in listed:
                    if not dry_run:
                        call(root + "/" + q(u), method="PUT", scopes=WRITE_SCOPE)
                    out["submitted"].append([prop, u])
    return out


def ga4_properties():
    out = []
    page = ""
    while True:
        r = call("https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=200" + ("&pageToken=" + page if page else ""))
        for acc in r.get("accountSummaries", []):
            for p in acc.get("propertySummaries", []):
                pid = p["property"].split("/")[1]
                streams = call("https://analyticsadmin.googleapis.com/v1beta/properties/%s/dataStreams" % pid).get("dataStreams", [])
                out.append({"account": acc.get("displayName"), "property_id": pid, "name": p.get("displayName"),
                            "streams": [{"measurement_id": (s.get("webStreamData") or {}).get("measurementId"),
                                         "uri": (s.get("webStreamData") or {}).get("defaultUri")} for s in streams]})
        page = r.get("nextPageToken")
        if not page:
            return out


def ga4_property(ident):
    if ident not in SITES:
        return ident
    for p in ga4_properties():
        if any(SITES[ident] in (s.get("uri") or "") for s in p["streams"]):
            return p["property_id"]
    raise NoAccess("no GA4 property with a web stream for %s is shared with the service account" % SITES[ident])


def bing(method, site=None, **params):
    key = env_value("BING_WEBMASTER_API_KEY")
    if not key:
        raise NoAccess("BING_WEBMASTER_API_KEY is not set in ~/.config/agents.env")
    q = {"apikey": key}
    if site:
        q["siteUrl"] = "https://www.%s/" % SITES[site] if site in SITES and site != "catalyst" else (
            "https://%s/" % SITES[site] if site in SITES else site)
    q.update(params)
    url = "https://ssl.bing.com/webmaster/api.svc/json/%s?%s" % (method, urllib.parse.urlencode(q))
    return call(url, bearer=False)


def probe():
    out = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sites": {}}
    try:
        visible = [s["siteUrl"] for s in gsc_sites()]
        out["gsc_error"] = None
    except Exception as e:
        visible, out["gsc_error"] = [], str(e)[:200]
    try:
        props = ga4_properties()
        out["ga4_error"] = None
    except Exception as e:
        props, out["ga4_error"] = [], str(e)[:200]
    try:
        bsites = [s.get("Url") for s in (bing("GetUserSites").get("d") or [])]
        out["bing_error"] = None
    except Exception as e:
        bsites, out["bing_error"] = [], str(e)[:200]
    for slug, domain in SITES.items():
        out["sites"][slug] = {
            "gsc": [u for u in visible if domain in u],
            "ga4": [p["property_id"] for p in props if any(domain in (s.get("uri") or "") for s in p["streams"])],
            "bing": [u for u in bsites if u and domain in u],
        }
    return out


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    opts, pos = {}, []
    i = 0
    while i < len(args):
        if args[i].startswith("--") and i + 1 < len(args):
            opts[args[i][2:]] = args[i + 1]
            i += 2
        else:
            pos.append(args[i])
            i += 1
    try:
        if cmd == "probe":
            res = probe()
        elif cmd == "gsc-sites":
            res = gsc_sites()
        elif cmd == "gsc-query":
            prop = gsc_property(pos[0])
            body = {"startDate": pos[1], "endDate": pos[2], "dimensions": opts.get("dims", "query,page").split(","),
                    "rowLimit": int(opts.get("limit", 100)), "type": opts.get("type", "web")}
            if opts.get("country"):
                body["dimensionFilterGroups"] = [{"filters": [{"dimension": "country", "operator": "equals",
                                                               "expression": opts["country"]}]}]
            res = call("https://www.googleapis.com/webmasters/v3/sites/%s/searchAnalytics/query" % urllib.parse.quote(prop, safe=""), body)
            res["property"] = prop
        elif cmd == "gsc-sitemaps":
            prop = gsc_property(pos[0])
            res = call("https://www.googleapis.com/webmasters/v3/sites/%s/sitemaps" % urllib.parse.quote(prop, safe=""))
        elif cmd == "gsc-sync-sitemaps":
            res = gsc_sync_sitemaps(pos[0], dry_run=bool(opts.get("dry-run")))
        elif cmd == "gsc-inspect":
            prop = gsc_property(pos[0])
            res = call("https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                       {"inspectionUrl": pos[1], "siteUrl": prop})
        elif cmd == "ga4-properties":
            res = ga4_properties()
        elif cmd == "ga4-report":
            pid = ga4_property(pos[0])
            body = {"dateRanges": [{"startDate": pos[1], "endDate": pos[2]}],
                    "dimensions": [{"name": d} for d in opts.get("dims", "sessionSource").split(",")],
                    "metrics": [{"name": m} for m in opts.get("metrics", "sessions").split(",")],
                    "limit": int(opts.get("limit", 100))}
            res = call("https://analyticsdata.googleapis.com/v1beta/properties/%s:runReport" % pid, body)
            res["property_id"] = pid
        elif cmd == "bing-sites":
            res = bing("GetUserSites")
        elif cmd == "bing":
            extra = dict(p.split("=", 1) for p in pos[2:] if "=" in p)
            res = bing(pos[0], pos[1] if len(pos) > 1 else None, **extra)
        else:
            print(__doc__)
            return 2
    except NoAccess as e:
        print(json.dumps({"error": "no_access", "detail": str(e)}))
        return 4
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
