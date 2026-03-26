"""Shared services for loading and interrogating AKG RDF graphs."""

from __future__ import annotations

import os
import re
import csv
import io
import json
from itertools import islice
from collections import Counter
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from akg import load_graph

PMID_PATTERN = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|\bpmid:)(\d{5,12})", re.IGNORECASE)
HGNC_PATTERN = re.compile(r"(HGNC:\d+)", re.IGNORECASE)


@dataclass
class QueryResultTable:
    headers: List[str]
    rows: List[List[str]]


@dataclass
class NetworkNode:
    identifier: str
    label: str
    degree: int
    pmid: str = ""
    is_literal: bool = False


@dataclass
class NetworkEdge:
    source: str
    target: str
    predicate: str
    label: str


@dataclass
class NetworkModel:
    nodes: List[NetworkNode]
    edges: List[NetworkEdge]
    total_edges: int


class GraphDataService:
    """Graph-focused data access service."""

    EDAM_BASE_URL = "http://edamontology.org/"
    EDAM_OLS_TEMPLATE = "https://www.ebi.ac.uk/ols4/api/ontologies/edam/terms?iri={encoded_iri}"

    def __init__(self):
        self._edam_label_cache: Dict[str, Optional[str]] = {}
        self._hgnc_symbol_cache: Dict[str, Optional[str]] = {}
        self._hgnc_to_symbol: Dict[str, str] = {}
        self._hgnc_mapping_loaded = False

    def load_nt_graph(self, graph_path: str) -> Any:
        if not graph_path:
            raise ValueError("Graph path is required")
        if not os.path.exists(graph_path):
            raise FileNotFoundError(f"Graph file not found: {graph_path}")
        return load_graph(graph_path)

    def resolve_edam_label(self, value: str) -> Optional[str]:
        text = str(value).strip()
        if not text.startswith(self.EDAM_BASE_URL):
            return None

        if text in self._edam_label_cache:
            return self._edam_label_cache[text]

        resolved_label: Optional[str] = None
        encoded_iri = quote(text, safe="")
        lookup_url = self.EDAM_OLS_TEMPLATE.format(encoded_iri=encoded_iri)

        try:
            request = Request(lookup_url, headers={"User-Agent": "akg-kg-explorer/1.0"})
            with urlopen(request, timeout=2.5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            embedded = payload.get("_embedded", {}) if isinstance(payload, dict) else {}
            terms = embedded.get("terms", []) if isinstance(embedded, dict) else []
            if terms and isinstance(terms[0], dict):
                label = terms[0].get("label")
                if isinstance(label, str) and label.strip():
                    resolved_label = label.strip()
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
            resolved_label = None

        self._edam_label_cache[text] = resolved_label
        return resolved_label

    @staticmethod
    def extract_hgnc_id(value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""

        match = HGNC_PATTERN.search(text)
        if not match:
            return ""
        return match.group(1).upper()

    def _ensure_hgnc_mapping(self) -> None:
        if self._hgnc_mapping_loaded:
            return

        self._hgnc_mapping_loaded = True
        candidate_paths = [
            os.path.join(os.path.dirname(__file__), "hgnc_complete_set.json"),
            os.path.join(os.getcwd(), "hgnc_complete_set.json"),
        ]

        hgnc_file = ""
        for candidate in candidate_paths:
            if os.path.exists(candidate):
                hgnc_file = candidate
                break

        if not hgnc_file:
            return

        try:
            with open(hgnc_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return

        docs = payload.get("response", {}).get("docs", []) if isinstance(payload, dict) else []
        if not isinstance(docs, list):
            return

        for gene in docs:
            if not isinstance(gene, dict):
                continue
            hgnc_id = str(gene.get("hgnc_id", "")).strip().upper()
            symbol = str(gene.get("symbol", "")).strip()
            if hgnc_id and symbol:
                self._hgnc_to_symbol[hgnc_id] = symbol

    def resolve_hgnc_symbol(self, value: str) -> Optional[str]:
        hgnc_id = self.extract_hgnc_id(value)
        if not hgnc_id:
            return None

        if hgnc_id in self._hgnc_symbol_cache:
            return self._hgnc_symbol_cache[hgnc_id]

        self._ensure_hgnc_mapping()
        symbol = self._hgnc_to_symbol.get(hgnc_id)
        if symbol:
            self._hgnc_symbol_cache[hgnc_id] = symbol
            return symbol

        self._hgnc_symbol_cache[hgnc_id] = None
        return None

    def display_value(self, value: str) -> str:
        text = str(value).strip()
        if not text:
            return text

        hgnc_symbol = self.resolve_hgnc_symbol(text)
        if hgnc_symbol:
            return hgnc_symbol

        edam_label = self.resolve_edam_label(text)
        if edam_label:
            return edam_label
        return text

    @staticmethod
    def supports_sparql(graph: Any) -> bool:
        return bool(getattr(graph, "supports_sparql", True))

    @staticmethod
    def triples_to_rows(graph: Any) -> List[Tuple[str, str, str]]:
        if hasattr(graph, "iter_string_triples"):
            return list(graph.iter_string_triples())

        rows: List[Tuple[str, str, str]] = []
        for subj, pred, obj in graph:
            rows.append((str(subj), str(pred), str(obj)))
        return rows

    @staticmethod
    def filter_triples(
        triples: Iterable[Tuple[str, str, str]],
        subject_filter: str = "",
        predicate_filter: str = "",
        object_filter: str = "",
    ) -> List[Tuple[str, str, str]]:
        sf = subject_filter.strip().lower()
        pf = predicate_filter.strip().lower()
        of = object_filter.strip().lower()

        filtered: List[Tuple[str, str, str]] = []
        for subj, pred, obj in triples:
            if sf and sf not in subj.lower():
                continue
            if pf and pf not in pred.lower():
                continue
            if of and of not in obj.lower():
                continue
            filtered.append((subj, pred, obj))
        return filtered

    @staticmethod
    def compact_resource_label(value: str, max_length: int = 36) -> str:
        text = str(value).strip()
        if not text:
            return "(blank)"

        candidate = text
        for separator in ("#", "/"):
            if separator in candidate:
                candidate = candidate.rsplit(separator, 1)[-1]

        if candidate.startswith('"') and candidate.endswith('"') and len(candidate) >= 2:
            candidate = candidate[1:-1]

        if not candidate:
            candidate = text

        if len(candidate) <= max_length:
            return candidate

        return candidate[: max_length - 3] + "..."

    @staticmethod
    def looks_like_literal(value: str) -> bool:
        text = str(value).strip()
        if not text:
            return True
        return not (
            text.startswith("http://")
            or text.startswith("https://")
            or text.startswith("urn:")
            or text.startswith("pmid:")
        )

    @staticmethod
    def load_binning_metadata(graph_path: str) -> Dict[str, Any]:
        """Load the .metadata.json sidecar for *graph_path*.  Returns {} on any failure."""
        metadata_path = graph_path + ".metadata.json"
        if not os.path.exists(metadata_path):
            base_path = os.path.splitext(graph_path)[0]
            metadata_path = base_path + ".metadata.json"

        if not os.path.exists(metadata_path):
            return {}

        try:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
        return {}

    @staticmethod
    def find_bin_index(values: List[str]) -> Optional[int]:
        """Return the first bin index found in *values* (e.g. 'bin_3' -> 3), or None."""
        for value in values:
            match = re.search(r"\bbin_(\d+)\b", str(value))
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def format_bin_description(bin_index: int, binning_metadata: Dict[str, Any]) -> str:
        """Return a human-readable description of *bin_index* from *binning_metadata*, or ''."""
        data_min = binning_metadata.get("data_min")
        data_max = binning_metadata.get("data_max")
        data_range = binning_metadata.get("data_range")
        bin_count = binning_metadata.get("bin_count", 10)
        total_values = binning_metadata.get("binned_values_count")

        if not isinstance(data_min, (int, float)) or not isinstance(data_max, (int, float)):
            return ""

        if not isinstance(data_range, (int, float)):
            data_range = data_max - data_min

        if not isinstance(bin_count, int) or bin_count <= 0:
            bin_count = 10

        bin_width = data_range / bin_count if bin_count else 0
        bin_lower = data_min + (bin_index * bin_width)
        bin_upper = data_max if bin_index >= bin_count - 1 else data_min + ((bin_index + 1) * bin_width)

        lines = [
            f"Bin: bin_{bin_index}",
            f"Approximate value range: {bin_lower:.4f} to {bin_upper:.4f}",
            f"Global minimum: {data_min:.4f}",
            f"Global maximum: {data_max:.4f}",
            f"Global range: {data_range:.4f}",
        ]
        if isinstance(total_values, int):
            lines.append(f"Binned numeric values: {total_values}")
        return "\n".join(lines)

    def build_network_model(
        self,
        triples: Iterable[Tuple[str, str, str]],
        max_edges: int = 250,
        label_resolver: Optional[Callable[[str], str]] = None,
    ) -> NetworkModel:
        limited_triples = list(islice(triples, max_edges))

        degrees: Counter[str] = Counter()
        node_map: Dict[str, NetworkNode] = {}
        edges: List[NetworkEdge] = []

        for subj, pred, obj in limited_triples:
            degrees[subj] += 1
            degrees[obj] += 1

            if subj not in node_map:
                node_map[subj] = NetworkNode(
                    identifier=subj,
                    label=self.compact_resource_label(label_resolver(subj) if label_resolver else subj),
                    degree=0,
                    pmid=MetadataService.normalize_pmid(subj),
                    is_literal=self.looks_like_literal(subj),
                )
            if obj not in node_map:
                node_map[obj] = NetworkNode(
                    identifier=obj,
                    label=self.compact_resource_label(label_resolver(obj) if label_resolver else obj),
                    degree=0,
                    pmid=MetadataService.normalize_pmid(obj),
                    is_literal=self.looks_like_literal(obj),
                )

            edges.append(
                NetworkEdge(
                    source=subj,
                    target=obj,
                    predicate=pred,
                    label=self.compact_resource_label(label_resolver(pred) if label_resolver else pred),
                )
            )

        for identifier, node in node_map.items():
            node.degree = degrees.get(identifier, 0)

        nodes = sorted(node_map.values(), key=lambda node: (-node.degree, node.label.lower(), node.identifier.lower()))
        return NetworkModel(nodes=nodes, edges=edges, total_edges=len(limited_triples))


class QueryService:
    """Preset query loading and execution service."""

    def __init__(self, query_dir: str):
        self.query_dir = query_dir

    def list_query_files(self) -> List[str]:
        if not os.path.isdir(self.query_dir):
            return []
        return sorted([name for name in os.listdir(self.query_dir) if name.endswith(".rq")])

    def load_query_text(self, query_name: str) -> str:
        query_path = os.path.join(self.query_dir, query_name)
        if not os.path.exists(query_path):
            raise FileNotFoundError(f"Query file not found: {query_path}")
        with open(query_path, "r", encoding="utf-8") as handle:
            return handle.read()

    @staticmethod
    def render_query(query_text: str, pmid: str = "") -> str:
        normalized_pmid = MetadataService.normalize_pmid(pmid)
        if not normalized_pmid:
            return query_text

        rendered = query_text.replace("{{PMID}}", normalized_pmid)
        rendered = rendered.replace("__PMID__", normalized_pmid)

        if rendered == query_text:
            rendered = re.sub(r"pmid:(\d{5,12})", f"pmid:{normalized_pmid}", rendered, count=1)

        return rendered

    def run_query(self, graph: Any, query_name: str, pmid: str = "") -> QueryResultTable:
        if not GraphDataService.supports_sparql(graph):
            raise ValueError("SPARQL queries are not available for .hdt graphs. Load the .nt graph to run queries.")

        query_text = self.load_query_text(query_name)
        query_text = self.render_query(query_text, pmid=pmid)
        raw_results: Any = graph.query(query_text)

        if not hasattr(raw_results, "serialize"):
            return QueryResultTable(headers=[], rows=[])

        csv_blob = raw_results.serialize(format="csv")
        csv_text = csv_blob.decode("utf-8") if isinstance(csv_blob, bytes) else str(csv_blob)

        csv_reader = csv.reader(io.StringIO(csv_text))
        headers = next(csv_reader, [])
        rows = [row for row in csv_reader]

        return QueryResultTable(headers=headers, rows=rows)


class MetadataService:
    """PMID metadata lookup for article information."""

    def __init__(self, metadata_csv_path: str):
        self.metadata_csv_path = metadata_csv_path
        self._lookup: Dict[str, Dict[str, str]] = {}
        self.status_message: str = ""

    @staticmethod
    def normalize_pmid(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if text.endswith(".0") and text[:-2].isdigit():
            return text[:-2]

        match = PMID_PATTERN.search(text)
        if match:
            return match.group(1)

        if text.isdigit():
            return text
        return ""

    @staticmethod
    def extract_pmid_from_values(values: Iterable[str]) -> str:
        for value in values:
            pmid = MetadataService.normalize_pmid(value)
            if pmid:
                return pmid
        return ""

    def load(self) -> None:
        if not os.path.exists(self.metadata_csv_path):
            self.status_message = f"Metadata file not found: {self.metadata_csv_path}"
            self._lookup = {}
            return

        try:
            df = pd.read_csv(self.metadata_csv_path, keep_default_na=False)
        except Exception as exc:
            self.status_message = f"Failed to read metadata CSV: {exc}"
            self._lookup = {}
            return

        column_map = {str(col).strip().lower(): col for col in df.columns}
        pmid_col = None
        for candidate in ("pmid", "pubmed_id", "pubmedid", "pubmed id"):
            if candidate in column_map:
                pmid_col = column_map[candidate]
                break

        if pmid_col is None:
            self.status_message = "Metadata CSV is missing a PMID column"
            self._lookup = {}
            return

        lookup: Dict[str, Dict[str, str]] = {}
        for _, row in df.iterrows():
            pmid = self.normalize_pmid(row.get(pmid_col, ""))
            if not pmid:
                continue
            entry: Dict[str, str] = {}
            for col in df.columns:
                entry[str(col).strip()] = str(row.get(col, "")).strip()
            lookup[pmid] = entry

        self._lookup = lookup
        if lookup:
            self.status_message = f"Loaded metadata for {len(lookup)} PMID rows"
        else:
            self.status_message = "Metadata CSV loaded but no valid PMID rows found"

    def get_by_pmid(self, pmid: str) -> Optional[Dict[str, str]]:
        normalized = self.normalize_pmid(pmid)
        if not normalized:
            return None
        return self._lookup.get(normalized)
