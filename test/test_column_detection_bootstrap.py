import os

import pandas as pd

from akg import detect_tracking_columns
from data_split import process_dataframe


def test_detect_tracking_columns_finds_expected_headers():
    headers = ["Gene Symbol", "adj.P.Val", "avg_logFC", "other"]

    gene, pval, lfc = detect_tracking_columns(headers)

    assert gene == "Gene Symbol"
    assert pval == "adj.P.Val"
    assert lfc == "avg_logFC"


def test_detect_tracking_columns_avoids_gene_substring_false_positive():
    headers = ["my_gene_metric", "random", "value"]

    gene, pval, lfc = detect_tracking_columns(headers)

    assert gene == ""
    assert pval == ""
    assert lfc == ""


def test_detect_tracking_columns_broader_gene_and_pval_matching():
    headers = ["human_gene_name", "adjusted_pvalue_score", "avg_logFC"]

    gene, pval, lfc = detect_tracking_columns(headers)

    assert gene == "human_gene_name"
    assert pval == "adjusted_pvalue_score"
    assert lfc == "avg_logFC"


def test_data_split_process_dataframe_populates_step1_column_hints(tmp_path):
    pmid_dir = tmp_path / "12345678"
    pmid_dir.mkdir(parents=True, exist_ok=True)

    source_file = pmid_dir / "source.xlsx"
    source_file.write_text("placeholder", encoding="utf-8")

    df = pd.DataFrame(
        {
            "Gene Symbol": ["TP53", "EGFR"],
            "adj.P.Val": [0.01, 0.02],
            "avg_logFC": [1.2, -0.5],
        }
    )

    tracking_rows = process_dataframe(
        df,
        sheet_name="Sheet 1",
        output_dir=str(pmid_dir),
        file_path=str(source_file),
        input_delimiter=",",
    )

    assert len(tracking_rows) == 1
    row = tracking_rows.iloc[0]

    assert int(row["step"]) == 1
    assert row["gene"] == "Gene Symbol"
    assert row["pval"] == "adj.P.Val"
    assert row["lfc"] == "avg_logFC"

    output_filename = str(row["file"])
    assert output_filename.startswith("split_")
    assert output_filename.endswith(".csv")
    assert os.path.exists(pmid_dir / output_filename)
