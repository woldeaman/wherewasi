# WhereWasI

A small personal tool I built to repair the metadata of my own photo library:
mostly missing or wrong GPS and capture times. Fully local, read-only: it never
writes to photo files.

Status (v0):

| Command    | Status          | What it does |
| ---------- | --------------- | ------------ |
| `track`    | implemented     | GPX track of all GPS photos between two chosen photos |
| `infer`    | not implemented | CSV of GPS suggestions for photos without GPS |
| `evaluate` | not implemented | leave-one-out error vs. time gap, per method |

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

## How capture times are normalised to UTC

The capture time is `DateTimeOriginal`, falling back to `CreateDate` and then to
a date in the filename (e.g. WhatsApp `IMG-20260801-WA0001.jpg`). The time zone
comes from the first of these that applies:

1. `OffsetTimeOriginal`, or an offset in the date string itself
2. QuickTime `CreateDate` for `.mov`/`.mp4`, which is UTC by spec
3. Offset derived from `GPSDateTime` (rounded to 15 min, because the GPS fix can lag the shutter)
4. `--default-tz`
5. Otherwise the zone is "unknown" and the photo is left out of the track

Also: 0/0 coordinates are treated as "no GPS", and copies of the same shot
(`IMG_1234.HEIC` + `IMG_1234.JPG`, Live Photo `.MOV`) are collapsed into one point.

## Tests

```sh
python3 -m unittest discover -v
```
