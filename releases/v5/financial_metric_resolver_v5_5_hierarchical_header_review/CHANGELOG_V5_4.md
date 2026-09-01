# CHANGELOG v5.4

## P0: Structural Order Preservation
- Added explicit user-selected `排序基准表` when creating a Merge Project.
- Added immutable reference-order backbone.
- Added `canonical_order` as the authoritative merged row order.
- Removed dependence on incidental groupby/pivot/alphabetical ordering for research output.
- Added contextual insertion of source-unique rows between nearest known anchors.
- Existing reference keys are never reordered.
- Preserved:
  - row_type
  - row_level
  - parent_section
  - canonical_section
  - canonical_item
- Added `ORDER_CONFLICT` detection for shared-key inversions.
- Added `DUPLICATE_CANONICAL_KEY_IN_SOURCE` structural conflict.
- Added:
  - `merge_structural_order.csv`
  - `merge_order_conflicts.csv`
- Added Excel sheets:
  - structural_order
  - order_conflicts
- `merge_manifest.json` now records:
  - version v5.4
  - order_policy
  - reference_capture_run_id
- Taxonomy/mapping rematerialization recomputes and preserves the same structural order.

## Merge Library Management
- Added `merge_library.py`.
- Added merge-project overview table.
- Added editable display name.
- Added notes.
- Added stable run ID display.
- Added soft delete.
- Added merge recycle bin.
- Added restore.
- Added permanent delete with confirmation.
- Added conflict counts in project overview.
- Added downloads/custom export for structural order and order-conflict CSVs.

## GUI
- Added `结构顺序` tab.
- Added `管理` tab.
- Added explicit ordering-policy explanation.
- Added reference capture selector before project creation.

## Retained
- All v5.3 boundary-review and Capture Library functionality.
- All v5.2 source-quality arbitration and custom export functionality.
- All v5.1 spatial capture and taxonomy merge functionality.
