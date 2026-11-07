#!/usr/bin/env python3
"""Sync the built toys, data and solver package from a SegmentAnyMesh checkout into this repo.

usage: python scripts/sync_from_research.py /path/to/SegmentAnyMesh [--dry-run]

Idempotent: files are only rewritten when their bytes differ; prints added / changed / removed / unchanged counts.
The source checkout is only read. Managed destinations are mirrored (stale files removed):
  site/fair-lines/  index.html (engine inlined, as build_page.py does; data fetches go through the data-base config)
  site/draw/        index.html (draw.html; data fetches go through the data-base config)
  site/regions/     index.html (regions.html, if present; fetches nothing)
  site/data/        shared data, the ONE place the toys read from: <ST>.json, national.json, us.json, us_sizefn.json,
                    layers/<ST>.json (draw constraint layers), regions/<ST>.json (draw region maps)
  redistricting/    verbatim package;  tests/test_redistricting.py;  docs/METHOD.md
  site/SYNC.json    source commit hash (+ dirty flag), timestamp-free so reruns are no-ops
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 50 * 1024 * 1024

# Every page that fetches data resolves it against one base: window.REDISTRICTING_DATA_BASE, else ?data-base=, else ../data/
# (relative to the page, so the whole site/ folder works under any subpath). Inserted right after the first <meta charset>.
ICON = '<link rel="icon" href="data:,">'  # no implicit /favicon.ico request (a root-relative URL that 404s under a subpath)
CONFIG_SNIPPET = (
    ICON + '<script>/* data base: window.REDISTRICTING_DATA_BASE (set before load) or ?data-base=, default ../data/ */'
    'var __RD_DATA_BASE=(function(){var b=window.REDISTRICTING_DATA_BASE;'
    'try{var q=new URLSearchParams(location.search).get("data-base");if(q)b=q}catch(e){}'
    'b=b||"../data/";return /\\/$/.test(b)?b:b+"/"})();</script>'
)
CHARSET = '<meta charset="utf-8">'

FAIR_LINES_FETCHES = [  # (upstream string, replacement); each must occur exactly once
    ('fetch("data/us_sizefn.json")', 'fetch(__RD_DATA_BASE + "us_sizefn.json")'),
    ('fetch(`data/${abbr}.json`)', 'fetch(`${__RD_DATA_BASE}${abbr}.json`)'),
    ('fetch("data/national.json")', 'fetch(__RD_DATA_BASE + "national.json")'),
    ('fetch("data/us.json")', 'fetch(__RD_DATA_BASE + "us.json")'),
]
DRAW_FETCHES = [
    ("fetch('regions/' + ", "fetch(__RD_DATA_BASE + 'regions/' + "),
    ("fetch('../redistricting_toy/data/' + ", "fetch(__RD_DATA_BASE + "),
    ("fetch('layers/' + ", "fetch(__RD_DATA_BASE + 'layers/' + "),
]


def with_icon(html: str) -> str:
    assert CHARSET in html, "no <meta charset>; update sync script"
    return html.replace(CHARSET, CHARSET + ICON, 1)


def with_data_base(html: str, fetches) -> str:
    """Route a page's data fetches through the data-base config. Fails loudly if upstream strings changed (upstream-string guard)."""
    assert html.count(CHARSET) >= 1, "no <meta charset> to anchor the data-base config; update sync script"
    for old, new in fetches:
        assert html.count(old) == 1, f"upstream fetch string changed or duplicated ({old!r} x{html.count(old)}); update sync script"
        html = html.replace(old, new)
    return html.replace(CHARSET, CHARSET + CONFIG_SNIPPET, 1)

stats = {"added": [], "changed": [], "removed": [], "unchanged": 0}


def put(dst: Path, data: bytes, dry: bool):
    if len(data) > MAX_BYTES:
        sys.exit(f"refusing {dst}: {len(data)/2**20:.0f} MB > 50 MB (keep it out of git, see README)")
    rel = dst.relative_to(ROOT)
    if dst.exists():
        if dst.read_bytes() == data:
            stats["unchanged"] += 1
            return
        stats["changed"].append(str(rel))
    else:
        stats["added"].append(str(rel))
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)


def mirror(src_dir: Path, dst_dir: Path, pattern: str, dry: bool, recursive: bool = True):
    keep = set()
    for f in sorted(src_dir.glob(pattern)):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(src_dir)
        keep.add(rel)
        put(dst_dir / rel, f.read_bytes(), dry)
    if dst_dir.exists():
        for f in sorted(dst_dir.rglob("*") if recursive else dst_dir.glob("*")):
            if f.is_file() and f.relative_to(dst_dir) not in keep and "__pycache__" not in f.parts:
                stats["removed"].append(str(f.relative_to(ROOT)))
                if not dry:
                    f.unlink()


def git(src, *args):
    return subprocess.run(["git", "-C", str(src), *args], capture_output=True, text=True).stdout.strip()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if len(args) != 1:
        sys.exit(__doc__)
    src = Path(args[0]).resolve()
    res = src / "research"
    toy, draw, reg = res / "redistricting_toy", res / "redistricting_draw", res / "redistricting_regions"
    for p in (toy / "page.html", toy / "engine" / "engine.js", draw / "draw.html"):
        if not p.exists():
            sys.exit(f"missing {p}")

    # fair-lines: inline engine into page.html (same as build_page.py) so we never depend on a stale index.html
    page = (toy / "page.html").read_text()
    engine = (toy / "engine" / "engine.js").read_text()
    assert "/*ENGINE*/" in page
    html = page.replace("/*ENGINE*/", engine.replace("</script", "<\\/script"))
    put(ROOT / "site/fair-lines/index.html", with_data_base(html, FAIR_LINES_FETCHES).encode(), dry)
    # shared data: one place, site/data/ (top level only here; layers/ and regions/ are mirrored separately below)
    mirror(toy / "data", ROOT / "site/data", "*.json", dry, recursive=False)

    # draw: its constraint layers and region maps live under site/data/ too
    dhtml = (draw / "draw.html").read_text()
    put(ROOT / "site/draw/index.html", with_data_base(dhtml, DRAW_FETCHES).encode(), dry)
    for sub in ("layers", "regions"):
        if (draw / sub).is_dir():
            mirror(draw / sub, ROOT / "site/data" / sub, "*.json", dry)

    # regions (optional)
    if (reg / "regions.html").exists():
        put(ROOT / "site/regions/index.html", with_icon((reg / "regions.html").read_text()).encode(), dry)
    else:
        print("note: regions.html not present, skipping")

    # package, tests, method doc
    mirror(src / "redistricting", ROOT / "redistricting", "*.py", dry)
    if (src / "tests/test_redistricting.py").exists():
        put(ROOT / "tests/test_redistricting.py", (src / "tests/test_redistricting.py").read_bytes(), dry)
    if (src / "docs/REDISTRICTING.md").exists():
        put(ROOT / "docs/METHOD.md", (src / "docs/REDISTRICTING.md").read_bytes(), dry)

    commit = git(src, "rev-parse", "HEAD")
    dirty = bool(git(src, "status", "--porcelain", "--", "redistricting", "research/redistricting_toy",
                     "research/redistricting_draw", "research/redistricting_regions", "tests/test_redistricting.py",
                     "docs/REDISTRICTING.md"))
    meta = {"source_repo": "SegmentAnyMesh", "commit": commit, "source_paths_dirty": dirty}
    put(ROOT / "site/SYNC.json", (json.dumps(meta, indent=2) + "\n").encode(), dry)

    print(("[dry run] " if dry else "") + f"source {commit[:10]}{' (dirty source paths)' if dirty else ''}")
    for k in ("added", "changed", "removed"):
        print(f"{k}: {len(stats[k])}")
        for p in stats[k][:15]:
            print("  ", p)
        if len(stats[k]) > 15:
            print(f"   ... {len(stats[k]) - 15} more")
    print(f"unchanged: {stats['unchanged']}")


if __name__ == "__main__":
    main()
