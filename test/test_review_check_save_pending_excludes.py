from pathlib import Path

import pandas as pd

from review_check import ReviewCheckWindow, load_ui_settings


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
    window.exclude_all_in_publication_checkbox = _FakeCheckBox(False)
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


def test_on_save_persists_pending_non_current_gene_choice(tmp_path: Path):
    tracking_rows = [
        _row("p", "table_a.csv", "supp_a.xlsx", 1),
        _row("p", "table_b.csv", "supp_a.xlsx", 1),
        _row("p", "table_c.csv", "supp_b.xlsx", 2),
    ]
    tracking_df = pd.DataFrame(tracking_rows)
    filtered_df = tracking_df.copy().reset_index(drop=True)

    window = ReviewCheckWindow.__new__(ReviewCheckWindow)
    window.tracking_df = tracking_df
    window.filtered = filtered_df
    window.tracking_file = str(tmp_path / "tracking.csv")

    # Simulate viewing row 2 when Save is clicked.
    window.current_index = 2
    window.excl_checkbox = _FakeCheckBox(False)
    window.exclude_all_in_source_checkbox = _FakeCheckBox(False)
    window.exclude_all_in_publication_checkbox = _FakeCheckBox(False)
    window.gene_choice_combo = _FakeCombo("")
    window.pval_choice_combo = _FakeCombo("")
    window.lfc_choice_combo = _FakeCombo("")
    window.reason_input = _FakeLineEdit("")
    window.skip_spinbox = _FakeSpinBox(0)

    # User previously changed gene choice on row 0, then navigated away.
    window.pending_gene_choices = {0: "gene_symbol"}
    window.pending_pval_choices = {}
    window.pending_lfc_choices = {}
    window.pending_excl_values = {}
    window.pending_reason_values = {}

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
    assert str(window.tracking_df.loc[0, "gene"]) == "gene_symbol"
    assert str(window.tracking_df.loc[1, "gene"]) == ""
    assert str(window.tracking_df.loc[2, "gene"]) == ""


def test_review_position_persists_and_restores(tmp_path: Path):
    tracking_rows = [
        _row("p", "table_a.csv", "supp_a.xlsx", 1),
        _row("p", "table_b.csv", "supp_a.xlsx", 1),
        _row("p", "table_c.csv", "supp_b.xlsx", 2),
    ]
    tracking_df = pd.DataFrame(tracking_rows)
    filtered_df = tracking_df.copy().reset_index(drop=True)

    settings_file = tmp_path / "review_check_settings.json"

    window = ReviewCheckWindow.__new__(ReviewCheckWindow)
    window.tracking_df = tracking_df
    window.filtered = filtered_df
    window.settings_file = str(settings_file)
    window.current_index = 1
    window.last_review_position = {}

    window.persist_review_position(1)

    settings = load_ui_settings(str(settings_file))
    assert settings["last_review_position"] == {"path": "p", "file": "table_b.csv"}

    restored_window = ReviewCheckWindow.__new__(ReviewCheckWindow)
    restored_window.filtered = filtered_df
    restored_window.last_review_position = settings["last_review_position"]
    restored_window.display_order_indices = [0, 1, 2]

    assert restored_window.resolve_initial_review_index() == 1
