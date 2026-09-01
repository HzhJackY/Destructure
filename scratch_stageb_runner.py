from __future__ import annotations
import json, os, shutil, sys, time
from pathlib import Path
from typing import Any
ROOT = Path(r'c:/dev/AXA_research')
RELEASE_V614 = ROOT / 'releases' / 'v6.14'
sys.path.insert(0, str(RELEASE_V614))
from backend_context import build_backend_services
from data_home import ensure_data_home
from golden_identity import load_yaml
from table_capture import capture_named_table, capture_to_long_df, capture_to_wide_df, write_capture_artifacts
CORPUS_ROOT = ROOT / 'golden_corpus' / 'v1.2.0' / 'companies'
DOCU_ROOT = ROOT / 'docu'
OUTPUT_RUN_ROOT = ROOT / 'output' / '_agent_runs' / 'v614_m1_stageb_five_extended_companies'
COMPANIES = [{'id': 'sunshine_insurance', 'name': '阳光保险', 'pdf': '阳光保险{year}年度报告.pdf'}, {'id': 'picc_pnc', 'name': '中国财险', 'pdf': '中国财险{year}年度报告.pdf'}, {'id': 'china_re', 'name': '中国再保', 'pdf': '中国再保{year}年年度报告.pdf'}, {'id': 'zhongan_online', 'name': '众安在线', 'pdf': '众安在线{year}年度报告.pdf'}, {'id': 'aia', 'name': '友邦保险', 'pdf': '友邦保险{year}年报.pdf'}]
YEARS = [2023, 2024, 2025]
def run_stageb():
    if OUTPUT_RUN_ROOT.exists(): shutil.rmtree(OUTPUT_RUN_ROOT)
    OUTPUT_RUN_ROOT.mkdir(parents=True, exist_ok=True)
    data_home = OUTPUT_RUN_ROOT / 'data_home'
    paths = ensure_data_home(data_home, RELEASE_V614 / 'metric_aliases.json')
    backend = build_backend_services(paths)
    results = []
    start_time = time.time()
    print('=== STARTING STAGE B EXECUTION FOR 5 EXTENDED COMPANIES 30 CELLS ===')
    for comp in COMPANIES:
        comp_id, comp_name = comp['id'], comp['name']
        print(f'\n>>> Processing: {comp_name} [{comp_id}]')
        for year in YEARS:
            pdf_path = DOCU_ROOT / comp['pdf'].format(year=year)
            if not pdf_path.exists(): raise FileNotFoundError(f'Missing PDF: {pdf_path}')
            backend.registry.upsert_pdf({'pdf_id': str(pdf_path), 'filename': pdf_path.name, 'display_name': pdf_path.name, 'company': comp_name, 'document_year': str(year), 'size_bytes': pdf_path.stat().st_size, 'path': str(pdf_path.resolve()), 'modified_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
            # 1. INVESTMENT_PORTFOLIO_V2
            ip_sidecar = load_yaml(CORPUS_ROOT / comp_id / str(year) / 'golden_identity_v1_2_investment_portfolio.yaml')
            ip_tables = ip_sidecar.get('physical_tables') or []
            print(f'  [{comp_name} {year}] INVESTMENT_PORTFOLIO_V2: {len(ip_tables)} tables...')
            ip_caps = []
            for pt in ip_tables:
                pt_id, pt_page, pt_title, pt_unit = pt['physical_table_id'], int(pt['physical_page_number']), pt['title'], pt['unit']
                out_dir = OUTPUT_RUN_ROOT / 'captures' / f'{comp_id}_{year}_IP_{pt_id}'
                out_dir.mkdir(parents=True, exist_ok=True)
                try:
                    res = capture_named_table(pdf_path=pdf_path, table_query=pt_title, start_page_override=pt_page, max_pages=1, certified_amount_unit=pt_unit, physical_table_id=pt_id, allow_legacy_fallback=True)
                except Exception:
                    core = pt_title.split('（')[0].strip()
                    res = capture_named_table(pdf_path=pdf_path, table_query=core, start_page_override=pt_page, max_pages=1, certified_amount_unit=pt_unit, physical_table_id=pt_id, allow_legacy_fallback=True)
                long_df, wide_df = capture_to_long_df(res), capture_to_wide_df(res)
                write_capture_artifacts(out_dir, result=res, pdf_path=pdf_path, table_name=pt_title, unit=pt_unit, geometry_source='NATIVE_AND_SPATIAL_GEOMETRY')
                ip_caps.append({'physical_table_id': pt_id, 'page': pt_page, 'title': pt_title, 'unit': pt_unit, 'columns': len(res.columns), 'rows': len(res.rows), 'long_df_rows': len(long_df), 'wide_df_rows': len(wide_df), 'artifacts_dir': str(out_dir)})
            results.append({'company_id': comp_id, 'company_name': comp_name, 'year': year, 'registry_id': 'INVESTMENT_PORTFOLIO_V2', 'status': 'SUCCESS', 'tables': ip_caps})
            # 2. FINANCIAL_INVESTMENT_V1
            fi_sidecar = load_yaml(CORPUS_ROOT / comp_id / str(year) / 'golden_identity_v1_2_financial_investment.yaml')
            fi_tables = fi_sidecar.get('physical_tables') or []
            print(f'  [{comp_name} {year}] FINANCIAL_INVESTMENT_V1: {len(fi_tables)} tables...')
            fi_caps = []
            for pt in fi_tables:
                pt_id, pt_page, pt_title, pt_unit = pt['physical_table_id'], int(pt['physical_page_number']), pt['title'], pt['unit']
                clean_id = pt_id.replace('::', '_')
                out_dir = OUTPUT_RUN_ROOT / 'captures' / f'{comp_id}_{year}_FI_{clean_id}'
                out_dir.mkdir(parents=True, exist_ok=True)
                try:
                    res = capture_named_table(pdf_path=pdf_path, table_query=pt_title, start_page_override=pt_page, max_pages=1, certified_amount_unit=pt_unit, physical_table_id=pt_id, allow_legacy_fallback=True)
                except Exception:
                    core = pt_title.split('（')[0].strip()
                    res = capture_named_table(pdf_path=pdf_path, table_query=core, start_page_override=pt_page, max_pages=1, certified_amount_unit=pt_unit, physical_table_id=pt_id, allow_legacy_fallback=True)
                long_df, wide_df = capture_to_long_df(res), capture_to_wide_df(res)
                write_capture_artifacts(out_dir, result=res, pdf_path=pdf_path, table_name=pt_title, unit=pt_unit, geometry_source='NATIVE_AND_SPATIAL_GEOMETRY')
                fi_caps.append({'physical_table_id': pt_id, 'page': pt_page, 'title': pt_title, 'unit': pt_unit, 'columns': len(res.columns), 'rows': len(res.rows), 'long_df_rows': len(long_df), 'wide_df_rows': len(wide_df), 'artifacts_dir': str(out_dir)})
            results.append({'company_id': comp_id, 'company_name': comp_name, 'year': year, 'registry_id': 'FINANCIAL_INVESTMENT_V1', 'status': 'SUCCESS', 'tables': fi_caps})
    elapsed = time.time() - start_time
    summary = {'status': 'COMPLETE', 'total_cells': len(results), 'successful_cells': sum(1 for r in results if r['status'] == 'SUCCESS'), 'elapsed_seconds': round(elapsed, 2), 'results': results}
    (OUTPUT_RUN_ROOT / 'stageb_execution_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n=== STAGE B EXECUTION COMPLETE: {summary['successful_cells']}/{summary['total_cells']} CELLS IN {summary['elapsed_seconds']}s ===')
    return summary
if __name__ == '__main__':
    run_stageb()
