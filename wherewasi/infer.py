"""Infer missing GPS from neighbouring GPS photos.

Two methods, both using the GPS photos immediately before and after the
target photo in UTC time:

- nearest:     coordinates of the GPS photo closest in time
- interpolate: time-weighted linear interpolation between the two neighbours
               (falls back to nearest when there is only one neighbour)

Each suggestion gets a confidence score in [0, 1] from the time gap to the
nearest GPS photo and the speed implied by the two neighbours.
"""
from __future__ import annotations

import csv
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import IO, List, Optional, Sequence, Tuple

from .loader import Photo, dedupe, sort_key

NEAREST = "nearest"
INTERPOLATE = "interpolate"
METHODS = (NEAREST, INTERPOLATE)

EARTH_RADIUS_M = 6_371_000
# Confidence halves for every hour to the nearest GPS photo.
GAP_HALF_LIFE = timedelta(hours=1)
# Implied speeds up to walking pace don't lower confidence; beyond that it
# drops (~0.34 at 100 km/h, ~0.06 at 800 km/h).
WALKING_KMH = 5.0
SPEED_SCALE_KMH = 50.0
# Speed factor when only one neighbour exists and the speed is unknown.
UNKNOWN_SPEED_FACTOR = 0.5


@dataclass
class Suggestion:
    photo: Photo
    lat: float
    lon: float
    method: str              # method actually used (interpolate may fall back)
    gap: timedelta           # time to the nearest GPS photo
    speed_kmh: Optional[float]  # implied by the two neighbours, if both exist
    confidence: float


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _lerp_lon(lon1: float, lon2: float, f: float) -> float:
    """Interpolate longitude along the short way round (across the antimeridian)."""
    d = (lon2 - lon1 + 180) % 360 - 180
    return (lon1 + f * d + 180) % 360 - 180


def anchors(photos: Sequence[Photo]) -> List[Photo]:
    """GPS photos with a known UTC time, chronological, deduplicated.

    Exact repeats (same instant, same place) are dropped as in `track`.
    """
    selected = sorted(
        (p for p in dedupe(photos) if p.has_gps and p.time_utc is not None),
        key=sort_key,
    )
    out: List[Photo] = []
    for p in selected:
        if out and (p.time_utc, p.lat, p.lon) == (out[-1].time_utc, out[-1].lat, out[-1].lon):
            continue
        out.append(p)
    return out


def confidence(gap: timedelta, speed_kmh: Optional[float]) -> float:
    time_factor = 0.5 ** (gap / GAP_HALF_LIFE)
    if speed_kmh is None:
        speed_factor = UNKNOWN_SPEED_FACTOR
    else:
        speed_factor = 1 / (1 + max(0.0, speed_kmh - WALKING_KMH) / SPEED_SCALE_KMH)
    return time_factor * speed_factor


def estimate(photo: Photo, prev: Optional[Photo], nxt: Optional[Photo],
             method: str) -> Optional[Suggestion]:
    """Estimate `photo`'s position from its GPS neighbours before/after in time."""
    if prev is None and nxt is None:
        return None
    t = photo.time_utc
    gaps = [(abs(t - a.time_utc), a) for a in (prev, nxt) if a is not None]
    gap, nearest = min(gaps, key=lambda g: g[0])

    speed_kmh = None
    if prev is not None and nxt is not None:
        span = (nxt.time_utc - prev.time_utc).total_seconds()
        dist = haversine_m(prev.lat, prev.lon, nxt.lat, nxt.lon)
        speed_kmh = dist / span * 3.6 if span > 0 else (0.0 if dist == 0 else math.inf)

    if method == INTERPOLATE and prev is not None and nxt is not None:
        span = (nxt.time_utc - prev.time_utc).total_seconds()
        f = (t - prev.time_utc).total_seconds() / span if span > 0 else 0.5
        f = min(1.0, max(0.0, f))
        lat = prev.lat + f * (nxt.lat - prev.lat)
        lon = _lerp_lon(prev.lon, nxt.lon, f)
        used = INTERPOLATE
    else:
        lat, lon, used = nearest.lat, nearest.lon, NEAREST

    return Suggestion(photo, lat, lon, used, gap, speed_kmh, confidence(gap, speed_kmh))


def neighbours(anchor_list: Sequence[Photo], times: Sequence, photo: Photo
               ) -> Tuple[Optional[Photo], Optional[Photo]]:
    """GPS photos just before (<) and at-or-after (>=) `photo` in time."""
    i = bisect_left(times, photo.time_utc)
    prev = anchor_list[i - 1] if i > 0 else None
    nxt = anchor_list[i] if i < len(anchor_list) else None
    return prev, nxt


def infer(photos: Sequence[Photo], method: str = INTERPOLATE,
          max_gap: Optional[timedelta] = None) -> Tuple[List[Suggestion], List[Photo]]:
    """Suggest GPS for photos without it.

    Returns (suggestions, skipped): skipped photos lack a UTC time, have no
    GPS photo to infer from, or are further than `max_gap` from one.
    """
    anchor_list = anchors(photos)
    times = [a.time_utc for a in anchor_list]
    targets = sorted(
        (p for p in dedupe(photos) if not p.has_gps),
        key=lambda p: (p.time_utc is None, p.time_utc or 0, p.source_file),
    )
    suggestions: List[Suggestion] = []
    skipped: List[Photo] = []
    for p in targets:
        s = None
        if p.time_utc is not None:
            s = estimate(p, *neighbours(anchor_list, times, p), method)
        if s is None or (max_gap is not None and s.gap > max_gap):
            skipped.append(p)
        else:
            suggestions.append(s)
    return suggestions, skipped


CSV_FIELDS = ["file", "time_utc", "lat", "lon", "method", "gap_min", "speed_kmh", "confidence"]


def write_csv(suggestions: Sequence[Suggestion], f: IO[str]) -> None:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(CSV_FIELDS)
    for s in suggestions:
        w.writerow([
            s.photo.source_file,
            s.photo.time_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            f"{s.lat:.7f}",
            f"{s.lon:.7f}",
            s.method,
            f"{s.gap.total_seconds() / 60:.1f}",
            "" if s.speed_kmh is None else f"{s.speed_kmh:.1f}",
            f"{s.confidence:.2f}",
        ])
