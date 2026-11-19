# WhereWasI

A small personal tool I built to repair the metadata of my own photo library:
mostly missing or wrong GPS and capture times. Fully local, read-only: it never
writes to photo files.

Status (v0):

| Command    | Status          | What it does |
| ---------- | --------------- | ------------ |
| `track`    | implemented     | GPX track of all GPS photos between two chosen photos |
| `infer`    | implemented     | CSV of GPS suggestions for photos without GPS |
| `evaluate` | implemented     | leave-one-out error vs. time gap, per method |

Requires Python 3.9+ and [exiftool](https://exiftool.org/). No other dependencies.

## 1. Export metadata with exiftool

```sh
exiftool -r -n -json -ext heic -ext heif -ext jpg -ext jpeg -ext png -ext dng -ext mov -ext mp4 \
  -SourceFile -GPSLatitude -GPSLongitude -GPSDateTime -DateTimeOriginal -OffsetTimeOriginal \
  -CreateDate -Model ~/Pictures/2026 > photos.json
```

## 2. Build a track between two photos

```sh
python3 -m wherewasi track photos.json IMG_1234.HEIC IMG_2345.HEIC -o trip.gpx
```

Photos can be given as a bare filename or, if the name is ambiguous, with more of
the path (`2026/08/IMG_1234.HEIC`). Order doesn't matter. Each track point carries
the photo filename as its `<name>`, so you can see which photo placed it.

Options:

- `--default-tz +09:00` (or `Asia/Tokyo`): time zone for photos whose zone
  can't be determined. Without it those photos are skipped.
- `--name`: track name.

## 3. Suggest GPS for photos without it

```sh
python3 -m wherewasi infer photos.json -o suggestions.csv
```

Each photo without GPS is placed using the GPS photos just before and after it
in (UTC) time:

- `interpolate` (default): time-weighted linear interpolation between the two
  neighbours. Falls back to `nearest` at the start or end of the library.
- `nearest`: coordinates of the GPS photo closest in time.

The CSV has columns `file, time_utc, lat, lon, method, gap_min, speed_kmh,
confidence`. `gap_min` is the time to the nearest GPS photo, `speed_kmh` the
speed implied by the two neighbours. `confidence` (0-1) halves for every hour of
gap, drops when the implied speed is above walking pace (e.g. x0.34 at
100 km/h), and is halved when there is only one neighbour (speed unknown). The tool only
writes the CSV; nothing is written to the photos.

Options:

- `--method interpolate|nearest`
- `--max-gap 24`: skip photos more than this many hours from any GPS photo
  (`0` = no limit).
- `--default-tz`: as for `track`. Photos with an unknown zone are skipped.

## 4. Check how accurate inference is

```sh
python3 -m wherewasi evaluate photos.json
```

Leave-one-out on your own library: each GPS photo's coordinates are hidden and
inferred from its neighbours with every method. Prints the median and
90th-percentile error in metres per time-gap bucket (< 10 min, 10-60 min,
1-6 h, > 6 h). Use it to decide which method and which `--max-gap` /
`confidence` cutoff to trust.

## How capture times are normalised to UTC

The capture time is `DateTimeOriginal`, falling back to `CreateDate` and then to
a date in the filename (e.g. WhatsApp `IMG-20260801-WA0001.jpg`). The time zone
comes from the first of these that applies:

1. `OffsetTimeOriginal`, or an offset in the date string itself
2. QuickTime `CreateDate` for `.mov`/`.mp4`, which is UTC by spec
3. Offset derived from `GPSDateTime` (rounded to 15 min, because the GPS fix can lag the shutter)
4. `--default-tz`
5. Otherwise the zone is "unknown" and the photo is left out of the track,
   the suggestions and the evaluation

Also: 0/0 coordinates are treated as "no GPS", and copies of the same shot
(`IMG_1234.HEIC` + `IMG_1234.JPG`, Live Photo `.MOV`) are collapsed into one point.

## Tests

```sh
python3 -m unittest discover -v
```
