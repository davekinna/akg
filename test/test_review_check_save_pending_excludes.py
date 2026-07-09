from pathlib import Path

import pandas as pd

from review_check import ReviewCheckWindow


class _FakeCheckBox:
    def __init__(self, checked: bool = False):
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        self._checked = bool(checked)

    def blockSignals(self, _block: bool):
        return None


class _FakeCombo:
    def __init__(self, text: str):
        self._text = text

    def currentText(self) -> str:
        return self._text


class _FakeSpinBox:
    def __init__(self, value: int):
        self._value = value

    def value(self) -> int:
        return self._value


class _FakeLineEdit:
    def __init__(self, text: str):
        self._text = text

    def text(self) -> str:
        return self._text


def _row(path: str, file_name: str, source: str, pmid: int, *, excl: bool = False) -> dict:
    return {
        "path": path,
        "file": file_name,
        "source": source,
        "pmid": pmid,
        "step": 1,
        "suitable": True,
        "skip": 0,
        "gene": "",
        "pval": "",
        "lfc": "",
        "excl": excl,
        "manualreason": "",
        "manual": False,
    }


def test_on_save_persists_pending_non_adjacent_excludes(tmp_path: Path):
    tracking_rows = [
        _row("p", "table_a.csv", "supp_a.xlsx", 1),
        _row("p", "table_b.csv", "supp_a.xlsx", 1),
        _row("p", "table_c.csv", "supp_b.xlsx", 2),
        _row("p", "table_d.csv", "supp_b.xlsx", 2),
    ]
    tracking_df = pd.DataFrame(tracking_rows)

    # Keep filtered ordering stable and include all rows.
    filtered_df = tracking_df.copy().reset_index(drop=True)

    window = ReviewCheckWindow.__new__(ReviewCheckWindow)
    window.tracking_df = tracking_df
    window.filtered = filtered_df
    window.tracking_file = str(tmp_path / "tracking.csv")

    # Simulate currently visible row = index 2.
    window.current_index = 2
    window.excl_checkbox = _FakeCheckBox(True)
    window.exclude_all_in_source_checkbox = _FakeCheckBox(False)
    window.gene_choice_combo = _FakeCombo("")
    window.pval_choice_combo = _FakeCombo("")
    window.lfc_choice_combo = _FakeCombo("")
    window.reason_input = _FakeLineEdit("exclude-current")
    window.skip_spinbox = _FakeSpinBox(0)

    # Pending non-adjacent excludes across rows 0 and 2.
    window.pending_excl_values = {0: True, 2: True}
    window.pending_reason_values = {0: "exclude-a", 2: "exclude-current"}
    window.pending_gene_choices = {}
    window.pending_pval_choices = {}
    window.pending_lfc_choices = {}

    window.saved_row_values = {
        idx: {
            "skip": 0,
            "gene": "",
            "pval": "",
            "lfc": "",
            "excl": False,
            "manualreason": "",
        }
        for idx in range(len(filtered_df))
    }

    refreshed = {"called": False}

    def _fake_refresh(*_args, **_kwargs):
        refreshed["called"] = True
        return True

    window.refresh_from_tracking_file = _fake_refresh
    window.update_dirty_state = lambda: None

    ok = window.on_save(show_success_dialog=False)

    assert ok is True
    assert refreshed["called"] is True

    # Non-adjacent pending rows are persisted as excluded.
    assert bool(window.tracking_df.loc[0, "excl"]) is True
    assert bool(window.tracking_df.loc[2, "excl"]) is True
    assert str(window.tracking_df.loc[0, "manualreason"]) == "exclude-a"
    assert str(window.tracking_df.loc[2, "manualreason"]) == "exclude-current"

    # Unrelated row remains unchanged.
    assert bool(window.tracking_df.loc[1, "excl"]) is False
