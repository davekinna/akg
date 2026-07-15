import importlib
import os
from types import SimpleNamespace

import pandas as pd


def _load_processing_module():
    os.environ.setdefault("ENTREZ_API_KEY", "test-key")
    module = importlib.import_module("processing")
    return importlib.reload(module)


def test_parse_csv_bool_variants():
    processing = _load_processing_module()

    truthy_values = [True, 1, "1", "true", "TRUE", " yes ", "Y", "t"]
    falsy_values = [False, 0, "0", "false", "FALSE", " no ", "N", "", None, "random"]

    for value in truthy_values:
        assert processing.parse_csv_bool(value) is True

    for value in falsy_values:
        assert processing.parse_csv_bool(value) is False


def test_download_candidate_filter_skips_tried_pmids():
    processing = _load_processing_module()

    df = pd.DataFrame(
        {
            "pmid": [11111111, 22222222, 33333333, 44444444],
            "download tried": ["True", "false", 1, 0],
        }
    )

    df["download tried"] = df["download tried"].map(processing.parse_csv_bool)
    download_df = df[~df["download tried"]]

    assert sorted(download_df["pmid"].tolist()) == [22222222, 44444444]


def test_read_existing_pmids_from_metadata_file(tmp_path):
    processing = _load_processing_module()

    metadata_file = tmp_path / "asd_article_metadata.csv"
    pd.DataFrame(
        {
            "pmid": [11111111, 22222222, None],
            "title": ["A", "B", "C"],
        }
    ).to_csv(metadata_file, index=False)

    known = processing.read_existing_pmids(str(metadata_file))

    assert known == {"11111111", "22222222"}


def test_get_metadata_appends_without_overwriting_existing_rows(tmp_path, monkeypatch):
    processing = _load_processing_module()

    metadata_file = tmp_path / "asd_article_metadata.csv"
    pd.DataFrame(
        {
            "pmid": [11111111],
            "title": ["Existing title"],
            "year": [2020],
            "journal": ["Existing Journal"],
            "doi": ["10.0000/existing"],
            "abstract": ["Existing abstract"],
            "exclude": [True],
            "exclude reason": ["manual"],
            "download tried": [True],
        }
    ).to_csv(metadata_file, index=False)

    class _FakeFetcher:
        def article_by_pmid(self, pmid):
            return SimpleNamespace(
                title=f"Title {pmid}",
                year=2024,
                journal="Test Journal",
                abstract=f"Abstract {pmid}",
            )

    monkeypatch.setattr(processing, "PubMedFetcher", _FakeFetcher)
    monkeypatch.setattr(processing.time, "sleep", lambda *_: None)

    processing.get_metadata([22222222], ["10.0000/new"], str(metadata_file))

    merged = pd.read_csv(metadata_file)
    assert sorted(merged["pmid"].astype(int).tolist()) == [11111111, 22222222]

    existing_row = merged[merged["pmid"].astype(int) == 11111111].iloc[0]
    assert processing.parse_csv_bool(existing_row["download tried"]) is True
    assert processing.parse_csv_bool(existing_row["exclude"]) is True
    assert existing_row["exclude reason"] == "manual"
