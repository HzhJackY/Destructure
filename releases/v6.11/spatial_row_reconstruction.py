"""
spatial_row_reconstruction.py - Generic TSV Spatial BBox Reconstruction Engine for v6.11

Implements:
1. BBox-based spatial token insertion and line reconstruction (erasing vertical OCR splits cleanly).
2. Table column topology analysis (Note Column, Amount Columns X-ranges).
3. Certified Note Bounding via BBox geometry.
4. Provenance tracking via explicit repair_operations audit log.
5. Multi-dimensional explicit status output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BBoxToken:
    left: float
    top: float
    right: float
    bottom: float
    text: str
    confidence: float = 1.0

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class ColumnTopology:
    label_x_range: tuple[float, float] = (0.0, 0.0)
    note_x_range: tuple[float, float] = (0.0, 0.0)
    current_amount_x_range: tuple[float, float] = (0.0, 0.0)
    comparative_amount_x_range: tuple[float, float] = (0.0, 0.0)
    has_certified_note_column: bool = False
    has_certified_amount_columns: bool = False
    # Each entry is immutable OCR geometry describing a statement data column.
    # It is intentionally distinct from a Capture/canonical value column.
    period_columns: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReconstructedLine:
    line_index: int
    text: str
    tokens: list[BBoxToken]
    repair_operations: list[dict[str, Any]] = field(default_factory=list)
    repair_confidence: float = 1.0


def words_to_bbox_tokens(words: list[tuple]) -> list[BBoxToken]:
    tokens = []
    for w in words:
        if len(w) < 5:
            continue
        x0, y0, x1, y1, text = w[:5]
        text_str = str(text).strip()
        if text_str:
            tokens.append(BBoxToken(left=float(x0), top=float(y0), right=float(x1), bottom=float(y1), text=text_str))
    return tokens


def derive_column_topology(tokens: list[BBoxToken]) -> ColumnTopology:
    """Analyze header tokens to determine BBox X-ranges for Note and Amount columns."""
    if not tokens:
        return ColumnTopology()

    # Find line containing 附注 / 注释 / 资产 / 202x年
    header_tokens = [t for t in tokens if any(k in t.text for k in ["附注", "注释", "注", "资产", "2024", "2025", "2023"])]

    note_tokens = [t for t in header_tokens if any(k in t.text for k in ["附注", "注释"])]
    
    topology = ColumnTopology()

    if note_tokens:
        n_left = min(t.left for t in note_tokens) - 15.0
        n_right = max(t.right for t in note_tokens) + 25.0
        topology.note_x_range = (n_left, n_right)
        topology.has_certified_note_column = True

    # Amount columns are identified only from the *table header row*.  A
    # document title often also contains “2023”, so taking the first two year
    # tokens (the former implementation) produced overlapping, false amount
    # ranges on scanned financial statements.  Select the lowest horizontal
    # cluster with at least two year headers, then form non-overlapping bands
    # around their centres.
    year_tokens = [t for t in tokens if re.fullmatch(r"202\d", t.text)]
    clusters: list[list[BBoxToken]] = []
    for token in sorted(year_tokens, key=lambda item: item.y_center):
        for cluster in clusters:
            center = sum(item.y_center for item in cluster) / len(cluster)
            if abs(token.y_center - center) <= 90.0:
                cluster.append(token)
                break
        else:
            clusters.append([token])
    valid_clusters = [cluster for cluster in clusters if len(cluster) >= 2]
    if valid_clusters:
        header_years = max(
            valid_clusters,
            key=lambda cluster: (len(cluster), sum(item.y_center for item in cluster) / len(cluster)),
        )
        header_years.sort(key=lambda item: item.x_center)
        centres = [item.x_center for item in header_years]
        for index, token in enumerate(header_years):
            left = 0.0 if index == 0 else (centres[index - 1] + centres[index]) / 2.0
            right = float("inf") if index == len(header_years) - 1 else (centres[index] + centres[index + 1]) / 2.0
            topology.period_columns.append({
                "period_label": token.text,
                "x_range": (left, right),
                "header_bbox": [token.left, token.top, token.right, token.bottom],
                "column_index": index,
            })
        topology.current_amount_x_range = tuple(topology.period_columns[0]["x_range"])
        if len(topology.period_columns) > 1:
            topology.comparative_amount_x_range = tuple(topology.period_columns[1]["x_range"])
        topology.has_certified_amount_columns = True

    return topology


def reconstruct_spatial_lines(words: list[tuple]) -> list[ReconstructedLine]:
    """Reconstruct lines from TSV words using BBox geometry, inserting vertical/horizontal fragments."""
    raw_tokens = words_to_bbox_tokens(words)
    if not raw_tokens:
        return []

    # Sort tokens into initial lines by Y-coordinate
    raw_tokens.sort(key=lambda t: (t.top, t.left))
    
    # Estimate median line height
    heights = [t.height for t in raw_tokens if t.height > 5]
    median_h = sorted(heights)[len(heights) // 2] if heights else 15.0

    line_groups: list[list[BBoxToken]] = []
    for t in raw_tokens:
        if not line_groups:
            line_groups.append([t])
            continue
        last_group = line_groups[-1]
        group_avg_y = sum(item.y_center for item in last_group) / len(last_group)
        if abs(t.y_center - group_avg_y) <= median_h * 0.5:
            last_group.append(t)
        else:
            line_groups.append([t])

    # Perform Spatial Fragment Insertion for detached single characters (e.g. '性')
    reconstructed_lines: list[ReconstructedLine] = []
    
    for idx, group in enumerate(line_groups):
        group.sort(key=lambda t: t.left)
        repairs = []

        # Check if previous or next group has a single detached character that belongs horizontally in this group
        if idx > 0:
            prev_group = line_groups[idx - 1]
            if len(prev_group) == 1 and len(prev_group[0].text) == 1:
                orphan = prev_group[0]
                # Check vertical proximity
                group_y = sum(t.y_center for t in group) / len(group)
                if abs(orphan.y_center - group_y) <= median_h * 1.5:
                    # Check if orphan fits horizontally between two tokens in group
                    for i in range(len(group)):
                        left_bound = group[i - 1].right if i > 0 else 0.0
                        right_bound = group[i].left
                        if left_bound <= orphan.x_center <= right_bound:
                            group.insert(i, orphan)
                            repairs.append({
                                "type": "INSERT_DETACHED_CHARACTER",
                                "token": orphan.text,
                                "insert_after": group[i - 1].text if i > 0 else "^",
                                "insert_before": group[i + 1].text if i + 1 < len(group) else "$",
                                "basis": "BBOX_X_Y_ALIGNMENT",
                                "source_bbox": [orphan.left, orphan.top, orphan.right, orphan.bottom]
                            })
                            break

        line_text = " ".join(t.text for t in group)
        reconstructed_lines.append(ReconstructedLine(
            line_index=idx,
            text=line_text,
            tokens=group,
            repair_operations=repairs,
            repair_confidence=1.0 if not repairs else 0.9
        ))

    return reconstructed_lines


def bind_detached_note_reference(
    line: ReconstructedLine,
    next_line: Optional[ReconstructedLine],
    topology: ColumnTopology,
    raw_note_in_line: str
) -> tuple[str, str, float]:
    """Bind note reference using BBox column topology geometry.

    Returns: (note_ordinal, binding_status, confidence)
    """
    if raw_note_in_line:
        # Check if in note column or header
        return raw_note_in_line, "EXPLICIT_HEADER", 1.0

    if not next_line:
        return "", "UNBOUND", 0.0

    # Inspect next_line tokens for a detached note digit
    for t in next_line.tokens:
        if re.fullmatch(r"\d{1,3}", t.text):
            # Verify BBox geometry
            if topology.has_certified_note_column:
                n_min, n_max = topology.note_x_range
                if n_min <= t.x_center <= n_max:
                    return t.text, "CERTIFIED_NOTE_COLUMN_GEOMETRY", 0.95
            else:
                # If no topology certified, check reasonable X position (left third of table)
                if t.left < 500.0:
                    return t.text, "GEOMETRIC_NOTE_COLUMN_FALLBACK", 0.75

    return "", "UNBOUND", 0.0
