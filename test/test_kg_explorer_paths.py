from pathlib import Path
import json

from kg_explorer import KGExplorerWindow, prefer_hdt_graph_path, resolve_default_metadata_path, resolve_graph_arg, resolve_query_dir
from kg_services import GraphDataService


def test_resolve_query_dir_defaults_to_input_query(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    resolved = resolve_query_dir(str(input_dir), "")
    assert resolved == str(input_dir / "query")


def test_resolve_query_dir_relative_under_input(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    resolved = resolve_query_dir(str(input_dir), "my_queries")
    assert resolved == str(input_dir / "my_queries")


def test_resolve_query_dir_absolute_passthrough(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    absolute_query = tmp_path / "abs_queries"
    absolute_query.mkdir(parents=True, exist_ok=True)

    resolved = resolve_query_dir(str(input_dir), str(absolute_query))
    assert resolved == str(absolute_query)


def test_resolve_graph_arg_prefers_existing_graph_under_input(tmp_path: Path):
    input_dir = tmp_path / "input"
    graph_dir = input_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    graph_file = graph_dir / "combined.nt"
    graph_file.write_text("", encoding="utf-8")

    resolved = resolve_graph_arg(str(input_dir), "combined.nt")
    assert resolved == str(graph_file)


def test_resolve_graph_arg_relative_fallback_when_missing(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    resolved = resolve_graph_arg(str(input_dir), "missing.nt")
    assert resolved == "missing.nt"


def test_resolve_graph_arg_absolute_passthrough(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    abs_graph = tmp_path / "combined.nt"
    abs_graph.write_text("", encoding="utf-8")

    resolved = resolve_graph_arg(str(input_dir), str(abs_graph))
    assert resolved == str(abs_graph)


def test_resolve_graph_arg_prefers_existing_hdt_graph_under_input(tmp_path: Path):
    input_dir = tmp_path / "input"
    graph_dir = input_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    graph_file = graph_dir / "combined.hdt"
    graph_file.write_text("", encoding="utf-8")

    resolved = resolve_graph_arg(str(input_dir), "combined.hdt")
    assert resolved == str(graph_file)


def test_resolve_graph_arg_prefers_hdt_when_nt_requested(tmp_path: Path):
    input_dir = tmp_path / "input"
    graph_dir = input_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    nt_file = graph_dir / "combined.nt"
    hdt_file = graph_dir / "combined.hdt"
    nt_file.write_text("", encoding="utf-8")
    hdt_file.write_text("", encoding="utf-8")

    resolved = resolve_graph_arg(str(input_dir), "combined.nt")
    assert resolved == str(nt_file)


def test_prefer_hdt_graph_path_passthrough_when_no_hdt(tmp_path: Path):
    nt_file = tmp_path / "combined.nt"
    nt_file.write_text("", encoding="utf-8")

    assert prefer_hdt_graph_path(str(nt_file)) == str(nt_file)


def test_prefer_hdt_graph_path_passthrough_when_hdt_exists(tmp_path: Path):
    nt_file = tmp_path / "combined.nt"
    hdt_file = tmp_path / "combined.hdt"
    nt_file.write_text("", encoding="utf-8")
    hdt_file.write_text("", encoding="utf-8")

    assert prefer_hdt_graph_path(str(nt_file)) == str(nt_file)


def test_resolve_default_metadata_path_prefers_input_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_meta = input_dir / "asd_article_metadata.csv"
    input_meta.write_text("pmid,title\n1,One\n", encoding="utf-8")

    workspace_meta = tmp_path / "data" / "asd_article_metadata.csv"
    workspace_meta.parent.mkdir(parents=True, exist_ok=True)
    workspace_meta.write_text("pmid,title\n2,Two\n", encoding="utf-8")

    resolved = resolve_default_metadata_path(str(input_dir))
    assert resolved == str(input_meta)


def test_resolve_default_metadata_path_uses_workspace_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    workspace_meta = tmp_path / "data" / "asd_article_metadata.csv"
    workspace_meta.parent.mkdir(parents=True, exist_ok=True)
    workspace_meta.write_text("pmid,title\n2,Two\n", encoding="utf-8")

    resolved = resolve_default_metadata_path(str(input_dir))
    assert resolved == str(Path("data") / "asd_article_metadata.csv")


def test_resolve_default_metadata_path_returns_input_candidate_when_missing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    resolved = resolve_default_metadata_path(str(input_dir))
    assert resolved == str(input_dir / "asd_article_metadata.csv")


def test_load_binning_metadata_prefers_exact_sidecar_name(tmp_path: Path):
    window = KGExplorerWindow.__new__(KGExplorerWindow)
    window.binning_metadata = {}
    window.graph_service = GraphDataService()

    graph_path = tmp_path / "combined.nt"
    graph_path.write_text("", encoding="utf-8")
    sidecar = tmp_path / "combined.nt.metadata.json"
    sidecar.write_text(json.dumps({"data_min": 1.5, "data_max": 3.5}), encoding="utf-8")

    window._load_binning_metadata(str(graph_path))

    assert window.binning_metadata == {"data_min": 1.5, "data_max": 3.5}


def test_load_binning_metadata_falls_back_to_base_sidecar_name(tmp_path: Path):
    window = KGExplorerWindow.__new__(KGExplorerWindow)
    window.binning_metadata = {}
    window.graph_service = GraphDataService()

    graph_path = tmp_path / "combined.nt"
    graph_path.write_text("", encoding="utf-8")
    sidecar = tmp_path / "combined.metadata.json"
    sidecar.write_text(json.dumps({"data_min": -2.0, "data_max": 8.0}), encoding="utf-8")

    window._load_binning_metadata(str(graph_path))

    assert window.binning_metadata == {"data_min": -2.0, "data_max": 8.0}


def test_format_bin_metadata_includes_range_and_counts():
    window = KGExplorerWindow.__new__(KGExplorerWindow)
    window.binning_metadata = {
        "data_min": 0.0,
        "data_max": 10.0,
        "data_range": 10.0,
        "bin_count": 10,
        "binned_values_count": 42,
    }
    window.graph_service = GraphDataService()

    result = window._format_bin_metadata(["bin_3"])

    assert "Bin: bin_3" in result
    assert "Approximate value range: 3.0000 to 4.0000" in result
    assert "Global minimum: 0.0000" in result
    assert "Global maximum: 10.0000" in result
    assert "Binned numeric values: 42" in result


def test_make_table_item_sets_bin_tooltip():
    window = KGExplorerWindow.__new__(KGExplorerWindow)
    window.binning_metadata = {
        "data_min": 0.0,
        "data_max": 10.0,
        "data_range": 10.0,
        "bin_count": 10,
    }
    window.graph_service = GraphDataService()

    item = window._make_table_item("bin_7")

    assert item.text() == "bin_7"
    assert "Bin: bin_7" in item.toolTip()
