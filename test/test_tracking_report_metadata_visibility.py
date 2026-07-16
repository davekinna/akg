import pandas as pd
from tracking_report import build_pending_downstream_pmids, write_pending_downstream_csv

from pmid_utils import (
    compute_pmid_visibility,
    extract_tracking_pmids,
    load_metadata_pmids,
    normalize_pmid,
)


def test_normalize_pmid_removes_float_suffix():
    assert normalize_pmid("12345678.0") == "12345678"
    assert normalize_pmid(12345678) == "12345678"
    assert normalize_pmid("") == ""


def test_extract_tracking_pmids_supports_step_filter():
    tdf = pd.DataFrame(
        {
            "step": [0, 1, 2, 0],
            "pmid": [11111111, "22222222.0", 33333333, ""],
        }
    )

    all_pmids = extract_tracking_pmids(tdf)
    step0_pmids = extract_tracking_pmids(tdf, step=0)

    assert all_pmids == {"11111111", "22222222", "33333333"}
    assert step0_pmids == {"11111111"}


def test_load_metadata_pmids_excludes_rows_marked_excluded(tmp_path):
    metadata_file = tmp_path / "asd_article_metadata.csv"
    pd.DataFrame(
        {
            "pmid": [11111111, 22222222, 33333333, ""],
            "exclude": [False, "TRUE", "0", True],
        }
    ).to_csv(metadata_file, index=False)

    pmids, error = load_metadata_pmids(str(metadata_file))

    assert error == ""
    assert pmids == {"11111111", "33333333"}


def test_compute_pmid_visibility_sets():
    metadata_pmids = {"11111111", "22222222", "33333333"}
    tracking_pmids = {"22222222", "33333333", "44444444"}

    visibility = compute_pmid_visibility(metadata_pmids, tracking_pmids)

    assert visibility["in_both"] == {"22222222", "33333333"}
    assert visibility["metadata_only"] == {"11111111"}
    assert visibility["tracking_only"] == {"44444444"}


def test_build_pending_downstream_pmids_sorted():
    visibility = {
        "metadata_only": {"33333333", "11111111", "22222222"},
        "in_both": set(),
        "tracking_only": set(),
    }

    pending = build_pending_downstream_pmids(visibility)

    assert pending == ["11111111", "22222222", "33333333"]


def test_write_pending_downstream_csv(tmp_path):
    output_file = tmp_path / "pending_pmids.csv"
    pending = ["11111111", "33333333"]

    write_pending_downstream_csv(str(output_file), pending)

    df = pd.read_csv(output_file)
    assert df.columns.tolist() == ["pmid", "status"]
    assert df["pmid"].astype(str).tolist() == pending
    assert set(df["status"].tolist()) == {"pending_downstream"}
