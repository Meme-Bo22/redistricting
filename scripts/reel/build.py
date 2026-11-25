"""Build the comparison reel: $REEL_DIR/out/<ST>/{terrain.png, <plan>.png, info.json} -> site/m/<ST>/*.{jpg,webp} + site/reel.html."""
import html
import json
import os
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent  # template.html lives here
WORK = Path(os.environ.get("REEL_DIR", Path.home() / ".cache" / "redistricting" / "reel"))  # outputs stay out of git
SRC, SITE = WORK / "out", WORK / "site"

GROUPS = [
    ("The West", "Mountains, deserts and the Pacific coast, where ranges decide where people live.",
     ["WA", "OR", "CA", "NV", "ID", "MT", "UT", "AZ", "CO", "NM", "HI"]),
    ("Plains and the Midwest", "Gentler ground, where big rivers and lakes are most of the natural lines there are.",
     ["TX", "OK", "KS", "NE", "MN", "IA", "MO", "WI", "IL", "IN", "MI", "OH"]),
    ("The South", "River deltas, the Gulf coast and the southern Appalachians.",
     ["AR", "LA", "MS", "AL", "TN", "KY", "GA", "FL", "SC", "NC", "WV", "VA"]),
    ("The Northeast", "Old folded ridges, river valleys and dense coastal cities.",
     ["PA", "NY", "NJ", "MD", "CT", "RI", "MA", "NH", "ME"]),
]
ORDER = ["official", "solver", "recom1", "recom20", "zip20", "geo:town", "geo:school", "geo:nature",
         "sci.adjusted.compact", "sci.zcta"]
SHORT = {"official": "Official", "solver": "Fair Lines", "recom1": "ReCom", "recom20": "Counties", "zip20": "ZIP areas",
         "sci.adjusted.compact": "Ties (county)", "sci.zcta": "Ties (ZIP)", "geo:nature": "Rivers & ridges",
         "geo:town": "Towns", "geo:school": "Schools", "geo:huc": "Watersheds"}
seen = {st for _, _, sts in GROUPS for st in sts}
extra = sorted(p.name for p in SRC.iterdir() if (p / "info.json").exists() and p.name not in seen)
if extra:
    GROUPS.append(("Elsewhere", "", extra))

files = {}
data = {}
sections = []
for title, blurb, sts in GROUPS:
    plates = []
    for st in sts:
        ip = SRC / st / "info.json"
        if not ip.exists():
            continue
        info = json.loads(ip.read_text(encoding="utf-8"))
        dst = SITE / "m" / st
        dst.mkdir(parents=True, exist_ok=True)
        im = Image.open(SRC / st / "terrain.png").convert("RGB")
        scale = min(1.0, 1400 / max(im.size))
        size = (round(im.size[0] * scale), round(im.size[1] * scale))
        im.resize(size, Image.LANCZOS).save(dst / "terrain.jpg", quality=82, optimize=True, progressive=True)
        files[f"m/{st}/terrain.jpg"] = str(dst / "terrain.jpg")
        plans = {}
        for key in ORDER:
            p = info["plans"].get(key)
            if not p:
                continue
            o = Image.open(SRC / st / p["file"]).convert("RGBA").resize(size, Image.LANCZOS)
            name = p["file"].replace(".png", ".webp")
            o.save(dst / name, quality=80, alpha_quality=85, method=6)
            files[f"m/{st}/{name}"] = str(dst / name)
            plans[key] = {"f": f"m/{st}/{name}", "d": p["seats_d"]}
        data[st] = {"name": info["name"], "k": info["k"], "med": info["neutral_median_d"], "vote": info["vote_d"],
                    "plans": plans, "hist": info.get("hist", {})}
        chips = "".join(
            f'<button type="button" class="chip" data-st="{st}" data-plan="{k}" aria-pressed="false">'
            f'<span class="chip-name">{SHORT[k]}</span><span class="chip-seats">{v["d"]}</span></button>'
            for k, v in plans.items())
        wide = " wide" if size[0] / size[1] > 1.3 else ""
        plates.append(f"""
      <figure class="plate{wide}" id="{st}" style="--ar:{size[0]}/{size[1]}">
        <div class="stack">
          <img class="terrain" src="m/{st}/terrain.jpg" width="{size[0]}" height="{size[1]}" alt="" loading="lazy">
          <img class="overlay" data-st="{st}" src="{plans.get('official', next(iter(plans.values())))['f']}" width="{size[0]}" height="{size[1]}" alt="{html.escape(info['name'])} districts" loading="lazy">
          <span class="plan-tag" data-tag="{st}">Official map</span>
        </div>
        <figcaption>
          <div class="cap-head"><span class="abbr">{st}</span><h3>{html.escape(info['name'])}</h3>
            <span class="facts">{info['k']} districts · {info['vote_d']}% Democratic vote · neutral median {info['neutral_median_d']} D</span></div>
          <div class="hist" data-hist="{st}"></div>
          <div class="chips" role="group" aria-label="Map for {html.escape(info['name'])}; numbers are Democratic seats">{chips}</div>
        </figcaption>
      </figure>""")
    if plates:
        sections.append(f"""
    <section class="group">
      <header class="group-head"><h2>{title}</h2><p>{blurb}</p></header>
      <div class="plates">{''.join(plates)}
      </div>
    </section>""")

page = (HERE / "template.html").read_text(encoding="utf-8")
page = page.replace("<!--PLATES-->", "".join(sections)).replace("/*DATA*/", json.dumps(data, separators=(",", ":")))
page = page.replace("/*SHORT*/", json.dumps(SHORT))
(SITE / "reel.html").write_text(page, encoding="utf-8")
(WORK / "files.json").write_text(json.dumps(files, indent=0), encoding="utf-8")
print("states", len(data), "files", len(files), "MB", round(sum(Path(f).stat().st_size for f in files.values()) / 1e6, 1))
