# photometa

A small personal tool I built to repair the metadata of my own photo library:
mostly missing or wrong GPS and capture times. Fully local, read-only: it never
writes to photo files.

Works on an exiftool JSON export:

```sh
exiftool -r -n -json -ext heic -ext heif -ext jpg -ext jpeg -ext png -ext dng -ext mov -ext mp4 \
  -SourceFile -GPSLatitude -GPSLongitude -GPSDateTime -DateTimeOriginal -OffsetTimeOriginal \
  -CreateDate -Model ~/Pictures/2026 > photos.json
```

Requires Python 3.9+ and [exiftool](https://exiftool.org/). No other dependencies.
