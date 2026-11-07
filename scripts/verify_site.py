#!/usr/bin/env python3
"""Playwright smoke test of site/: python scripts/verify_site.py [--shots]  (serves site/ itself on a free port).
Checks: every page loads with zero console errors; fair-lines runs a PA solve; draw can seed districts and Finish.
Set PW_CHROMIUM to a chromium executable if Playwright's pinned build is not installed."""
import functools, http.server, os, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SHOTS = "--shots" in sys.argv
fails = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    h = functools.partial(Quiet, directory=str(SITE))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def main():
    srv, base = serve()
    with sync_playwright() as p:
        exe = os.environ.get("PW_CHROMIUM")
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()

        def page(path, w=1360, h=1000, scheme=None):
            pg = b.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
            pg.errs = []
            # Google Fonts are external; a blocked font request is not a site error
            pg.on("console", lambda m: pg.errs.append(m.text) if m.type == "error" and "fonts." not in m.text and "ERR_" not in m.text else None)
            pg.on("pageerror", lambda e: pg.errs.append("pageerror: " + str(e)))
            pg.on("requestfailed", lambda r: pg.errs.append("requestfailed: " + r.url) if r.url.startswith(base) else None)
            pg.on("response", lambda r: pg.errs.append(f"HTTP {r.status}: {r.url}") if r.url.startswith(base) and r.status >= 400 else None)
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
        pg.wait_for_function("S.sol && S.sol.labels", timeout=180000)
        r = pg.evaluate("({k: S.k, n: new Set(Array.from(S.sol.labels)).size, neg: Array.from(S.sol.labels).filter(l => l < 0).length})")
        check(r["n"] == r["k"] and r["neg"] == 0, f"draw: Finish completes all {r['k']} districts {r}")
        check(not pg.errs, f"draw: no console errors through Finish {pg.errs}")
        # draw ?state= fetch path (data lives under fair-lines/)
        pg3 = page("draw/?state=OH")
        pg3.wait_for_function("window.__ready === true", timeout=120000)
        check(pg3.evaluate("S.prep.n") > 1000 and not pg3.errs, f"draw: ?state=OH fetches ../fair-lines/data/OH.json {pg3.errs}")

        # regions
        pg = page("regions/")
        pg.wait_for_timeout(2500)
        check(not pg.errs, f"regions: loads clean {pg.errs}")
        if SHOTS:
            pg.screenshot(path=str(ROOT / "docs/img/regions.png"))
        b.close()
    srv.shutdown()
    print("FAILED" if fails else "ALL OK")
    sys.exit(1 if fails else 0)


main()
