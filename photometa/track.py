"""Build a GPX track from all GPS photos between two chosen photos."""
from __future__ import annotations

from datetime import timezone
from pathlib import PurePath
from typing import List, Sequence
from xml.sax.saxutils import escape, quoteattr

from .loader import Photo, dedupe, sort_key


class TrackError(Exception):
    pass


def find_photo(photos: Sequence[Photo], query: str) -> Photo:
    """Find a photo by full path, trailing path components, or bare filename."""
    q = PurePath(query)
    q_parts = [s.lower() for s in q.parts]
    exact = [p for p in photos if p.source_file == query]
    if exact:
        matches = exact
    else:
        matches = [
            p for p in photos
            if [s.lower() for s in PurePath(p.source_file).parts[-len(q_parts):]] == q_parts
        ]
    if not matches:
        raise TrackError(f"No photo matches {query!r}")
    if len(matches) > 1:
        listing = "\n  ".join(p.source_file for p in matches)
        raise TrackError(f"{query!r} is ambiguous, use more of the path:\n  {listing}")
    photo = matches[0]
    if photo.time_utc is None:
        raise TrackError(
            f"{photo.source_file}: capture time zone unknown "
            f"(time: {photo.local_time}); pass --default-tz"
        )
    return photo


def select_between(photos: Sequence[Photo], start: Photo, end: Photo) -> List[Photo]:
    """All GPS photos with start <= time <= end (UTC), chronological, deduplicated."""
    lo, hi = sorted((start.time_utc, end.time_utc))
    selected = [
        p for p in dedupe(photos)
        if p.has_gps and p.time_utc is not None and lo <= p.time_utc <= hi
    ]
    selected.sort(key=sort_key)
    # Drop exact repeats (same instant, same place), e.g. burst/edited copies.
    out: List[Photo] = []
    for p in selected:
        if out and (p.time_utc, p.lat, p.lon) == (out[-1].time_utc, out[-1].lat, out[-1].lon):
            continue
        out.append(p)
    return out


def to_gpx(points: Sequence[Photo], name: str) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="photometa" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <trk><name>{escape(name)}</name><trkseg>",
    ]
    for p in points:
        t = p.time_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(
            f'    <trkpt lat={quoteattr(f"{p.lat:.7f}")} lon={quoteattr(f"{p.lon:.7f}")}>'
            f"<time>{t}</time><name>{escape(p.name)}</name></trkpt>"
        )
    lines += ["  </trkseg></trk>", "</gpx>", ""]
    return "\n".join(lines)
