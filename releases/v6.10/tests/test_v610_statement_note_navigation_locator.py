"""Regression coverage for section-aware note navigation.

These are synthetic text-layer cases: the locator must remain generic and must
not depend on a particular company, annual report year or physical page.
"""
from statement_note_navigation import TextIndexRecord, locate_note


def _rec(page: int, text: str, section: str = "") -> TextIndexRecord:
    return TextIndexRecord(page, text, "", section, ())


def test_bare_note_ordinal_handles_ideographic_space_without_nameerror():
    index = [_rec(21, "11\u3000\u3000债权投资\n按摊余成本计量")]
    page, method, confidence = locate_note(index, note_reference="附注11", item="债权投资")
    assert page == 21
    assert method == "ORDINAL_EXACT_HEADING_WITH_CONTEXT"
    assert confidence == 0.90


def test_section_and_ordinal_prefers_matching_note_section():
    index = [
        _rec(31, "六、金融资产\n10. 交易性金融资产"),
        _rec(32, "七、金融资产\n10\u3000交易性金融资产"),
    ]
    page, method, confidence = locate_note(
        index,
        note_reference="附注七-10",
        item="交易性金融资产",
    )
    assert page == 32
    assert method == "SECTION_ORDINAL_EXACT_HEADING"
    assert confidence == 0.98


def test_explicit_section_can_be_embedded_in_heading_line():
    index = [_rec(41, "附注七-12\u3000其他债权投资")]
    page, method, confidence = locate_note(index, note_reference="附注七-12", item="其他债权投资")
    assert page == 41
    assert method == "SECTION_ORDINAL_EXACT_HEADING"
    assert confidence == 0.98


def test_contents_page_ordinal_and_item_is_never_certified_as_detail_target():
    index = [
        _rec(8, "目录\n附注七-12 其他债权投资 ........ 171\n附注七-13 其他权益工具投资 .... 172\n附注七-14 长期股权投资 .... 173"),
    ]
    page, method, confidence = locate_note(index, note_reference="附注七-12", item="其他债权投资")
    assert page is None
    assert method == "TOC_ONLY_MATCH_REVIEW_REQUIRED"
    assert confidence == 0.0


def test_token_cooccurrence_without_heading_is_review_required_not_certified():
    index = [_rec(55, "本集团债权投资的附注11相关会计政策详见上文。", section="七")]
    page, method, confidence = locate_note(index, note_reference="附注七-11", item="债权投资")
    assert page is None
    assert method in {"DIRECT_SEARCH_UNVERIFIED_REVIEW_REQUIRED", "NOTE_REF_ITEM_UNVERIFIED_REVIEW_REQUIRED"}
    assert confidence == 0.0


def test_adjacent_ordinal_and_item_lines_form_a_verified_note_heading():
    index = [_rec(188, "186\n12\n债权投资\n2023年12月31日\n债券\n国债及政府债")]
    page, method, confidence = locate_note(index, note_reference="附注12", item="债权投资")
    assert page == 188
    assert method == "ORDINAL_EXACT_HEADING_WITH_CONTEXT"
    assert confidence == 0.90
