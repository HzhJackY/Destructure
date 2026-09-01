from statement_family_resolution import _is_descendant_of_parent


def test_split_statement_rows_do_not_close_parent_by_raw_line_distance():
    # Xinhua 2023: the fourth child is visually inside 金融投资 but its label
    # arrives 25 extracted lines after the parent because note/amount cells
    # are emitted on separate lines.
    assert _is_descendant_of_parent(
        100,
        75,
        structural_boundary_index=132,
    )


def test_registered_outside_member_closes_parent_boundary():
    assert not _is_descendant_of_parent(
        150,
        75,
        structural_boundary_index=132,
    )
