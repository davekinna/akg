from pathlib import Path

import pandas as pd

from csv_data_cleaning import has_existing_step3_for_source
from tracking import create_empty_tracking_store, refresh_step0_tracking_entries, tracking_entry


def _step_row(step: int, path: Path, pmid: str, file_name: str, source: str = "") -> pd.DataFrame:
    return tracking_entry(
        step,
        str(path),
        pmid,
        file_name,
        False,
        True,
        source,
        False,
        False,
        "",
        0,
        "",
        "",
        "",
        "",
        0,
        0,
        True,
        "",
    )


def test_refresh_step0_tracking_entries_adds_new_files_once(tmp_path: Path):
    main_dir = tmp_path / "data"
    pmid_dir = main_dir / "supp_data" / "12345678"
    pmid_dir.mkdir(parents=True)

    existing_file = pmid_dir / "existing.xlsx"
    new_file = pmid_dir / "new.xlsx"
    existing_file.write_text("", encoding="utf-8")
    new_file.write_text("", encoding="utf-8")

    existing_df = create_empty_tracking_store()
    existing_df = pd.concat(
        [existing_df, _step_row(0, pmid_dir, "12345678", "existing.xlsx")],
        ignore_index=True,
    )

    refreshed = refresh_step0_tracking_entries(existing_df, str(main_dir))
    step0_files = set(refreshed[refreshed["step"] == 0]["file"].tolist())
    assert step0_files == {"existing.xlsx", "new.xlsx"}

    refreshed_again = refresh_step0_tracking_entries(refreshed, str(main_dir))
    assert len(refreshed_again) == len(refreshed)


def test_has_existing_step3_for_source_detects_existing_and_pending_rows(tmp_path: Path):
    root = tmp_path / "supp_data" / "12345678"
    root.mkdir(parents=True)
    source = str(root / "expdata_table.csv")

    existing_df = create_empty_tracking_store()
    pending_df = create_empty_tracking_store()

    assert has_existing_step3_for_source(existing_df, pending_df, source) is False

    existing_df = pd.concat(
        [existing_df, _step_row(3, root, "12345678", "clean_expdata_table.csv", source=source)],
        ignore_index=True,
    )
    assert has_existing_step3_for_source(existing_df, pending_df, source) is True

    existing_df = create_empty_tracking_store()
    pending_df = pd.concat(
        [pending_df, _step_row(3, root, "12345678", "clean_expdata_table.csv", source=source)],
        ignore_index=True,
    )
    assert has_existing_step3_for_source(existing_df, pending_df, source) is True
