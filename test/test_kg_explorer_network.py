from kg_explorer import KGExplorerWindow
from kg_services import NetworkNode, GraphDataService


def test_compute_network_positions_returns_entry_per_node():
    nodes = [
        NetworkNode(identifier="a", label="a", degree=1),
        NetworkNode(identifier="b", label="b", degree=2),
        NetworkNode(identifier="c", label="c", degree=3),
    ]

    positions = KGExplorerWindow._compute_network_positions(nodes)

    assert set(positions.keys()) == {"a", "b", "c"}


def test_network_node_color_categories():
    pmid_node = NetworkNode(identifier="https://pubmed.ncbi.nlm.nih.gov/1", label="1", degree=1, pmid="1")
    literal_node = NetworkNode(identifier="bin_3", label="bin_3", degree=1, is_literal=True)
    uri_node = NetworkNode(identifier="https://example.org/node", label="node", degree=1)

    assert KGExplorerWindow._network_node_color(pmid_node).name() == "#74b9ff"
    assert KGExplorerWindow._network_node_color(literal_node).name() == "#f7c59f"
    assert KGExplorerWindow._network_node_color(uri_node).name() == "#7bd389"


def test_network_node_tooltip_includes_bin_metadata_when_available():
    window = KGExplorerWindow.__new__(KGExplorerWindow)
    window.binning_metadata = {
        "data_min": 0.0,
        "data_max": 10.0,
        "data_range": 10.0,
        "bin_count": 10,
        "binned_values_count": 100,
    }
    window.graph_service = GraphDataService()

    node = NetworkNode(identifier="bin_3", label="bin_3", degree=4, is_literal=True)
    tooltip = window._network_node_tooltip(node)

    assert "Identifier: bin_3" in tooltip
    assert "Degree: 4" in tooltip
    assert "Bin: bin_3" in tooltip
    assert "Approximate value range: 3.0000 to 4.0000" in tooltip
