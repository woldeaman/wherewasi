"""Command-line interface: `python -m wherewasi <command> ...`."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import timedelta, tzinfo
from typing import List, Optional

from . import infer as infer_mod
from .loader import TZ_UNKNOWN, load, parse_offset
from .track import TrackError, find_photo, select_between, to_gpx


def _tz(value: str) -> tzinfo:
    tz = parse_offset(value)
    if tz is not None:
        return tz
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(value)
    except Exception:
        raise argparse.ArgumentTypeError(
            f"invalid time zone {value!r} (use e.g. +09:00 or Asia/Tokyo)"
        )


def cmd_track(args) -> int:
    photos = load(args.photos_json, args.default_tz)
    try:
        start = find_photo(photos, args.start)
        end = find_photo(photos, args.end)
    except TrackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    points = select_between(photos, start, end)
    name = args.name or f"{start.name} – {end.name}"
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(to_gpx(points, name))

    sources = Counter(p.tz_source for p in points)
    print(f"{len(points)} GPS points between {start.name} and {end.name}")
    print("time zone source: " + ", ".join(f"{k}={v}" for k, v in sorted(sources.items())))
    skipped = sum(1 for p in photos if p.has_gps and p.tz_source == TZ_UNKNOWN)
    if skipped:
        print(f"warning: {skipped} GPS photos skipped (time zone unknown); "
              f"see --default-tz", file=sys.stderr)
    print(f"Written {args.output}")
    return 0


def cmd_infer(args) -> int:
    photos = load(args.photos_json, args.default_tz)
    max_gap = timedelta(hours=args.max_gap) if args.max_gap > 0 else None
    suggestions, skipped = infer_mod.infer(photos, args.method, max_gap)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        infer_mod.write_csv(suggestions, f)

    methods = Counter(s.method for s in suggestions)
    print(f"{len(suggestions)} GPS suggestions for photos without GPS")
    if methods:
        print("method: " + ", ".join(f"{k}={v}" for k, v in sorted(methods.items())))
    no_tz = sum(1 for p in skipped if p.time_utc is None)
    if no_tz:
        print(f"warning: {no_tz} photos skipped (time zone unknown); "
              f"see --default-tz", file=sys.stderr)
    if len(skipped) > no_tz:
        print(f"warning: {len(skipped) - no_tz} photos skipped "
              f"(no GPS photo within --max-gap)", file=sys.stderr)
    print(f"Written {args.output}")
    return 0


def cmd_not_implemented(args) -> int:
    print(f"'{args.command}' is not implemented yet.", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wherewasi",
        description="Repair photo metadata (reads an exiftool JSON export).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("photos_json", help="exiftool JSON export (see README)")
        p.add_argument("--default-tz", type=_tz, metavar="TZ",
                       help="time zone for photos without offset/GPS time, "
                            "e.g. +09:00 or Asia/Tokyo")

    p = sub.add_parser("track", help="GPX of all GPS photos between two chosen photos")
    common(p)
    p.add_argument("start", help="first photo (filename or path)")
    p.add_argument("end", help="last photo (filename or path)")
    p.add_argument("-o", "--output", default="track.gpx", help="output GPX (default: track.gpx)")
    p.add_argument("--name", help="track name (default: '<start> – <end>')")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("infer", help="CSV of GPS suggestions for photos without GPS")
    common(p)
    p.add_argument("-o", "--output", default="suggestions.csv",
                   help="output CSV (default: suggestions.csv)")
    p.add_argument("--method", choices=infer_mod.METHODS, default=infer_mod.INTERPOLATE,
                   help="inference method (default: interpolate)")
    p.add_argument("--max-gap", type=float, default=24, metavar="HOURS",
                   help="skip photos further than this from any GPS photo; "
                        "0 = no limit (default: 24)")
    p.set_defaults(func=cmd_infer)

    p = sub.add_parser("evaluate", help="[not implemented] leave-one-out error vs. time gap")
    common(p)
    p.set_defaults(func=cmd_not_implemented)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
