"""Leave-one-out evaluation of GPS inference.

Each GPS photo in turn has its coordinates hidden and inferred from its
neighbouring GPS photos; the error in metres is reported as median and
90th percentile per time-gap bucket and per method.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Sequence, Tuple

from .infer import METHODS, anchors, estimate, haversine_m
from .loader import Photo

# (label, upper bound of the gap to the nearest GPS photo)
BUCKETS: List[Tuple[str, timedelta]] = [
    ("< 10 min", timedelta(minutes=10)),
    ("10-60 min", timedelta(hours=1)),
    ("1-6 h", timedelta(hours=6)),
    ("> 6 h", timedelta.max),
]


@dataclass
class Result:
    photo: Photo
    method: str              # requested method
    gap: timedelta
    error_m: float


def bucket(gap: timedelta) -> str:
    for label, upper in BUCKETS:
        if gap < upper:
            return label
    return BUCKETS[-1][0]


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    s = sorted(values)
    k = (len(s) - 1) * q / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def leave_one_out(photos: Sequence[Photo], methods: Sequence[str] = METHODS) -> List[Result]:
    anchor_list = anchors(photos)
    results: List[Result] = []
    for i, p in enumerate(anchor_list):
        prev = anchor_list[i - 1] if i > 0 else None
        nxt = anchor_list[i + 1] if i + 1 < len(anchor_list) else None
        for method in methods:
            s = estimate(p, prev, nxt, method)
            if s is None:
                continue
            results.append(Result(p, method, s.gap, haversine_m(p.lat, p.lon, s.lat, s.lon)))
    return results


def summarise(results: Sequence[Result]) -> List[Tuple[str, str, int, float, float]]:
    """Rows of (method, bucket, n, median m, p90 m), in method and bucket order."""
    groups: Dict[Tuple[str, str], List[float]] = {}
    for r in results:
        groups.setdefault((r.method, bucket(r.gap)), []).append(r.error_m)
    rows = []
    for method in METHODS:
        for label, _ in BUCKETS:
            errors = groups.get((method, label))
            if errors:
                rows.append((method, label, len(errors),
                             percentile(errors, 50), percentile(errors, 90)))
    return rows


def format_table(rows: Sequence[Tuple[str, str, int, float, float]]) -> str:
    header = ("method", "gap", "n", "median m", "p90 m")
    body = [(m, b, str(n), f"{med:.0f}", f"{p90:.0f}") for m, b, n, med, p90 in rows]
    widths = [max(len(r[i]) for r in [header, *body]) for i in range(len(header))]
    lines = []
    for r in [header, *body]:
        cells = [r[0].ljust(widths[0]), r[1].ljust(widths[1])]
        cells += [c.rjust(w) for c, w in zip(r[2:], widths[2:])]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)
