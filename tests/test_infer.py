import csv
import json
import os
import tempfile
import unittest
from datetime import timedelta

from wherewasi.cli import main
from wherewasi.evaluate import bucket, leave_one_out, percentile, summarise
from wherewasi.infer import (INTERPOLATE, NEAREST, anchors, confidence, estimate,
                             haversine_m, infer)
from wherewasi.loader import normalise


def rec(name, time, lat=None, lon=None, offset="+00:00"):
    r = {"SourceFile": f"trip/{name}", "DateTimeOriginal": f"2026:08:01 {time}",
         "OffsetTimeOriginal": offset}
    if lat is not None:
        r.update(GPSLatitude=lat, GPSLongitude=lon)
    return r


RECORDS = [
    rec("A.HEIC", "10:00:00", 50.0, 8.0),
    rec("B.HEIC", "10:30:00"),               # midway between A and C
    rec("C.HEIC", "11:00:00", 50.0, 8.1),
    rec("C.JPG", "11:00:00"),                # copy of C without GPS: not a target
    rec("D.HEIC", "11:05:00"),               # after the last GPS photo
    rec("E.HEIC", "23:00:00"),               # 12 h after the last GPS photo
    {"SourceFile": "trip/F.HEIC", "DateTimeOriginal": "2026:08:01 12:00:00"},  # zone unknown
]


class InferTest(unittest.TestCase):
    def setUp(self):
        self.photos = [normalise(r) for r in RECORDS]
        self.by_name = {p.name: p for p in self.photos}

    def test_haversine(self):
        # 0.1 deg of longitude at 50 N is ~7.15 km
        self.assertAlmostEqual(haversine_m(50, 8, 50, 8.1), 7150, delta=10)
        self.assertEqual(haversine_m(1, 2, 1, 2), 0)

    def test_interpolate_midpoint(self):
        s, = [s for s in infer(self.photos)[0] if s.photo.name == "B.HEIC"]
        self.assertEqual(s.method, INTERPOLATE)
        self.assertAlmostEqual(s.lat, 50.0)
        self.assertAlmostEqual(s.lon, 8.05)
        self.assertEqual(s.gap, timedelta(minutes=30))
        self.assertAlmostEqual(s.speed_kmh, 7.15, delta=0.01)

    def test_nearest(self):
        s, = [s for s in infer(self.photos, NEAREST)[0] if s.photo.name == "B.HEIC"]
        self.assertEqual((s.lat, s.lon, s.method), (50.0, 8.0, NEAREST))

    def test_interpolate_falls_back_to_nearest_at_end(self):
        s, = [s for s in infer(self.photos)[0] if s.photo.name == "D.HEIC"]
        self.assertEqual((s.lat, s.lon, s.method), (50.0, 8.1, NEAREST))
        self.assertIsNone(s.speed_kmh)

    def test_skipped(self):
        suggestions, skipped = infer(self.photos, max_gap=timedelta(hours=6))
        self.assertEqual(sorted(s.photo.name for s in suggestions), ["B.HEIC", "D.HEIC"])
        self.assertEqual(sorted(p.name for p in skipped), ["E.HEIC", "F.HEIC"])
        # No limit: E gets a suggestion; the copy C.JPG is never a target.
        names = [s.photo.name for s in infer(self.photos)[0]]
        self.assertIn("E.HEIC", names)
        self.assertNotIn("C.JPG", names)

    def test_antimeridian(self):
        a = normalise(rec("a.jpg", "10:00:00", 0.0, 179.9))
        b = normalise(rec("b.jpg", "10:30:00"))
        c = normalise(rec("c.jpg", "11:00:00", 0.0, -179.9))
        s = estimate(b, a, c, INTERPOLATE)
        self.assertAlmostEqual(abs(s.lon), 180.0)

    def test_confidence(self):
        self.assertAlmostEqual(confidence(timedelta(0), 3.0), 1.0)
        self.assertAlmostEqual(confidence(timedelta(hours=1), 3.0), 0.5)
        self.assertLess(confidence(timedelta(0), 800), confidence(timedelta(0), 100))
        self.assertAlmostEqual(confidence(timedelta(0), None), 0.5)

    def test_anchors_drop_repeats(self):
        dup = self.photos + [normalise({**RECORDS[0], "SourceFile": "other/A2.HEIC"})]
        self.assertEqual(len(anchors(dup)), 2)  # A and its repeat A2 collapse


class EvaluateTest(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(bucket(timedelta(minutes=5)), "< 10 min")
        self.assertEqual(bucket(timedelta(minutes=10)), "10-60 min")
        self.assertEqual(bucket(timedelta(hours=2)), "1-6 h")
        self.assertEqual(bucket(timedelta(days=2)), "> 6 h")

    def test_percentile(self):
        self.assertEqual(percentile([3, 1, 2], 50), 2)
        self.assertAlmostEqual(percentile(list(range(11)), 90), 9)
        self.assertEqual(percentile([7], 90), 7)

    def test_leave_one_out_straight_line(self):
        # Constant speed along a line: interpolation is exact, nearest is not.
        photos = [normalise(rec(f"{i}.jpg", f"10:0{i}:00", 50.0, 8.0 + 0.01 * i))
                  for i in range(5)]
        results = leave_one_out(photos)
        interp = [r.error_m for r in results if r.method == INTERPOLATE]
        nearest = [r.error_m for r in results if r.method == NEAREST]
        self.assertEqual(len(interp), 5)
        self.assertLess(max(interp[1:-1]), 1)    # inner points exact
        self.assertGreater(min(nearest), 700)    # 0.01 deg ~ 715 m
        rows = summarise(results)
        self.assertEqual([(m, b, n) for m, b, n, _, _ in rows],
                         [(NEAREST, "< 10 min", 5), (INTERPOLATE, "< 10 min", 5)])


class CliTest(unittest.TestCase):
    def test_infer_and_evaluate_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "photos.json"), os.path.join(d, "s.csv")
            with open(src, "w", encoding="utf-8") as f:
                json.dump(RECORDS, f)
            self.assertEqual(main(["infer", src, "-o", out, "--max-gap", "6"]), 0)
            with open(out, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([r["file"] for r in rows], ["trip/B.HEIC", "trip/D.HEIC"])
            self.assertEqual(rows[0]["lon"], "8.0500000")
            self.assertEqual(rows[0]["time_utc"], "2026-08-01T10:30:00Z")
            self.assertEqual(main(["evaluate", src]), 0)

    def test_evaluate_needs_two_gps_photos(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "photos.json")
            with open(src, "w", encoding="utf-8") as f:
                json.dump(RECORDS[:1], f)
            self.assertEqual(main(["evaluate", src]), 1)


if __name__ == "__main__":
    unittest.main()
