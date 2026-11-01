import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from photometa.cli import main
from photometa.loader import TZ_GPS, TZ_OFFSET, TZ_UNKNOWN, TZ_UTC, dedupe, normalise
from photometa.track import TrackError, find_photo, select_between, to_gpx

RECORDS = [
    # Okinawa, offset tag present
    {"SourceFile": "trip/IMG_0001.HEIC", "DateTimeOriginal": "2026:08:01 10:00:00",
     "OffsetTimeOriginal": "+09:00", "GPSLatitude": 26.2, "GPSLongitude": 127.7},
    # HEIC+JPG duplicate of the same shot
    {"SourceFile": "trip/IMG_0001.JPG", "DateTimeOriginal": "2026:08:01 10:00:00",
     "OffsetTimeOriginal": "+09:00", "GPSLatitude": 26.2, "GPSLongitude": 127.7},
    # No offset tag, zone derived from GPSDateTime (fix 20 s stale)
    {"SourceFile": "trip/IMG_0002.JPG", "DateTimeOriginal": "2026:08:01 12:00:00",
     "GPSDateTime": "2026:08:01 02:59:40Z", "GPSLatitude": 26.3, "GPSLongitude": 127.8},
    # 0/0 coordinates = no fix
    {"SourceFile": "trip/IMG_0003.JPG", "DateTimeOriginal": "2026:08:01 13:00:00",
     "OffsetTimeOriginal": "+09:00", "GPSLatitude": 0, "GPSLongitude": 0},
    # Video, QuickTime CreateDate is UTC
    {"SourceFile": "trip/IMG_0004.MOV", "CreateDate": "2026:08:01 05:00:00",
     "GPSLatitude": 26.4, "GPSLongitude": 127.9},
    # Unknown zone
    {"SourceFile": "trip/IMG_0005.JPG", "DateTimeOriginal": "2026:08:01 15:00:00",
     "GPSLatitude": 26.5, "GPSLongitude": 128.0},
    # WhatsApp image, date only from filename, no GPS
    {"SourceFile": "chat/IMG-20260801-WA0001.jpg"},
    # Later photo, end point
    {"SourceFile": "trip/IMG_0006.HEIC", "DateTimeOriginal": "2026:08:01 18:00:00",
     "OffsetTimeOriginal": "+09:00", "GPSLatitude": 26.6, "GPSLongitude": 128.1},
    # After the end point
    {"SourceFile": "trip/IMG_0007.HEIC", "DateTimeOriginal": "2026:08:02 09:00:00",
     "OffsetTimeOriginal": "+09:00", "GPSLatitude": 26.7, "GPSLongitude": 128.2},
]


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.photos = {p.name: p for p in map(normalise, RECORDS)}

    def test_offset_tag(self):
        p = self.photos["IMG_0001.HEIC"]
        self.assertEqual(p.time_utc, utc(2026, 8, 1, 1))
        self.assertEqual(p.tz_source, TZ_OFFSET)

    def test_offset_from_gps_time(self):
        p = self.photos["IMG_0002.JPG"]
        self.assertEqual(p.time_utc, utc(2026, 8, 1, 3))
        self.assertEqual(p.tz_source, TZ_GPS)

    def test_zero_coordinates_dropped(self):
        self.assertFalse(self.photos["IMG_0003.JPG"].has_gps)

    def test_video_create_date_is_utc(self):
        p = self.photos["IMG_0004.MOV"]
        self.assertEqual(p.time_utc, utc(2026, 8, 1, 5))
        self.assertEqual(p.tz_source, TZ_UTC)

    def test_unknown_zone(self):
        p = self.photos["IMG_0005.JPG"]
        self.assertIsNone(p.time_utc)
        self.assertEqual(p.tz_source, TZ_UNKNOWN)

    def test_default_tz(self):
        p = normalise(RECORDS[5], default_tz=timezone.utc)
        self.assertEqual(p.time_utc, utc(2026, 8, 1, 15))

    def test_filename_date(self):
        p = self.photos["IMG-20260801-WA0001.jpg"]
        self.assertEqual(p.local_time, datetime(2026, 8, 1))
        self.assertEqual(p.time_source, "filename")

    def test_inline_offset(self):
        p = normalise({"SourceFile": "a.mov", "DateTimeOriginal": "2026:08:01 10:00:00+09:00"})
        self.assertEqual(p.time_utc, utc(2026, 8, 1, 1))

    def test_dedupe_prefers_heic(self):
        names = {p.name for p in dedupe(self.photos.values())}
        self.assertIn("IMG_0001.HEIC", names)
        self.assertNotIn("IMG_0001.JPG", names)


class TrackTest(unittest.TestCase):
    def setUp(self):
        self.photos = [normalise(r) for r in RECORDS]

    def test_select_between(self):
        start = find_photo(self.photos, "IMG_0001.JPG")
        end = find_photo(self.photos, "trip/IMG_0006.HEIC")
        names = [p.name for p in select_between(self.photos, start, end)]
        self.assertEqual(names, ["IMG_0001.HEIC", "IMG_0002.JPG", "IMG_0004.MOV", "IMG_0006.HEIC"])

    def test_reversed_endpoints(self):
        a = find_photo(self.photos, "IMG_0001.HEIC")
        b = find_photo(self.photos, "IMG_0006.HEIC")
        self.assertEqual(select_between(self.photos, a, b), select_between(self.photos, b, a))

    def test_find_photo_errors(self):
        with self.assertRaises(TrackError):
            find_photo(self.photos, "nope.jpg")
        with self.assertRaises(TrackError):
            find_photo(self.photos, "IMG_0005.JPG")  # unknown zone
        dup = self.photos + [normalise({**RECORDS[0], "SourceFile": "other/IMG_0001.HEIC"})]
        with self.assertRaises(TrackError):
            find_photo(dup, "IMG_0001.HEIC")

    def test_gpx_utc_and_escaping(self):
        start = find_photo(self.photos, "IMG_0001.HEIC")
        gpx = to_gpx(select_between(self.photos, start, start), "A & B <x>")
        self.assertIn("<time>2026-08-01T01:00:00Z</time>", gpx)
        self.assertIn("<name>A &amp; B &lt;x&gt;</name>", gpx)


class CliTest(unittest.TestCase):
    def test_track_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "photos.json"), os.path.join(d, "t.gpx")
            with open(src, "w", encoding="utf-8") as f:
                json.dump(RECORDS, f)
            rc = main(["track", src, "IMG_0001.HEIC", "IMG_0006.HEIC", "-o", out,
                       "--default-tz", "+09:00"])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as f:
                gpx = f.read()
            self.assertEqual(gpx.count("<trkpt"), 5)  # IMG_0005 now included via default tz

    def test_placeholders(self):
        self.assertEqual(main(["infer", "x.json"]), 2)
        self.assertEqual(main(["evaluate", "x.json"]), 2)


if __name__ == "__main__":
    unittest.main()
