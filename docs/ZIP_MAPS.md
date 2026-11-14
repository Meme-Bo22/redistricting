# The maps remade with ZIP-code areas

## In short (for people)

Every earlier district map that used counties now has a ZIP-code version: neutral maps that keep ZIP-code areas whole instead of counties (10,000+ per state, two agreeing chains), and social-ties maps built from friendships between ZIP-code areas, with and without a shape limit. The 50-state maps stay at county level (a ZIP-to-ZIP table for the whole country would have about a billion pairs, and states are large enough that county ties describe them).

- Keeping ZIP areas whole instead of counties barely moves the neutral result: 229 Democratic seats (2020 votes, 44 states, sum of medians) against 230. The median differs by one seat in 7 states (AL, CA, FL, GA, MD, TX, WI).
- It does change the maps: they split far more counties (they no longer try to keep them) and few ZIP areas.
- Social-ties maps by ZIP: 234 Democratic seats compact, 231 with no shape limit; official maps 221.
- Pictures: `docs/samples/<ST>.techniques.zip.png` for GA, OH, FL, MI, AZ, IL, NC, PA, TX and WI.

| State | Seats | Official | Neutral, counties whole | Neutral, ZIP areas whole | Social ties by ZIP, compact | No shape limit | County splits (county / ZIP neutral) | ZIP splits (ZIP neutral) |
| --- | --: | --: | --: | --: | --: | --: | --- | --: |
| AL | 7 | 1 | 1 | 0 | 1 | 0 | 8 / 30 | 11 |
| AR | 4 | 0 | 0 | 0 | 1 | 1 | 4 / 20 | 5 |
| AZ | 9 | 5 | 4 | 4 | 5 | 5 | 5 / 9 | 14 |
| CA | 52 | 48 | 45 | 46 | 45 | 45 | 27 / 41 | 96 |
| CO | 8 | 5 | 5 | 5 | 5 | 5 | 9 / 20 | 14 |
| CT | 5 | 5 | 5 | 5 | 5 | 5 | 4 / 6 | 6 |
| FL | 28 | 8 | 13 | 12 | 14 | 14 | 23 / 35 | 42 |
| GA | 14 | 5 | 6 | 5 | 5 | 5 | 17 / 53 | 29 |
| HI | 2 | 2 | 2 | 2 | 2 | 2 | 1 / 1 | 1 |
| IA | 4 | 0 | 1 | 1 | 0 | 2 | 4 / 26 | 4 |
| ID | 2 | 0 | 0 | 0 | 0 | 0 | 1 / 5 | 1 |
| IL | 17 | 14 | 11 | 11 | 11 | 11 | 13 / 42 | 34 |
| IN | 9 | 2 | 2 | 2 | 2 | 2 | 11 / 40 | 15 |
| KS | 4 | 1 | 1 | 1 | 1 | 1 | 4 / 20 | 4 |
| KY | 6 | 1 | 1 | 1 | 1 | 1 | 6 / 25 | 8 |
| LA | 6 | 1 | 1 | 1 | 1 | 1 | 6 / 24 | 8 |
| MA | 9 | 9 | 9 | 9 | 9 | 9 | 7 / 10 | 13 |
| MD | 8 | 7 | 7 | 6 | 7 | 7 | 6 / 9 | 13 |
| ME | 2 | 1 | 1 | 1 | 1 | 2 | 1 / 5 | 1 |
| MI | 13 | 7 | 6 | 6 | 7 | 8 | 13 / 34 | 25 |
| MN | 8 | 4 | 4 | 4 | 3 | 4 | 8 / 30 | 12 |
| MO | 8 | 2 | 2 | 2 | 2 | 2 | 8 / 37 | 11 |
| MS | 4 | 1 | 1 | 1 | 0 | 1 | 3 / 21 | 5 |
| MT | 2 | 0 | 0 | 0 | 0 | 0 | 1 / 6 | 1 |
| NC | 14 | 3 | 6 | 6 | 6 | 5 | 17 / 47 | 32 |
| NE | 3 | 1 | 1 | 1 | 1 | 1 | 2 / 12 | 2 |
| NH | 2 | 2 | 2 | 2 | 2 | 2 | 1 / 4 | 1 |
| NJ | 12 | 10 | 9 | 9 | 9 | 9 | 11 / 17 | 20 |
| NM | 3 | 3 | 2 | 2 | 3 | 2 | 2 / 9 | 2 |
| NV | 4 | 2 | 2 | 2 | 2 | 3 | 2 / 4 | 4 |
| NY | 26 | 20 | 20 | 20 | 20 | 19 | 18 / 41 | 45 |
| OH | 15 | 3 | 5 | 5 | 4 | 3 | 19 / 54 | 30 |
| OK | 5 | 0 | 0 | 0 | 0 | 0 | 5 / 26 | 7 |
| OR | 6 | 5 | 5 | 5 | 5 | 3 | 6 / 14 | 7 |
| PA | 17 | 9 | 8 | 8 | 8 | 8 | 19 / 45 | 37 |
| RI | 2 | 2 | 2 | 2 | 2 | 2 | 1 / 2 | 1 |
| SC | 7 | 1 | 2 | 2 | 2 | 2 | 9 / 24 | 10 |
| TN | 9 | 0 | 2 | 2 | 2 | 2 | 10 / 38 | 16 |
| TX | 38 | 14 | 18 | 19 | 21 | 19 | 36 / 87 | 72 |
| UT | 4 | 1 | 1 | 1 | 1 | 1 | 3 / 7 | 4 |
| VA | 11 | 7 | 8 | 8 | 8 | 7 | 12 / 39 | 19 |
| WA | 10 | 7 | 7 | 7 | 7 | 7 | 9 / 16 | 14 |
| WI | 8 | 2 | 2 | 3 | 3 | 3 | 9 / 33 | 13 |
| WV | 2 | 0 | 0 | 0 | 0 | 0 | 1 / 7 | 1 |

Democratic seats with 2020 votes; neutral columns are medians; splits are medians.

---

## For AI agents (detailed)

- Neutral: `python -m redistricting_addons.batch --variants zip20` -> `site/data/ensembles/<ST>.zip20.json` (ReCom with edges inside one ZCTA weighted 20, `Graph.zcta`; plans also record `zip_splits`). Same moves, burn-in, thinning and two-chain check as the county version; the panel offers it as "ZIP areas kept whole" (site neighbour graph only).
- Social ties by ZIP: `python -m redistricting_addons.sci_zcta` (compact, `<ST>.zcta.json`) and `--skip-read --free` (no shape limit, `<ST>.zcta.free.json`).
- Pictures: `python -m redistricting_addons.samples --states --fifty "" --techniques-zip GA OH ...`.

