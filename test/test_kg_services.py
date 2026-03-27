from pathlib import Path
import json
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace, URIRef

from kg_services import GraphDataService, MetadataService, NetworkModel, QueryService


def build_sample_graph() -> Graph:
    graph = Graph()
    ex = Namespace("http://example.org/")
    graph.add((URIRef(ex["s1"]), URIRef(ex["pred"]), Literal("alpha")))
    graph.add((URIRef(ex["s2"]), URIRef(ex["pred"]), Literal("beta")))
    return graph


def test_filter_triples_case_insensitive():
    triples = [
        ("http://example.org/S1", "http://example.org/pred", "Alpha"),
        ("http://example.org/S2", "http://example.org/other", "Beta"),
    ]

    filtered = GraphDataService.filter_triples(
        triples,
        subject_filter="s1",
        predicate_filter="PRED",
        object_filter="alp",
    )

    assert len(filtered) == 1
    assert filtered[0][0].endswith("S1")


def test_triples_to_rows_accepts_hdt_like_graph():
    class FakeHDTGraph:
        supports_sparql = False

        def iter_string_triples(self):
            yield ("http://example.org/s1", "http://example.org/pred", "alpha")
            yield ("http://example.org/s2", "http://example.org/pred", "beta")

    rows = GraphDataService.triples_to_rows(FakeHDTGraph())

    assert rows == [
        ("http://example.org/s1", "http://example.org/pred", "alpha"),
        ("http://example.org/s2", "http://example.org/pred", "beta"),
    ]


def test_build_network_model_compacts_nodes_and_edges():
    service = GraphDataService()
    triples = [
        ("https://pubmed.ncbi.nlm.nih.gov/12345", "http://example.org/predicate/has_output", "http://example.org/node/alpha"),
        ("http://example.org/node/alpha", "http://example.org/predicate/related_to", "literal beta value"),
    ]

    model = service.build_network_model(triples, max_edges=10)

    assert isinstance(model, NetworkModel)
    assert model.total_edges == 2
    assert [edge.label for edge in model.edges] == ["has_output", "related_to"]
    assert {node.identifier for node in model.nodes} == {
        "https://pubmed.ncbi.nlm.nih.gov/12345",
        "http://example.org/node/alpha",
        "literal beta value",
    }

    pmid_node = next(node for node in model.nodes if node.pmid == "12345")
    literal_node = next(node for node in model.nodes if node.identifier == "literal beta value")

    assert pmid_node.label == "12345"
    assert literal_node.is_literal is True


def test_build_network_model_honors_edge_limit():
    service = GraphDataService()
    triples = [
        (f"http://example.org/s{index}", "http://example.org/predicate/edge", f"http://example.org/o{index}")
        for index in range(5)
    ]

    model = service.build_network_model(triples, max_edges=3)

    assert model.total_edges == 3
    assert len(model.edges) == 3
    assert len(model.nodes) == 6


def test_display_value_resolves_edam_label_and_caches():
    service = GraphDataService()
    payload = {
        "_embedded": {
            "terms": [
                {
                    "label": "P-value",
                }
            ]
        }
    }

    with patch("kg_services.urlopen") as mocked_urlopen:
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")

        first = service.display_value("http://edamontology.org/data_1669")
        second = service.display_value("http://edamontology.org/data_1669")

    assert first == "P-value"
    assert second == "P-value"
    assert mocked_urlopen.call_count == 1


def test_hgnc_id_extraction_handles_monarch_urls_and_plain_ids():
    service = GraphDataService()

    assert service.extract_hgnc_id("https://monarchinitiative.org/HGNC:16851") == "HGNC:16851"
    assert service.extract_hgnc_id("HGNC:5") == "HGNC:5"
    assert service.extract_hgnc_id("http://example.org/not-hgnc") == ""


def test_display_value_prefers_hgnc_symbol_when_available():
    service = GraphDataService()
    service._hgnc_mapping_loaded = True
    service._hgnc_to_symbol = {"HGNC:16851": "SULF2"}

    value = "https://monarchinitiative.org/HGNC:16851"
    assert service.display_value(value) == "SULF2"


def test_display_value_returns_original_for_non_edam():
    service = GraphDataService()
    value = "https://monarchinitiative.org/not-a-hgnc-node"
    assert service.display_value(value) == value


def test_query_render_prefers_placeholders():
    query_text = "SELECT * WHERE { VALUES ?pmid { pmid:{{PMID}} } }"
    rendered = QueryService.render_query(query_text, pmid="12345678")
    assert "pmid:12345678" in rendered


def test_query_render_fallback_replaces_first_pmid():
    query_text = "SELECT * WHERE { VALUES ?pmid { pmid:11111111 } }"
    rendered = QueryService.render_query(query_text, pmid="22222222")
    assert "pmid:22222222" in rendered
    assert "pmid:11111111" not in rendered


def test_query_service_run_query_returns_rows(tmp_path: Path):
    graph = build_sample_graph()
    query_dir = tmp_path / "query"
    query_dir.mkdir(parents=True, exist_ok=True)

    query_file = query_dir / "all_rows.rq"
    query_file.write_text(
        """
        SELECT ?s ?o
        WHERE {
            ?s <http://example.org/pred> ?o .
        }
        ORDER BY ?s
        """.strip(),
        encoding="utf-8",
    )

    service = QueryService(str(query_dir))
    result = service.run_query(graph, "all_rows.rq")

    assert result.headers == ["s", "o"]
    assert len(result.rows) == 2
    assert result.rows[0][1] == "alpha"
    assert result.rows[1][1] == "beta"


def test_query_service_rejects_hdt_graph(tmp_path: Path):
    class FakeHDTGraph(Graph):
        supports_sparql = False

    query_dir = tmp_path / "query"
    query_dir.mkdir(parents=True, exist_ok=True)

    query_file = query_dir / "all_rows.rq"
    query_file.write_text("SELECT * WHERE { ?s ?p ?o }", encoding="utf-8")

    service = QueryService(str(query_dir))

    try:
        service.run_query(FakeHDTGraph(), "all_rows.rq")
        assert False, "Expected run_query to reject HDT-backed graphs"
    except ValueError as exc:
        assert ".hdt" in str(exc)


def test_metadata_service_load_and_lookup(tmp_path: Path):
    metadata_file = tmp_path / "asd_article_metadata.csv"
    metadata_file.write_text(
        "pmid,title,journal\n12345,Paper One,Journal A\n67890,Paper Two,Journal B\n",
        encoding="utf-8",
    )

    service = MetadataService(str(metadata_file))
    service.load()

    first = service.get_by_pmid("12345")
    second = service.get_by_pmid("https://pubmed.ncbi.nlm.nih.gov/67890")

    assert first is not None
    assert first["title"] == "Paper One"
    assert second is not None
    assert second["journal"] == "Journal B"


def test_metadata_normalize_pmid_variants():
    assert MetadataService.normalize_pmid("12345.0") == "12345"
    assert MetadataService.normalize_pmid("pmid:99999") == "99999"
    assert MetadataService.normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/54321") == "54321"
    assert MetadataService.normalize_pmid("not-a-pmid") == ""


def test_metadata_extract_pmid_from_values_returns_first_match():
    values = [
        "http://example.org/gene/SULF2",
        "https://pubmed.ncbi.nlm.nih.gov/36323788",
        "https://pubmed.ncbi.nlm.nih.gov/99999999",
    ]
    assert MetadataService.extract_pmid_from_values(values) == "36323788"


def test_metadata_extract_pmid_from_values_returns_empty_when_none():
    values = ["http://example.org/no-pmid-here", "plain text"]
    assert MetadataService.extract_pmid_from_values(values) == ""


# ---------------------------------------------------------------------------
# GraphDataService — compact_resource_label
# ---------------------------------------------------------------------------

def test_compact_resource_label_strips_fragment():
    result = GraphDataService.compact_resource_label("http://example.org/ontology#SomeClass")
    assert result == "SomeClass"


def test_compact_resource_label_strips_path_segment():
    result = GraphDataService.compact_resource_label("http://example.org/node/alpha")
    assert result == "alpha"


def test_compact_resource_label_strips_quotes():
    result = GraphDataService.compact_resource_label('"hello world"')
    assert result == "hello world"


def test_compact_resource_label_truncates_long_values():
    long_value = "A" * 50
    result = GraphDataService.compact_resource_label(long_value, max_length=10)
    assert len(result) == 10
    assert result.endswith("...")


def test_compact_resource_label_blank_input():
    assert GraphDataService.compact_resource_label("") == "(blank)"


# ---------------------------------------------------------------------------
# GraphDataService — looks_like_literal
# ---------------------------------------------------------------------------

def test_looks_like_literal_identifies_uris_as_non_literal():
    assert GraphDataService.looks_like_literal("http://example.org/thing") is False
    assert GraphDataService.looks_like_literal("https://example.org/thing") is False
    assert GraphDataService.looks_like_literal("urn:some:id") is False
    assert GraphDataService.looks_like_literal("pmid:12345") is False


def test_looks_like_literal_identifies_plain_text():
    assert GraphDataService.looks_like_literal("just some text") is True
    assert GraphDataService.looks_like_literal("3.14") is True
    assert GraphDataService.looks_like_literal("") is True


# ---------------------------------------------------------------------------
# GraphDataService — load_binning_metadata
# ---------------------------------------------------------------------------

def test_load_binning_metadata_reads_primary_sidecar(tmp_path: Path):
    graph_path = str(tmp_path / "combined.nt")
    sidecar = tmp_path / "combined.nt.metadata.json"
    payload = {"data_min": 0.0, "data_max": 1.0, "bin_count": 10}
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    result = GraphDataService.load_binning_metadata(graph_path)
    assert result == payload


def test_load_binning_metadata_falls_back_to_stripped_extension(tmp_path: Path):
    graph_path = str(tmp_path / "combined.nt")
    sidecar = tmp_path / "combined.metadata.json"
    payload = {"data_min": 1.5, "data_max": 9.5, "bin_count": 5}
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    result = GraphDataService.load_binning_metadata(graph_path)
    assert result == payload


def test_load_binning_metadata_returns_empty_when_missing(tmp_path: Path):
    graph_path = str(tmp_path / "no_metadata.nt")
    result = GraphDataService.load_binning_metadata(graph_path)
    assert result == {}


def test_load_binning_metadata_returns_empty_on_corrupt_json(tmp_path: Path):
    graph_path = str(tmp_path / "combined.nt")
    sidecar = tmp_path / "combined.nt.metadata.json"
    sidecar.write_text("NOT VALID JSON{{{", encoding="utf-8")

    result = GraphDataService.load_binning_metadata(graph_path)
    assert result == {}


# ---------------------------------------------------------------------------
# GraphDataService — find_bin_index
# ---------------------------------------------------------------------------

def test_find_bin_index_finds_first_match():
    values = ["http://example.org/subject", "bin_7", "http://example.org/object"]
    assert GraphDataService.find_bin_index(values) == 7


def test_find_bin_index_returns_none_when_absent():
    values = ["http://example.org/subject", "literal text", "http://example.org/object"]
    assert GraphDataService.find_bin_index(values) is None


def test_find_bin_index_handles_bin_zero():
    assert GraphDataService.find_bin_index(["bin_0"]) == 0


def test_find_bin_index_does_not_match_partial_words():
    # "cabin_5" must not match — word boundary is required
    assert GraphDataService.find_bin_index(["cabin_5"]) is None


# ---------------------------------------------------------------------------
# GraphDataService — format_bin_description
# ---------------------------------------------------------------------------

SAMPLE_BINNING_META = {
    "data_min": 0.0,
    "data_max": 10.0,
    "data_range": 10.0,
    "bin_count": 10,
    "binned_values_count": 500,
}


def test_format_bin_description_correct_range_for_mid_bin():
    result = GraphDataService.format_bin_description(3, SAMPLE_BINNING_META)
    assert "bin_3" in result
    assert "3.0000 to 4.0000" in result
    assert "0.0000" in result   # global minimum
    assert "10.0000" in result  # global maximum
    assert "500" in result      # binned values count


def test_format_bin_description_last_bin_uses_data_max():
    result = GraphDataService.format_bin_description(9, SAMPLE_BINNING_META)
    # Upper bound of last bin should equal data_max exactly
    assert "9.0000 to 10.0000" in result


def test_format_bin_description_returns_empty_for_missing_min_max():
    incomplete = {"bin_count": 10}
    result = GraphDataService.format_bin_description(2, incomplete)
    assert result == ""


def test_format_bin_description_infers_range_when_absent():
    meta_no_range = {
        "data_min": 2.0,
        "data_max": 4.0,
        "bin_count": 2,
    }
    result = GraphDataService.format_bin_description(0, meta_no_range)
    # range = 4.0 - 2.0 = 2.0; bin_width = 1.0; bin 0 → 2.0000 to 3.0000
    assert "2.0000 to 3.0000" in result


# ---------------------------------------------------------------------------
# QueryService — list_query_files
# ---------------------------------------------------------------------------

def test_query_service_lists_only_rq_files(tmp_path: Path):
    query_dir = tmp_path / "query"
    query_dir.mkdir()
    (query_dir / "alpha.rq").write_text("SELECT * WHERE { ?s ?p ?o }", encoding="utf-8")
    (query_dir / "beta.rq").write_text("SELECT * WHERE { ?s ?p ?o }", encoding="utf-8")
    (query_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    service = QueryService(str(query_dir))
    files = service.list_query_files()

    assert files == ["alpha.rq", "beta.rq"]


def test_query_service_returns_empty_list_for_missing_dir(tmp_path: Path):
    service = QueryService(str(tmp_path / "nonexistent"))
    assert service.list_query_files() == []


# ---------------------------------------------------------------------------
# GraphDataService — UUID Resolution
# ---------------------------------------------------------------------------

def test_extract_uuid_finds_urn_uuid():
    result = GraphDataService._extract_uuid("urn:uuid:12345678-1234-5678-1234-567812345678")
    assert result == "12345678-1234-5678-1234-567812345678"


def test_extract_uuid_case_insensitive():
    result = GraphDataService._extract_uuid("URN:UUID:ABCD1234-ABCD-1234-ABCD-1234ABCD1234")
    assert result == "abcd1234-abcd-1234-abcd-1234abcd1234"


def test_extract_uuid_from_embedded_text():
    text = "Some prefix urn:uuid:aaaabbbb-cccc-dddd-eeee-ffff00001111 some suffix"
    result = GraphDataService._extract_uuid(text)
    assert result == "aaaabbbb-cccc-dddd-eeee-ffff00001111"


def test_extract_uuid_returns_none_when_absent():
    result = GraphDataService._extract_uuid("no uuid here")
    assert result is None


def test_load_uuid_maps_builds_reverse_map(tmp_path: Path):
    service = GraphDataService()
    
    # Create filename_uuid_map.json
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    map_file = graph_dir / "filename_uuid_map.json"
    payload = {
        "expdata_TableS6": "6fddc7d8-3251-4697-abd8-fca338308db7",
        "expdata_TableS7": "b2f05b9c-b864-4537-8ca4-77cdf00fcd73",
    }
    map_file.write_text(json.dumps(payload), encoding="utf-8")
    
    service.load_uuid_maps(str(tmp_path))
    
    # Verify reverse map
    assert service.resolve_uuid_to_filename("6fddc7d8-3251-4697-abd8-fca338308db7") == "expdata_TableS6"
    assert service.resolve_uuid_to_filename("b2f05b9c-b864-4537-8ca4-77cdf00fcd73") == "expdata_TableS7"


def test_load_uuid_maps_idempotent(tmp_path: Path):
    service = GraphDataService()
    
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    map_file = graph_dir / "filename_uuid_map.json"
    map_file.write_text(json.dumps({"file1": "uuid1"}), encoding="utf-8")
    
    # Load twice
    service.load_uuid_maps(str(tmp_path))
    service.load_uuid_maps(str(tmp_path))
    
    # Should not error
    assert service.resolve_uuid_to_filename("uuid1") == "file1"


def test_resolve_uuid_to_filename_returns_none_for_unknown(tmp_path: Path):
    service = GraphDataService()
    service.load_uuid_maps(str(tmp_path))  # Empty dir
    
    result = service.resolve_uuid_to_filename("unknown-uuid")
    assert result is None


def test_resolve_uuid_to_row_context_returns_none_for_missing():
    service = GraphDataService()
    result = service.resolve_uuid_to_row_context("urn:uuid:unknown", "/nonexistent/path.nt")
    assert result is None


def test_resolve_uuid_to_row_context_supports_dot_sidecar_suffix(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined.nt"
    sidecar = graph_dir / "combined.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:12345678-1234-5678-9abc-1234567890ab": "row 42"}),
        encoding="utf-8",
    )

    result = service.resolve_uuid_to_row_context("urn:uuid:12345678-1234-5678-9abc-1234567890ab", str(graph_path))

    assert result is not None
    assert result["filename"] == "combined.nt"
    assert result["row_label"] == "row 42"
    assert result["row_index"] == "42"


def test_resolve_uuid_to_row_context_searches_pmid_supp_data_for_combined_graph(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined_36323788.nt"

    pmid_dir = tmp_path / "supp_data" / "36323788"
    pmid_dir.mkdir(parents=True)
    sidecar = pmid_dir / "graph_clean_expdata_cluster_markers.csv.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:12345678-1234-5678-9abc-1234567890ab": "row 17"}),
        encoding="utf-8",
    )

    result = service.resolve_uuid_to_row_context(
        "urn:uuid:12345678-1234-5678-9abc-1234567890ab",
        str(graph_path),
        input_dir=str(tmp_path),
    )

    assert result is not None
    assert result["filename"] == "graph_clean_expdata_cluster_markers.csv.nt"
    assert result["display_filename"] == "expdata_cluster_markers"
    assert result["row_label"] == "row 17"
    assert result["row_index"] == "17"


def test_resolve_uuid_to_row_context_prefers_graph_pmid_folder_for_combined_graph(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined_36323788.nt"

    pmid_graph_dir = graph_dir / "36323788"
    pmid_graph_dir.mkdir(parents=True)
    sidecar = pmid_graph_dir / "graph_clean_expdata_TableS6.csv.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:12345678-1234-5678-9abc-1234567890ab": "row 42"}),
        encoding="utf-8",
    )

    result = service.resolve_uuid_to_row_context(
        "urn:uuid:12345678-1234-5678-9abc-1234567890ab",
        str(graph_path),
        input_dir=str(tmp_path),
    )

    assert result is not None
    assert result["filename"] == "graph_clean_expdata_TableS6.csv.nt"
    assert result["display_filename"] == "expdata_TableS6"
    assert result["row_label"] == "row 42"
    assert result["row_index"] == "42"


def test_resolve_uuid_to_row_context_prefers_exact_combined_sidecar(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined_multi.nt"
    sidecar = graph_dir / "combined_multi.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps(
            {
                "urn:uuid:12345678-1234-5678-9abc-1234567890ab": {
                    "filename": "graph_clean_expdata_TableS6.csv.nt",
                    "row_label": "row 42",
                    "row_index": "42",
                }
            }
        ),
        encoding="utf-8",
    )

    result = service.resolve_uuid_to_row_context(
        "urn:uuid:12345678-1234-5678-9abc-1234567890ab",
        str(graph_path),
        input_dir=str(tmp_path),
    )

    assert result is not None
    assert result["filename"] == "graph_clean_expdata_TableS6.csv.nt"
    assert result["display_filename"] == "expdata_TableS6"
    assert result["row_label"] == "row 42"
    assert result["row_index"] == "42"


def test_resolve_uuid_to_row_context_binned_graph_uses_unbinned_combined_sidecar(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined_multi_binned.nt"
    sidecar = graph_dir / "combined_multi.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps(
            {
                "urn:uuid:12345678-1234-5678-9abc-1234567890ab": {
                    "filename": "graph_clean_expdata_TableS6.csv.nt",
                    "row_label": "row 42",
                    "row_index": "42",
                }
            }
        ),
        encoding="utf-8",
    )

    result = service.resolve_uuid_to_row_context(
        "urn:uuid:12345678-1234-5678-9abc-1234567890ab",
        str(graph_path),
        input_dir=str(tmp_path),
    )

    assert result is not None
    assert result["display_filename"] == "expdata_TableS6"
    assert result["row_label"] == "row 42"


def test_enhance_uuid_values_replaces_file_level_uuids(tmp_path: Path):
    service = GraphDataService()
    
    # Set up filename map
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    map_file = graph_dir / "filename_uuid_map.json"
    map_file.write_text(
        json.dumps({"expdata_TableS6": "6fddc7d8-3251-4697-abd8-fca338308db7"}),
        encoding="utf-8"
    )
    
    values = ["urn:uuid:6fddc7d8-3251-4697-abd8-fca338308db7", "other_text"]
    enhanced = service.enhance_uuid_values(values, input_dir=str(tmp_path))
    
    assert "6fddc7d8-3251-4697-abd8-fca338308db7" in enhanced[0]
    assert "expdata_TableS6" in enhanced[0]
    assert enhanced[1] == "other_text"


def test_enhance_uuid_values_falls_back_to_graph_path_for_uuid_map(tmp_path: Path):
    service = GraphDataService()

    actual_input = tmp_path / "actual"
    graph_dir = actual_input / "graph"
    graph_dir.mkdir(parents=True)
    map_file = graph_dir / "filename_uuid_map.json"
    map_file.write_text(
        json.dumps({"expdata_TableS6": "6fddc7d8-3251-4697-abd8-fca338308db7"}),
        encoding="utf-8",
    )

    values = ["urn:uuid:6fddc7d8-3251-4697-abd8-fca338308db7"]
    enhanced = service.enhance_uuid_values(
        values,
        input_dir=str(tmp_path / "missing"),
        graph_path=str(graph_dir / "combined.nt"),
    )

    assert "expdata_TableS6" in enhanced[0]


def test_enhance_uuid_values_uses_clean_row_display_name(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined_36323788.nt"
    pmid_graph_dir = graph_dir / "36323788"
    pmid_graph_dir.mkdir(parents=True)
    sidecar = pmid_graph_dir / "graph_clean_expdata_TableS6.csv.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:12345678-1234-5678-9abc-1234567890ab": "row 42"}),
        encoding="utf-8",
    )

    enhanced = service.enhance_uuid_values(
        ["urn:uuid:12345678-1234-5678-9abc-1234567890ab"],
        input_dir=str(tmp_path),
        graph_path=str(graph_path),
    )

    assert enhanced == ["urn:uuid:12345678-1234-5678-9abc-1234567890ab [from expdata_TableS6, row 42]"]


def test_enhance_uuid_values_preserves_non_uuid_values():
    service = GraphDataService()

    values = ["http://example.org/gene", "literal text", "pmid:12345"]
    enhanced = service.enhance_uuid_values(values)

    assert enhanced == values


def test_enhance_uuid_values_handles_mixed_uuids_and_non_uuids(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    map_file = graph_dir / "filename_uuid_map.json"
    map_file.write_text(
        json.dumps({"file1": "aaa-aaa-aaa"}),
        encoding="utf-8"
    )

    values = [
        "urn:uuid:aaa-aaa-aaa",
        "http://example.org/stay-same",
        "literal",
    ]
    enhanced = service.enhance_uuid_values(values, input_dir=str(tmp_path))

    assert "[file1]" in enhanced[0]
    assert enhanced[1] == "http://example.org/stay-same"
    assert enhanced[2] == "literal"


def test_enhance_uuid_values_handles_unknown_uuids():
    """Unknown UUIDs should be preserved as-is."""
    service = GraphDataService()

    values = ["urn:uuid:unknown-uuid-here"]
    enhanced = service.enhance_uuid_values(values, input_dir="/nonexistent")

    # Should preserve the original since it's not in any map
    assert "unknown-uuid-here" in enhanced[0]


# ---------------------------------------------------------------------------
# GraphDataService — display_value_with_uuid_context
# ---------------------------------------------------------------------------

def test_display_value_with_uuid_context_resolves_filename_uuid(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    map_file = graph_dir / "filename_uuid_map.json"
    map_file.write_text(
        json.dumps({"expdata_TableS6": "6fddc7d8-3251-4697-abd8-fca338308db7"}),
        encoding="utf-8",
    )

    result = service.display_value_with_uuid_context(
        "urn:uuid:6fddc7d8-3251-4697-abd8-fca338308db7",
        input_dir=str(tmp_path),
    )

    assert result == "expdata_TableS6"


def test_display_value_with_uuid_context_resolves_row_uuid(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined.nt"
    sidecar = graph_dir / "combined.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:aaaabbbb-cccc-dddd-eeee-ffff00001111": "row 7"}),
        encoding="utf-8",
    )

    result = service.display_value_with_uuid_context(
        "urn:uuid:aaaabbbb-cccc-dddd-eeee-ffff00001111",
        graph_path=str(graph_path),
        resolve_row_context=True,
    )

    assert result == "combined row 7"


def test_display_value_with_uuid_context_skips_row_context_when_disabled(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined.nt"
    sidecar = graph_dir / "combined.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:aaaabbbb-cccc-dddd-eeee-ffff00001111": "row 7"}),
        encoding="utf-8",
    )

    result = service.display_value_with_uuid_context(
        "urn:uuid:aaaabbbb-cccc-dddd-eeee-ffff00001111",
        graph_path=str(graph_path),
        resolve_row_context=False,
    )

    # Should return raw since row context is disabled and filename map is absent
    assert "urn:uuid:aaaabbbb-cccc-dddd-eeee-ffff00001111" in result


def test_display_value_with_uuid_context_returns_non_uuid_via_display_value():
    service = GraphDataService()
    service._hgnc_mapping_loaded = True
    service._hgnc_to_symbol = {"HGNC:99": "MYGENE"}

    result = service.display_value_with_uuid_context(
        "https://monarchinitiative.org/HGNC:99",
    )

    assert result == "MYGENE"


def test_display_value_with_uuid_context_caches_result(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    map_file = graph_dir / "filename_uuid_map.json"
    map_file.write_text(
        json.dumps({"expdata_TableS6": "6fddc7d8-3251-4697-abd8-fca338308db7"}),
        encoding="utf-8",
    )

    first = service.display_value_with_uuid_context(
        "urn:uuid:6fddc7d8-3251-4697-abd8-fca338308db7",
        input_dir=str(tmp_path),
    )
    # Corrupt the in-memory map to confirm cache is used on second call
    service._filename_uuid_map = {}

    second = service.display_value_with_uuid_context(
        "urn:uuid:6fddc7d8-3251-4697-abd8-fca338308db7",
        input_dir=str(tmp_path),
    )

    assert first == "expdata_TableS6"
    assert second == "expdata_TableS6"


# ---------------------------------------------------------------------------
# GraphDataService — _load_row_sidecar (caching behaviour)
# ---------------------------------------------------------------------------

def test_load_row_sidecar_builds_uuid_context_map(tmp_path: Path):
    service = GraphDataService()

    sidecar = tmp_path / "combined.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:12345678-1234-5678-9abc-1234567890ab": "row 3"}),
        encoding="utf-8",
    )

    contexts = service._load_row_sidecar(str(sidecar))

    assert "12345678-1234-5678-9abc-1234567890ab" in contexts
    assert contexts["12345678-1234-5678-9abc-1234567890ab"]["row_label"] == "row 3"


def test_load_row_sidecar_caches_on_second_call(tmp_path: Path):
    service = GraphDataService()

    sidecar = tmp_path / "combined.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:aabbccdd-0000-0000-0000-000000000001": "row 1"}),
        encoding="utf-8",
    )

    first = service._load_row_sidecar(str(sidecar))
    # Remove file to confirm second call uses cache
    sidecar.unlink()
    second = service._load_row_sidecar(str(sidecar))

    assert first is second


def test_load_row_sidecar_returns_empty_for_missing_file(tmp_path: Path):
    service = GraphDataService()
    result = service._load_row_sidecar(str(tmp_path / "nonexistent.json"))
    assert result == {}


def test_load_row_sidecar_returns_empty_for_corrupt_json(tmp_path: Path):
    service = GraphDataService()
    bad = tmp_path / "bad.json"
    bad.write_text("{{NOT JSON}}", encoding="utf-8")
    result = service._load_row_sidecar(str(bad))
    assert result == {}


# ---------------------------------------------------------------------------
# GraphDataService — prepopulate_row_context_cache
# ---------------------------------------------------------------------------

def test_prepopulate_row_context_cache_loads_sidecar_files(tmp_path: Path):
    service = GraphDataService()

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    graph_path = graph_dir / "combined_36323788.nt"

    sidecar = graph_dir / "combined_36323788.nt.row_uri_labels.json"
    sidecar.write_text(
        json.dumps({"urn:uuid:aabbccdd-0000-0000-0000-000000000001": "row 5"}),
        encoding="utf-8",
    )

    count = service.prepopulate_row_context_cache(
        graph_path=str(graph_path),
        input_dir=str(tmp_path),
    )

    assert count >= 1
    # Subsequent resolve should use in-memory cache, not disk
    sidecar.unlink()
    result = service.resolve_uuid_to_row_context(
        "urn:uuid:aabbccdd-0000-0000-0000-000000000001",
        str(graph_path),
    )
    assert result is not None
    assert result["row_label"] == "row 5"


def test_prepopulate_returns_zero_when_no_sidecars(tmp_path: Path):
    service = GraphDataService()
    graph_path = tmp_path / "graph" / "combined.nt"
    (tmp_path / "graph").mkdir()

    count = service.prepopulate_row_context_cache(
        graph_path=str(graph_path),
        input_dir=str(tmp_path),
    )

    assert count == 0


# ---------------------------------------------------------------------------
# Integration Tests - GUI + Services
# ---------------------------------------------------------------------------

def test_uuid_resolution_integration_with_display_values(tmp_path: Path):
    """
    Integration test: UUID resolution + display value formatting.
    Simulates what happens when a GUI row is selected with UUIDs.
    """
    service = GraphDataService()
    
    # Set up filename map
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    map_file = graph_dir / "filename_uuid_map.json"
    map_file.write_text(
        json.dumps({
            "expdata_TableS6": "6fddc7d8-3251-4697-abd8-fca338308db7",
            "expdata_TableS7": "b2f05b9c-b864-4537-8ca4-77cdf00fcd73",
        }),
        encoding="utf-8"
    )
    
    # Simulate values from a selected table row (mix of identifiers and UUIDs)
    row_values = [
        "urn:uuid:6fddc7d8-3251-4697-abd8-fca338308db7",
        "https://monarchinitiative.org/HGNC:5467",
        "3.14159",
    ]
    
    # Enhance with UUID resolution (what the GUI does before display)
    enhanced = service.enhance_uuid_values(row_values, input_dir=str(tmp_path))
    
    # Verify result
    assert len(enhanced) == 3
    assert "[expdata_TableS6]" in enhanced[0]  # UUID resolved to filename
    assert "https://monarchinitiative.org/HGNC:5467" == enhanced[1]  # Non-UUID unchanged
    assert "3.14159" == enhanced[2]  # Non-UUID unchanged
