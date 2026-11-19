# GPS inference: error vs. time gap

> **Note:** This is an example photo set, used to evaluate the GPS inference
> methods (`nearest` and `interpolate`).

Leave-one-out test on `photos.json` (2026-11-19). Each GPS photo's coordinates
are hidden in turn and inferred from its GPS neighbours in time; the error is
the haversine distance to the true position. "Gap" is the time to the nearest
GPS neighbour.

## Data

| | count |
|---|---:|
| Records in `photos.json` | 2,330 |
| Distinct photos after merging HEIC/JPG/MOV copies | 1,499 |
| GPS photos with a known time zone | 1,441 |
| Evaluated (after dropping 2 exact same-time/same-place repeats) | **1,439** |

56 GPS photos (58 raw records) were skipped because their time zone is unknown;
`--default-tz` would include them.

## Results (`wherewasi evaluate`)

| method | gap | n | median m | p90 m |
|---|---|---:|---:|---:|
| nearest | < 10 min | 1143 | 13 | 178 |
| nearest | 10–60 min | 220 | 206 | 5,647 |
| nearest | 1–6 h | 71 | 668 | 9,701 |
| nearest | > 6 h | 5 | 1,758 | 7,649 |
| interpolate | < 10 min | 1143 | 17 | 240 |
| interpolate | 10–60 min | 220 | 445 | 10,561 |
| interpolate | 1–6 h | 71 | 2,324 | 69,156 |
| interpolate | > 6 h | 5 | 2,686 | 6,375 |

## Finer breakdown

Median m/min = median of (error ÷ gap in minutes).

| gap | n | nearest median / p90 m | nearest m/min | interpolate median / p90 m | interpolate m/min |
|---|---:|---:|---:|---:|---:|
| < 1 min | 521 | 7 / 55 | 26.6 | 8 / 97 | 30.8 |
| 1–5 min | 465 | 27 / 171 | 14.1 | 32 / 253 | 15.4 |
| 5–10 min | 157 | 83 / 417 | 10.5 | 92 / 826 | 13.0 |
| 10–30 min | 157 | 195 / 5,027 | 9.8 | 383 / 5,815 | 23.8 |
| 30–60 min | 63 | 210 / 11,088 | 5.4 | 607 / 23,352 | 15.2 |
| 1–3 h | 52 | 564 / 9,583 | 5.7 | 1,356 / 34,765 | 12.2 |
| 3–6 h | 19 | 3,732 / 9,713 | 13.9 | 5,798 / 291,209 | 24.1 |
| 6–24 h | 4 | 3,982 / 7,809 | 3.6 | 3,837 / 6,453 | 3.8 |
| > 24 h | 1 | 1,758 | 0.4 | 2,686 | 0.6 |

## Takeaways

- **Under 10 min (79 % of photos):** median error is tens of metres and p90 is
  a few hundred, roughly 10–30 m per minute of gap.
- **Beyond 10 min**, the p90 jumps to kilometres: travel between shots makes
  the error unpredictable. Medians grow to hundreds of metres within an hour
  and to kilometres beyond 3 h. Buckets over 6 h have too few photos to draw
  conclusions from.
- **`nearest` beats `interpolate` in every bucket up to 6 h.** That holds even
  when both neighbours are about equally far in time (median 18 m vs. 22 m) and
  is much clearer when they're not (22 m vs. 47 m). Photos tend to be taken in
  clusters at a stop rather than along the path between stops, which would
  favour `nearest`. This suggests changing `infer`'s default method.
- **Caveat:** leave-one-out measures photos *with* GPS. Photos without GPS
  may sit in different situations (indoors, flights), so their real error
  could be higher.
