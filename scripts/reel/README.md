# Lines on the Land: the map reel

This folder builds the "Lines on the Land" page: every state with more than one district, drawn over grey terrain, with buttons to switch between the official map, the Fair Lines solver, the social-ties maps and a typical neutral map from each scheme. Under each state is a histogram of how the neutral maps split the seats, so you can see where the official map lands. Every map comes from the stored, audited files (one piece per district, within 1%; see `docs/MAP_AUDIT.md`).

Run, from the repo root:

```
PYTHONPATH=. WORKERS=2 python scripts/reel/posters.py ~/.cache/redistricting/reel/out CO PA ...
python scripts/reel/build.py
```

The pictures and the page land in `~/.cache/redistricting/reel/` (set `REEL_DIR` to move it), not in git.

## For AI agents

- `posters.py OUTDIR ST...`: per state, `terrain.png` (USGS 3DEP hillshade via `geo_layers.DEM`, rivers/lakes from `geo/<ST>.shapes.json`, clipped to the outline) plus one transparent overlay PNG per plan (district fill by 2020 presidential lean, white borders) and `info.json` (`plans[key] = {label, file, seats_d}`, `hist[key] = {h, settled, n}`, `neutral_median_d` from recom20, `vote_d`). Plans are read, never re-run: official/solver from `plans/{st}.*.census.json`, ReCom/geo schemes from the `typical` map in `ensembles/maps/{st}.*.census.json`, social ties from `sci/districts/{st}.adjusted.compact|zcta.census.json`. `settled` comes from the ensemble index `passed` flag (sets whose two chains disagreed show "not settled"). States with `info.json` already present are skipped (resumable). `WORKERS` sets the process pool (default 2); processes run at below-normal priority.
- `build.py`: reads `$REEL_DIR/out`, writes `$REEL_DIR/site/reel.html` and `site/m/<ST>/{terrain.jpg,*.webp}` and `$REEL_DIR/files.json` (published-path -> local-path map for an Artifact publish). `GROUPS` are four regions covering all 44 multi-district states; `ORDER` sets the buttons. `geo:huc` (watersheds) is left out of `ORDER` only because an Artifact version holds at most 511 files; add it back for a self-hosted page.
- `template.html`: the page; `build.py` fills `<!--PLATES-->`, `/*DATA*/`, `/*SHORT*/`. The histogram is drawn client-side (`hist(st, plan)`, SVG): the shown plan's bar is white, markers O/F/T/Z mark official, Fair Lines and the two social-ties maps.
- Published copy (2026-11-25): https://claude.ai/artifact/Xi2DLnnxhsmBKj5jh5Y78j (private to the owner until shared).
