from pathlib import Path
import os
import json

from combine_graphs import build_combined_row_context, resolve_pmid_graph_input_dirs
from create_rdf_triples import resolve_per_file_graph_output_path


def test_resolve_per_file_graph_output_path_uses_graph_pmid_subdir(tmp_path: Path):
    graph_folder = tmp_path / "graph"

    graph_path = resolve_per_file_graph_output_path(str(graph_folder), "36323788", "clean_expdata_TableS6.csv")

    assert os.path.normpath(graph_path) == os.path.normpath(
        str(graph_folder / "36323788" / "graph_clean_expdata_TableS6.csv.nt")
    )
    assert (graph_folder / "36323788").is_dir()


def test_resolve_pmid_graph_input_dirs_prefers_graph_subdir_before_supp_data(tmp_path: Path):
    result = resolve_pmid_graph_input_dirs(str(tmp_path), "36323788")

    assert result == [
        str(tmp_path / "graph" / "36323788"),
        str(tmp_path / "supp_data" / "36323788"),
    ]


def test_build_combined_row_context_merges_per_file_sidecars(tmp_path: Path):
    file_one = tmp_path / "graph_1.nt"
    file_two = tmp_path / "graph_2.nt"
    file_one.write_text("", encoding="utf-8")
    file_two.write_text("", encoding="utf-8")

    (tmp_path / "graph_1.nt.row_uri_labels.json").write_text(
        json.dumps({"urn:uuid:aaa": "row 7"}),
        encoding="utf-8",
    )
    (tmp_path / "graph_2.nt.row_uri_labels.json").write_text(
        json.dumps({"urn:uuid:bbb": "row 11"}),
        encoding="utf-8",
    )

    result = build_combined_row_context([str(file_one), str(file_two)])

    assert result == {
        "urn:uuid:aaa": {
            "filename": "graph_1.nt",
            "row_label": "row 7",
            "row_index": "7",
        },
        "urn:uuid:bbb": {
            "filename": "graph_2.nt",
            "row_label": "row 11",
            "row_index": "11",
        },
    }