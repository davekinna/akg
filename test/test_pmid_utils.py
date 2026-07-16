import pandas as pd

from pmid_utils import (
    load_article_metadata_by_pmid,
    load_metadata_pmids,
    normalize_pmid,
    parse_bool,
)


def test_normalize_and_parse_bool_shared_rules():
    assert normalize_pmid("12345678.0") == "12345678"
    assert normalize_pmid(12345678) == "12345678"
    assert parse_bool("TRUE") is True
    assert parse_bool("0") is False


def test_load_metadata_pmids_uses_exclude_filter(tmp_path):
    metadata_file = tmp_path / "asd_article_metadata.csv"
    pd.DataFrame(
        {
            "pmid": [11111111, "22222222.0", "", 33333333],
            "exclude": [False, "yes", False, "0"],
        }
    ).to_csv(metadata_file, index=False)

    pmids, error = load_metadata_pmids(str(metadata_file))

    assert error == ""
    assert pmids == {"11111111", "33333333"}


def test_load_article_metadata_by_pmid_returns_lookup(tmp_path):
    metadata_file = tmp_path / "asd_article_metadata.csv"
    pd.DataFrame(
        {
            "pmid": [11111111, "22222222.0"],
            "title": ["A", "B"],
            "exclude": [False, True],
        }
    ).to_csv(metadata_file, index=False)

    lookup, error = load_article_metadata_by_pmid(str(metadata_file))

    assert error == ""
    assert lookup["11111111"]["title"] == "A"
    assert lookup["22222222"]["title"] == "B"
