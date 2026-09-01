from capture_library import capture_readiness, is_orphan_numeric_noise


def test_short_blank_numeric_token_between_labelled_rows_is_not_implicit_business_row():
    rows = [
        {"row_role": "DETAIL", "raw_item": "次级债券", "cells": [{"raw": "62306"}]},
        {"row_role": "IMPLICIT_ROW_CANDIDATE", "raw_item": None, "cells": [{"raw": "07"}]},
        {"row_role": "DETAIL", "raw_item": "股票", "cells": [{"raw": "91299"}]},
        {"row_role": "TOTAL", "raw_item": "合计", "cells": [{"raw": "380239"}]},
    ]
    assert is_orphan_numeric_noise(rows, 1)
    result = {"boundary_status": "HUMAN_CONFIRMED", "header_dimension_status": "AUTO_CONFIRMED", "rows": rows,
              "stats": {"v69_header_topology": {"consistent": True}, "v69_reconciliation": {"status": "PASS"}}}
    assert capture_readiness(result)["unresolved_implicit_rows"] == 0
