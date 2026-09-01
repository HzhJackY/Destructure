#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse
import json
from pathlib import Path

from batch_pipeline import aggregate_batch_results, run_batch_jobs, write_batch_artifacts
from data_home import resolve_data_home, ensure_data_home


def main() -> int:
    app_dir = Path(__file__).resolve().parent
    data_paths = ensure_data_home(resolve_data_home(app_dir), app_dir / "metric_aliases.json")
    p = argparse.ArgumentParser(description="v5.9 multi-PDF fast-index batch extractor")
    p.add_argument("pdfs", nargs="+")
    p.add_argument("--metrics", nargs="+", required=True)
    p.add_argument("--rules", default=str(data_paths["rules"]))
    p.add_argument("--output-dir", default=str(data_paths["batch_runs"] / "cli_batch_output"))
    p.add_argument("--cache-root", default=str(data_paths["cache"]))
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--ocr-mode", choices=["off", "auto", "force"], default="off")
    p.add_argument("--ocr-language", default="chi_sim+eng")
    p.add_argument("--ocr-dpi", type=int, default=150)
    args = p.parse_args()

    jobs = [{
        "pdf_path": str(Path(x).resolve()),
        "rules_path": str(Path(args.rules).resolve()),
        "cache_root": str(Path(args.cache_root).resolve()),
        "metrics": args.metrics,
        "ocr_mode": args.ocr_mode,
        "ocr_language": args.ocr_language,
        "ocr_dpi": args.ocr_dpi,
    } for x in args.pdfs]

    def progress(evt):
        if evt["event"] == "job_done":
            r = evt["result"]
            print(f"[{evt['index']}/{evt['total']}] {r.get('pdf_name')} done "
                  f"{r.get('elapsed_seconds','-')}s error={r.get('error','-')}")

    results = run_batch_jobs(jobs, max_workers=args.workers, progress_callback=progress)
    out = Path(args.output_dir)
    long_df, wide_df = write_batch_artifacts(out, results)

    print("Output:", out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
