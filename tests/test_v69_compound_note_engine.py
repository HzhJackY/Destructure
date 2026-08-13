from __future__ import annotations

from compound_note_engine import segment_table_blocks
from table_capture import TableCaptureResult, TableCell, TableColumn, TableRow


def _row(order, label, value=None, page=109, row_type="DETAIL", block="A"):
    return TableRow(order, page, block, "TEST", label, label or "", None, "UNMAPPED", row_type, 0, None,
                    [TableCell(0, 0, "" if value is None else str(value), value, "人民币百万元", value)], page)


def _result(rows):
    return TableCaptureResult("新华保险2023年报.pdf", "sha", "金融投资", "11", "金融投资", 109, 110, [109,110], "人民币百万元",
                              [TableColumn(0,0,"2023", "2023", "CONSOLIDATED", False, "ANNUAL")], rows, [], {})


def test_single_logical_table_is_not_split_without_evidence():
    container, blocks = segment_table_blocks(_result([_row(1,"政府债",100), _row(2,"金融债",50), _row(3,"合计",150)]))
    assert container.note_reference == "11"
    assert len(blocks) == 1
    assert blocks[0].reconciliation["status"] == "PASS"


def test_narrative_separator_creates_independent_block():
    rows = [_row(1,"第一表",1), _row(2,"本表以下为另一种计量口径，采用不同的列头说明",None,row_type="NOTE_TEXT"),
            _row(3,"第二表",2,page=110,block="B")]
    _, blocks = segment_table_blocks(_result(rows))
    assert len(blocks) == 2
    assert blocks[0].role == "PRIMARY_TABLE"
    assert blocks[1].role == "SECONDARY_TABLE"
