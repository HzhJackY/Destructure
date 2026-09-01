"""Shared certified-ROI row membership semantics.

Capture parsing and post-capture governance must ask the same pure function
whether a source line/row belongs to an already certified rectangle.  A PDF
glyph bbox may cross a visual/text boundary even when the row itself is on the
table side of that boundary, so vertical membership uses the bbox centre.
Horizontal membership preserves the existing overlap semantics.
"""
from __future__ import annotations

from typing import Any, Mapping


CERTIFIED_ROI_ROW_MEMBERSHIP_SEMANTICS = (
    "BBOX_VERTICAL_CENTER_HORIZONTAL_OVERLAP_V1"
)


def normalise_bbox(value: Any) -> dict[str, float]:
    """Return ``x0/y0/x1/y1`` for list or common mapping bbox shapes."""
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            payload = {
                "x0": float(value[0]),
                "y0": float(value[1]),
                "x1": float(value[2]),
                "y1": float(value[3]),
            }
        except (TypeError, ValueError):
            return {}
        return payload if _valid_bbox(payload) else {}
    if not isinstance(value, Mapping):
        return {}
    aliases = {
        "x0": ("x0", "left"),
        "y0": ("y0", "top"),
        "x1": ("x1", "right"),
        "y1": ("y1", "bottom"),
    }
    payload: dict[str, float] = {}
    for coordinate, names in aliases.items():
        for name in names:
            if value.get(name) is not None:
                try:
                    payload[coordinate] = float(value[name])
                except (TypeError, ValueError):
                    return {}
                break
    return payload if len(payload) == 4 and _valid_bbox(payload) else {}


def _valid_bbox(value: Mapping[str, float]) -> bool:
    return value["x1"] >= value["x0"] and value["y1"] >= value["y0"]


def belongs_to_certified_roi(
    candidate_bbox: Any,
    certified_bbox: Any,
) -> bool:
    """Decide row membership for an already certified rectangular ROI.

    The vertical centre is the stable row anchor.  Full glyph containment is
    deliberately not required because font ascent/descent boxes may cross the
    certified boundary.  Horizontal overlap is unchanged from the spatial
    parser and still excludes a wholly separate side region.
    """
    candidate = normalise_bbox(candidate_bbox)
    certified = normalise_bbox(certified_bbox)
    if not candidate or not certified:
        return False
    vertical_anchor = (candidate["y0"] + candidate["y1"]) / 2.0
    return (
        candidate["x1"] >= certified["x0"]
        and candidate["x0"] <= certified["x1"]
        and certified["y0"] <= vertical_anchor <= certified["y1"]
    )
