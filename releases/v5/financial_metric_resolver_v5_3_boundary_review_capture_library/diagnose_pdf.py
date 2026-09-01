#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys

def main():
    if len(sys.argv) != 2:
        print("用法: python diagnose_pdf.py <pdf路径>")
        return 2

    p = Path(sys.argv[1])
    if not p.exists():
        print("NOT_FOUND", p)
        return 2

    raw = p.read_bytes()
    print("FILE:", p)
    print("SIZE_BYTES:", len(raw))
    print("FIRST_32_BYTES_HEX:", raw[:32].hex(" "))
    print("FIRST_80_BYTES_REPR:", repr(raw[:80]))

    offset = raw[:1024*1024].find(b"%PDF-")
    print("PDF_HEADER_OFFSET:", offset)

    tail = raw[-8192:] if len(raw) > 8192 else raw
    print("HAS_EOF_MARKER:", b"%%EOF" in tail)

    stripped = raw[:4096].lstrip().lower()
    looks_html = (
        stripped.startswith(b"<!doctype html")
        or stripped.startswith(b"<html")
        or b"<body" in stripped[:512]
    )
    print("LOOKS_HTML:", looks_html)

    if offset < 0:
        print("RESULT: FAIL - 未发现 %PDF- 文件头，不是真正PDF或已严重损坏。")
        return 1
    if offset > 0:
        print(f"RESULT: WARNING - %PDF- 位于 offset={offset}，文件前有额外数据。")
    if b"%%EOF" not in tail:
        print("RESULT: WARNING - 未发现 %%EOF，可能被截断。")
    else:
        print("RESULT: BASIC_PDF_SIGNATURE_OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
