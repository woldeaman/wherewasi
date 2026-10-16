"""Shared loader: read exiftool JSON and normalise capture times to UTC.

Expected input is produced by:

    exiftool -r -n -json -ext heic -ext heif -ext jpg -ext jpeg -ext png -ext dng \
      -ext mov -ext mp4 -SourceFile -GPSLatitude -GPSLongitude -GPSDateTime \
      -DateTimeOriginal -OffsetTimeOriginal -CreateDate -Model <folder> > photos.json
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import PurePath
from typing import Iterable, List, Optional, Tuple

VIDEO_EXTS = {".mov", ".mp4"}
# When the same shot exists in several formats, keep the first in this order.
EXT_PREFERENCE = [".heic", ".heif", ".dng", ".jpg", ".jpeg", ".png", ".mov", ".mp4"]

# Where the UTC time came from.
TZ_OFFSET = "offset"          # DateTimeOriginal + OffsetTimeOriginal (or inline offset)
TZ_GPS = "gps"                # offset derived from GPSDateTime
TZ_UTC = "utc"                # value is UTC by definition (QuickTime CreateDate)
TZ_DEFAULT = "default"        # user-supplied fallback time zone
TZ_UNKNOWN = "unknown"        # local time only, zone unknown

_DT_RE = re.compile(
    r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.\d+)?"
    r"(Z|[+\-]\d{2}:?\d{2})?"
)
_OFFSET_RE = re.compile(r"^([+\-])(\d{2}):?(\d{2})$")
# Dates embedded in filenames: IMG-20260801-WA0001.jpg, 20260801_123456.jpg,
# PXL_20260801_123456789.jpg, Screenshot 2026-08-01 at 12.34.56.png, ...
_FILENAME_DT_RE = re.compile(
    r"(?<!\d)(20\d{2}|19\d{2})-?(\d{2})-?(\d{2})"
    r"(?:[_\-\sT]+(?:at\s)?(\d{2})[.\-:]?(\d{2})[.\-:]?(\d{2}))?"
)


@dataclass
class Photo:
    source_file: str
    model: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    local_time: Optional[datetime]   # naive wall-clock time as shown on the device
    time_utc: Optional[datetime]     # aware, UTC; None if the zone is unknown
    tz_source: str                   # one of the TZ_* constants
    time_source: Optional[str]       # tag the time was read from

    @property
    def has_gps(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def name(self) -> str:
        return PurePath(self.source_file).name


def parse_exif_datetime(value) -> Tuple[Optional[datetime], Optional[timezone]]:
    """Parse 'YYYY:MM:DD HH:MM:SS[.sss][Z|+HH:MM]' -> (naive datetime, tz or None)."""
    if value is None:
        return None, None
    m = _DT_RE.search(str(value))
    if not m:
        return None, None
    try:
        dt = datetime(*(int(g) for g in m.groups()[:6]))
    except ValueError:  # e.g. "0000:00:00 00:00:00"
        return None, None
    return dt, parse_offset(m.group(7))


def parse_offset(value) -> Optional[timezone]:
    if value is None:
        return None
    value = str(value).strip()
    if value == "Z":
        return timezone.utc
    m = _OFFSET_RE.match(value)
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    if delta > timedelta(hours=14):
        return None
    return timezone(sign * delta)


def parse_filename_datetime(path: str) -> Optional[datetime]:
    m = _FILENAME_DT_RE.search(PurePath(path).name)
    if not m:
        return None
    parts = [int(g) if g is not None else 0 for g in m.groups()]
    try:
        return datetime(*parts)
    except ValueError:
        return None


def _valid_coords(lat, lon) -> bool:
    if lat is None or lon is None:
        return False
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)  # 0/0 = "no fix"


def _offset_from_gps(local: datetime, gps_utc: datetime) -> Optional[timezone]:
    """Derive the UTC offset from local time vs. GPS time, rounded to 15 min.

    GPSDateTime is the time of the last fix and can lag the shutter by a bit,
    so rounding gives a more accurate UTC time than using GPSDateTime itself.
    """
    diff = local - gps_utc.replace(tzinfo=None)
    quarters = round(diff.total_seconds() / 900)
    offset = timedelta(minutes=15 * quarters)
    if abs(offset) > timedelta(hours=14) or abs(diff - offset) > timedelta(minutes=5):
        return None
    return timezone(offset)


def normalise(record: dict, default_tz: Optional[tzinfo] = None) -> Photo:
    source = str(record.get("SourceFile", ""))
    ext = PurePath(source).suffix.lower()

    lat, lon = record.get("GPSLatitude"), record.get("GPSLongitude")
    if _valid_coords(lat, lon):
        lat, lon = float(lat), float(lon)
    else:
        lat = lon = None

    local, inline_tz, time_source = None, None, None
    for tag in ("DateTimeOriginal", "CreateDate"):
        local, inline_tz = parse_exif_datetime(record.get(tag))
        if local is not None:
            time_source = tag
            break
    if local is None:
        local = parse_filename_datetime(source)
        if local is not None:
            time_source = "filename"

    time_utc, tz_source = None, TZ_UNKNOWN
    if local is not None:
        tz = inline_tz or parse_offset(record.get("OffsetTimeOriginal"))
        if tz is not None:
            tz_source = TZ_OFFSET
        elif time_source == "CreateDate" and ext in VIDEO_EXTS:
            # QuickTime CreateDate is stored in UTC by spec.
            tz, tz_source = timezone.utc, TZ_UTC
        else:
            gps_dt, gps_tz = parse_exif_datetime(record.get("GPSDateTime"))
            if gps_dt is not None:
                tz = _offset_from_gps(local, gps_dt.replace(tzinfo=gps_tz or timezone.utc))
                if tz is not None:
                    tz_source = TZ_GPS
            if tz is None and default_tz is not None:
                tz, tz_source = default_tz, TZ_DEFAULT
        if tz is not None:
            time_utc = local.replace(tzinfo=tz).astimezone(timezone.utc)

    model = record.get("Model")
    return Photo(
        source_file=source,
        model=str(model) if model is not None else None,
        lat=lat,
        lon=lon,
        local_time=local,
        time_utc=time_utc,
        tz_source=tz_source,
        time_source=time_source,
    )


def dedupe(photos: Iterable[Photo]) -> List[Photo]:
    """Collapse HEIC+JPG (and Live Photo .MOV) copies of the same shot.

    Copies share directory and filename stem; the preferred format is kept,
    but a copy with GPS beats one without.
    """
    def rank(p: Photo):
        ext = PurePath(p.source_file).suffix.lower()
        pref = EXT_PREFERENCE.index(ext) if ext in EXT_PREFERENCE else len(EXT_PREFERENCE)
        return (not p.has_gps, p.time_utc is None, pref)

    best = {}
    for p in photos:
        path = PurePath(p.source_file)
        key = (str(path.parent).lower(), path.stem.lower())
        if key not in best or rank(p) < rank(best[key]):
            best[key] = p
    return list(best.values())


def load(path: str, default_tz: Optional[tzinfo] = None) -> List[Photo]:
    """Load an exiftool JSON export into Photo records (not deduplicated)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [normalise(r, default_tz) for r in data]


def sort_key(p: Photo):
    return (p.time_utc, p.source_file)
