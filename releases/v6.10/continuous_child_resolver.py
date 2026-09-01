"""Generic contiguous statement-child resolver; no family-specific names."""
from __future__ import annotations
from typing import Any

def resolve_continuous_children(rows:list[dict[str,Any]], parent_index:int, *, max_children:int=12)->dict[str,Any]:
    parent=rows[parent_index]; children=[]
    base_indent=float(parent.get('indent',0) or 0)
    for row in rows[parent_index+1:parent_index+1+max_children]:
        text=str(row.get('item') or row.get('text') or '').strip()
        if not text: continue
        if row.get('is_section_boundary') or (row.get('indent') is not None and float(row.get('indent') or 0)<base_indent): break
        children.append(dict(row))
    return {'parent':dict(parent),'children':children,'boundary_confidence':1.0 if children else 0.0,'resolver':'GENERIC_CONTIGUOUS_CHILD_RESOLVER'}
