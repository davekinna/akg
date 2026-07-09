import importlib
import os

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
