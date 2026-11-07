#!/usr/bin/env python3
"""Playwright smoke test of site/: python scripts/verify_site.py [--shots]
Serves site/ under the SUBPATH /projects/redistricting/ (any request outside that prefix is a 404, so a leading-slash URL
or a ../ escape in a page fails the test) and a second, CORS-enabled data-only server on another port.
Checks, with zero console errors and zero 4xx/failed requests:
  subpath run: landing links; fair-lines PA solve + national view; draw seeds + Finish, ?state=OH and ?region=PA; regions.
  override run: window.REDISTRICTING_DATA_BASE (init script) and ?data-base= point fair-lines and draw at the second
  server; the data requests really go there and none go to the first server's /data/.
Set PW_CHROMIUM to a chromium executable if Playwright's pinned build is not installed."""
import functools, http.server, os, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PREFIX = "/projects/redistricting/"
# the exact attribute strings embed/README.md recommends
SANDBOX = "allow-scripts allow-same-origin"
IFRAME = '<iframe src="{src}" title="{t}" width="100%" style="aspect-ratio:4/3;min-height:640px;border:0" loading="lazy" sandbox="' + SANDBOX + '" referrerpolicy="no-referrer"></iframe>'
SHOTS = "--shots" in sys.argv
fails = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def serve(directory, prefix="/", cors=False):
    """Static server for `directory`, mounted at URL `prefix`; everything outside the prefix is 404."""
    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass

        def translate_path(self, path):
            if not path.startswith(prefix):
                return str(directory / "__outside_mount__")
            return super().translate_path("/" + path[len(prefix):])

        def end_headers(self):
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def main():
    all_reqs = []
    srv, origin = serve(SITE, PREFIX)
    dsrv, dorigin = serve(SITE / "data", "/", cors=True)  # data-only server for the override run
    base = origin + PREFIX
    with sync_playwright() as p:
        exe = os.environ.get("PW_CHROMIUM")
        args = ["--disable-features=LocalNetworkAccessChecks"]  # lets the cross-origin host test (localhost -> 127.0.0.1) run
        b = p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args)

        def page(path, w=1360, h=1000, scheme=None, init=None):
            pg = b.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
            pg.errs, pg.reqs = [], []
            if init:
                pg.add_init_script(init)
            pg.on("request", lambda r: (pg.reqs.append(r.url), all_reqs.append(r.url)))
            # Google Fonts are external; a blocked font request is not a site error
            pg.on("console", lambda m: pg.errs.append(m.text) if m.type == "error" and "fonts." not in m.text and "ERR_" not in m.text else None)
            pg.on("pageerror", lambda e: pg.errs.append("pageerror: " + str(e)))
            pg.on("requestfailed", lambda r: pg.errs.append("requestfailed: " + r.url) if r.url.startswith((origin, dorigin)) else None)
            pg.on("response", lambda r: pg.errs.append(f"HTTP {r.status}: {r.url}") if r.url.startswith((origin, dorigin)) and r.status >= 400 else None)
            pg.goto(base + path)
            return pg

        # landing
        pg = page("", 1280, 900)
        pg.wait_for_timeout(800)
        check(not pg.errs, f"landing: no console errors {pg.errs}")
        for a in pg.query_selector_all("a.card"):
            href = a.get_attribute("href")
            check((SITE / href / "index.html").exists() or (SITE / href).exists(), f"landing link {href} resolves")
        if SHOTS:
            pg.screenshot(path=str(ROOT / "docs/img/landing.png"), full_page=True)

        # fair-lines: PA solve
        pg = page("fair-lines/#PA")
        pg.wait_for_selector("#btnGen:not([disabled])", timeout=60000)
        pg.wait_for_timeout(1500)
        check(not pg.errs, f"fair-lines: loads clean {pg.errs}")
        pg.click("#btnGen")
        pg.wait_for_function("document.querySelectorAll('#logList li').length > 3 && !document.querySelector('#btnGen').disabled", timeout=180000)
        txt = pg.inner_text("#logList")
        check(not pg.errs, f"fair-lines: no errors during PA solve {pg.errs}")
        check("PA" in pg.inner_text("body") and len(txt) > 50, "fair-lines: PA solve produced a log: " + txt.replace("\n", " | ")[:200])
        if SHOTS:
            pg.screenshot(path=str(ROOT / "docs/img/fair-lines-state.png"))
        # borderless view renders (loads national.json)
        pg2 = page("fair-lines/")
        pg2.wait_for_timeout(3000)
        pg2.click("#natViewMos")
        pg2.wait_for_timeout(6000)
        check(not pg2.errs, f"fair-lines: national view loads national.json clean {pg2.errs}")
        if SHOTS:
            pg2.screenshot(path=str(ROOT / "docs/img/fair-lines-borderless.png"))

        # draw: seed + Finish
        pg = page("draw/")
        pg.wait_for_function("window.__ready === true", timeout=120000)
        spot = """([fx, fy]) => { const P = S.prep; let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
          for (let i=0;i<P.n;i++){x0=Math.min(x0,P.x[i]);x1=Math.max(x1,P.x[i]);y0=Math.min(y0,P.y[i]);y1=Math.max(y1,P.y[i]);}
          const tx=x0+fx*(x1-x0), ty=y0+fy*(y1-y0); let best=-1,bd=1e18;
          for (let i=0;i<P.n;i++){ if (S.labels[i]>=0) continue; const d=(P.x[i]-tx)**2+(P.y[i]-ty)**2; if(d<bd){bd=d;best=i;} }
          const r=document.getElementById('ov').getBoundingClientRect(), V=S.V;
          return {x:r.left+V.ux[best]/V.dpr, y:r.top+V.uy[best]/V.dpr}; }"""
        for fx, fy in [(0.12, 0.45), (0.3, 0.7), (0.3, 0.3)]:
            s = pg.evaluate(spot, [fx, fy])
            pg.mouse.click(s["x"], s["y"])
            pg.keyboard.press("Enter")
        used = pg.evaluate("new Set(Array.from(S.labels).filter(l => l >= 0)).size")
        check(used == 3, f"draw: 3 districts accepted (got {used})")
        pg.click("#finish")
        pg.wait_for_function("S.sol && S.sol.stage === 'done' && !S.running", timeout=180000)
        r = pg.evaluate("({k: S.k, n: new Set(Array.from(S.sol.labels)).size, neg: Array.from(S.sol.labels).filter(l => l < 0).length})")
        check(r["n"] == r["k"] and r["neg"] == 0, f"draw: Finish completes all {r['k']} districts {r}")
        check(not pg.errs, f"draw: no console errors through Finish {pg.errs}")
        # draw ?state= fetch path (data lives under fair-lines/)
        pg3 = page("draw/?state=OH")
        pg3.wait_for_function("window.__ready === true", timeout=120000)
        check(pg3.evaluate("S.prep.n") > 1000 and not pg3.errs, f"draw: ?state=OH fetches ../data/OH.json {pg3.errs}")
        check(any(u.endswith("/data/layers/OH.json") for u in pg3.reqs), "draw: ?state=OH fetched ../data/layers/OH.json")
        pg4 = page("draw/?region=PA")
        pg4.wait_for_function("window.__ready === true", timeout=120000)
        check(any(u.endswith("/data/regions/PA.json") for u in pg4.reqs) and not pg4.errs, f"draw: ?region=PA fetches ../data/regions/PA.json {pg4.errs}")

        # regions
        pg = page("regions/")
        pg.wait_for_timeout(2500)
        check(not pg.errs, f"regions: loads clean {pg.errs}")
        if SHOTS:
            pg.screenshot(path=str(ROOT / "docs/img/regions.png"))

        # every request stayed under the mount point (no leading-slash URL, no escape from site/)
        # (a stray request would have been a 404 above; this makes the failure message explicit)
        check(all(u.startswith(base) or not u.startswith(origin) for u in all_reqs), "all same-origin requests are under " + PREFIX)

        # ---- override: REDISTRICTING_DATA_BASE / ?data-base= -> second server on another port ----
        init = f"window.REDISTRICTING_DATA_BASE = {dorigin + '/'!r};"
        pg = page("fair-lines/#PA", init=init)
        pg.wait_for_selector("#btnGen:not([disabled])", timeout=60000)
        pg.wait_for_timeout(1500)
        check(not pg.errs, f"override fair-lines: loads clean {pg.errs}")
        check(any(u == dorigin + "/PA.json" for u in pg.reqs) and not any("/data/" in u and u.startswith(origin) for u in pg.reqs),
              "override fair-lines: PA.json came from the second server, none from site/data/")
        pg.click("#btnGen")
        pg.wait_for_function("document.querySelectorAll('#logList li').length > 3 && !document.querySelector('#btnGen').disabled", timeout=180000)
        check(not pg.errs, f"override fair-lines: PA solve with remote data {pg.errs}")
        pg = page("draw/?state=OH", init=init)
        pg.wait_for_function("window.__ready === true", timeout=120000)
        check(pg.evaluate("S.prep.n") > 1000 and not pg.errs, f"override draw: ?state=OH via window global {pg.errs}")
        check(any(u == dorigin + "/OH.json" for u in pg.reqs) and any(u == dorigin + "/layers/OH.json" for u in pg.reqs)
              and not any("/data/" in u and u.startswith(origin) for u in pg.reqs), "override draw: OH.json + layers/OH.json from the second server")
        pg = page("draw/?state=OH&data-base=" + dorigin + "/")
        pg.wait_for_function("window.__ready === true", timeout=120000)
        check(any(u == dorigin + "/OH.json" for u in pg.reqs) and not pg.errs, f"override draw: ?data-base= query param {pg.errs}")

        # ---- iframe recipes (embed/README.md): (a) same-origin copy of site/, (b) cross-origin host + data from another origin ----
        port = origin.rsplit(":", 1)[1]
        for label, host, query in (("(a) same-origin", origin, ""), ("(b) cross-origin host + ?data-base=", f"http://localhost:{port}", "?data-base=" + dorigin + "/")):
            url = host + "/host.html"
            pg = b.new_page(viewport={"width": 1100, "height": 900})
            errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "fonts." not in m.text and "ERR_" not in m.text else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("response", lambda r: errs.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 and not r.url.endswith("host.html") else None)
            srcs = [f"{origin}{PREFIX}fair-lines/{query}#PA", f"{origin}{PREFIX}draw/{query}{'&' if query else '?'}state=OH", f"{origin}{PREFIX}regions/"]
            html = "".join(IFRAME.format(src=u, t="toy") for u in srcs)
            pg.route(url, lambda route: route.fulfill(body="<!doctype html><title>host</title>" + html, content_type="text/html"))
            pg.goto(url)
            fl, dr = None, None
            for _ in range(100):
                fl = next((f for f in pg.frames if "/fair-lines/" in f.url), None)
                dr = next((f for f in pg.frames if "/draw/" in f.url), None)
                if fl and dr:
                    break
                pg.wait_for_timeout(100)
            assert fl and dr, [f.url for f in pg.frames]
            fl.wait_for_selector("#btnGen:not([disabled])", timeout=60000)
            dr.wait_for_function("window.__ready === true", timeout=120000)
            fl.click("#btnGen")
            fl.wait_for_function("document.querySelectorAll('#logList li').length > 3 && !document.querySelector('#btnGen').disabled", timeout=180000)
            pg.wait_for_timeout(1500)
            check(not errs and dr.evaluate("S.prep.n") > 1000, f"iframe {label}: all three load, PA solves in sandbox='{SANDBOX}' {errs}")
            pg.close()

        b.close()
    srv.shutdown()
    dsrv.shutdown()
    print("FAILED" if fails else "ALL OK")
    sys.exit(1 if fails else 0)


main()
