# ADR-003 — CPIC High-Resolution Financial-Table OCR

Status: FROZEN

CPIC image-dominant target pages use the existing conditional OCR pipeline with a high-resolution financial-table profile, normally 400 DPI for the certified page/ROI.

OCR tokens never become certified amounts directly. Cache identity includes DPI, profile, segmentation mode, crop, language pack, and preprocessing version.
