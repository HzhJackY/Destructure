# PDF `No /Root object` 排错

错误：

```text
PDFSyntaxError: No /Root object! - Is this really a PDF?
```

意味着 pdfminer 无法读取 PDF Catalog `/Root`。

最常见原因：

1. `.pdf` 文件实际是 HTML 登录页/下载错误页。
2. 下载被截断，文件不完整。
3. 文件为 0 字节或异常小。
4. PDF 本身结构损坏。
5. 文件前面被加入了额外 wrapper/junk bytes。

## 一条命令诊断

```powershell
python diagnose_pdf.py .\年报.pdf
```

正常 PDF 至少应看到：

```text
PDF_HEADER_OFFSET: 0
LOOKS_HTML: False
HAS_EOF_MARKER: True
RESULT: BASIC_PDF_SIGNATURE_OK
```

## 快速直接检查

```powershell
python -c "from pathlib import Path; p=Path(r'年报.pdf'); b=p.read_bytes(); print('size=',len(b)); print('head=',repr(b[:80])); print('pdf_offset=',b[:1048576].find(b'%PDF-')); print('eof=',b'%%EOF' in b[-8192:])"
```

正常开头通常类似：

```text
b'%PDF-1.7'
```

若看到：

```text
b'<!DOCTYPE html'
b'<html'
```

说明保存的是网页，不是 PDF。

## 修复优先级

1. 从原始网站重新下载 PDF。
2. 确认下载完成、文件大小合理。
3. 若 Adobe/Edge 能正常打开但程序不能：
   - 打开 PDF
   - 打印
   - 选择 Microsoft Print to PDF / 另存为 PDF
   - 用新生成的 PDF 再导入
4. 不要通过修改扩展名把 HTML 改成 `.pdf`。

v4.1 GUI 会在导入和运行前做 PDF 文件头预检，并把这类问题显示为友好错误，而不是直接抛 traceback。
