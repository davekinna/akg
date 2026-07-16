import json

import create_rdf_triples as crt


class _StubFilenameUUIDMap:
    def get_uuid(self, _filename: str) -> str:
        return "00000000-0000-0000-0000-000000000001"


def test_process_regular_csv_handles_fully_quoted_rows(tmp_path):
    csv_file = tmp_path / "clean_expdata_demo.csv"
    csv_file.write_text(
        "\n".join(
            [
                '"gene,pvalue,logfc"',
                '"ABC1,0.010,1.20"',
                '"DEF2,0.020,-0.70"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    graph_file = tmp_path / "graph_clean_expdata_demo.csv.nt"

    crt.g_filename_uuid_map = _StubFilenameUUIDMap()
    graph = crt.create_base_graph()

    matched, unmatched = crt.process_regular_csv(
        str(csv_file),
        0,
        0,
        graph,
        str(graph_file),
        gene_name="gene",
        pval_name="pvalue",
        lfc_name="logfc",
    )

    assert graph_file.exists()
    assert len(graph) > 2
    assert matched + unmatched == 2

    sidecar_path = tmp_path / "graph_clean_expdata_demo.csv.nt.row_uri_labels.json"
    assert sidecar_path.exists()

    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert sorted(payload.values()) == ["row 0", "row 1"]


def test_process_regular_csv_allows_missing_graph_file(tmp_path):
    csv_file = tmp_path / "clean_expdata_demo.csv"
    csv_file.write_text(
        "\n".join(
            [
                '"gene,pvalue,logfc"',
                '"ABC1,0.010,1.20"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    crt.g_filename_uuid_map = _StubFilenameUUIDMap()
    graph = crt.create_base_graph()

    matched, unmatched = crt.process_regular_csv(
        str(csv_file),
        0,
        0,
        graph,
        None,
        gene_name="gene",
        pval_name="pvalue",
        lfc_name="logfc",
    )

    assert len(graph) > 0
    assert matched + unmatched == 1
    # No sidecar should be written when no graph_file is provided.
    assert not (tmp_path / "clean_expdata_demo.csv.row_uri_labels.json").exists()
