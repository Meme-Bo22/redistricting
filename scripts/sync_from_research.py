#!/usr/bin/env python3
"""Sync the built toys, data and solver package from a SegmentAnyMesh checkout into this repo.

usage: python scripts/sync_from_research.py /path/to/SegmentAnyMesh [--dry-run]

Idempotent: files are only rewritten when their bytes differ; prints added / changed / removed / unchanged counts.
The source checkout is only read. Managed destinations are mirrored (stale files removed):
  site/fair-lines/  index.html (engine inlined, as build_page.py does) + data/*.json
  site/draw/        index.html (draw.html, fetch path to the state data repointed) + layers/, regions/
  site/regions/     index.html (regions.html, if present)
  redistricting/    verbatim package;  tests/test_redistricting.py;  docs/METHOD.md
  site/SYNC.json    source commit hash (+ dirty flag), timestamp-free so reruns are no-ops
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 50 * 1024 * 1024
DRAW_FETCH_OLD = "fetch('../redistricting_toy/data/'"
DRAW_FETCH_NEW = "fetch('../fair-lines/data/'"

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


def mirror(src_dir: Path, dst_dir: Path, pattern: str, dry: bool, transform=None):
    keep = set()
    for f in sorted(src_dir.glob(pattern)):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(src_dir)
        keep.add(rel)
        put(dst_dir / rel, f.read_bytes(), dry)
    if dst_dir.exists():
        for f in sorted(dst_dir.rglob("*")):
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
    put(ROOT / "site/fair-lines/index.html", html.encode(), dry)
    mirror(toy / "data", ROOT / "site/fair-lines/data", "*.json", dry)

    # draw: state data now lives next to the fair-lines page
    dhtml = (draw / "draw.html").read_text()
    assert DRAW_FETCH_OLD in dhtml, "draw.html fetch path changed; update sync script"
    put(ROOT / "site/draw/index.html", dhtml.replace(DRAW_FETCH_OLD, DRAW_FETCH_NEW).encode(), dry)
    for sub in ("layers", "regions"):
        if (draw / sub).is_dir():
            mirror(draw / sub, ROOT / "site/draw" / sub, "*.json", dry)

    # regions (optional)
    if (reg / "regions.html").exists():
        put(ROOT / "site/regions/index.html", (reg / "regions.html").read_bytes(), dry)
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
