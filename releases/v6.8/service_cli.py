#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless v6.1 service CLI proving core asset workflows do not require Streamlit."""
from __future__ import annotations
import argparse,json
from pathlib import Path

from data_home import resolve_data_home,ensure_data_home
from backend_context import build_backend_services

APP_DIR=Path(__file__).resolve().parent


def backend():
    root=resolve_data_home(APP_DIR)
    paths=ensure_data_home(root,APP_DIR/'metric_aliases.json')
    b=build_backend_services(paths);b.registry_service.bootstrap_if_needed();return b


def main()->int:
    p=argparse.ArgumentParser(description='Financial Metric Resolver v6.1 headless service CLI')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('registry-stats');sub.add_parser('sync-registry')
    lc=sub.add_parser('list-captures');lc.add_argument('--status');lc.add_argument('--limit',type=int,default=50);lc.add_argument('--include-trash',action='store_true')
    lb=sub.add_parser('list-batches');lb.add_argument('--include-trashed',action='store_true')
    inv=sub.add_parser('invalidate');inv.add_argument('capture_ids',nargs='+');inv.add_argument('--reason',default='OTHER');inv.add_argument('--note',default='')
    rea=sub.add_parser('reactivate');rea.add_argument('capture_ids',nargs='+')
    jobs=sub.add_parser('list-jobs');jobs.add_argument('--limit',type=int,default=50)
    args=p.parse_args();b=backend()
    if args.cmd=='registry-stats':out=b.registry_service.stats()
    elif args.cmd=='sync-registry':out=b.registry_service.full_sync()
    elif args.cmd=='list-captures':out=b.capture_service.list(lifecycle_status=args.status,include_trash=args.include_trash,limit=args.limit)
    elif args.cmd=='list-batches':out=b.batch_service.list_batches(include_fully_trashed=args.include_trashed)
    elif args.cmd=='invalidate':out=b.asset_service.invalidate(args.capture_ids,reason_code=args.reason,note=args.note)
    elif args.cmd=='reactivate':out=b.asset_service.reactivate(args.capture_ids)
    elif args.cmd=='list-jobs':out=b.job_service.list(limit=args.limit)
    else:raise AssertionError(args.cmd)
    print(json.dumps(out,ensure_ascii=False,indent=2,default=str));return 0

if __name__=='__main__':raise SystemExit(main())
