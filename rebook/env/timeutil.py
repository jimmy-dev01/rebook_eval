"""Local-time helpers shared by tools and (later) verifiers."""
from __future__ import annotations


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def format_hhmm(total_min: int) -> str:
    total_min = total_min % (24 * 60)
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def arrival_local(dep_local: str, duration_min: int, origin_offset: float, dest_offset: float) -> str:
    """Arrival clock at the destination airport.

    Departure times are local to the origin; arrivals are local to the destination.
    Offset difference converts between airport clocks (DEN −6, ORD −5 → +60 min).
    """
    shift = int(round((dest_offset - origin_offset) * 60))
    return format_hhmm(minutes(dep_local) + duration_min + shift)
