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
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

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


@dataclass
class ProvenanceIndex:
    publication_tables: Dict[str, List[str]]
    table_publication: Dict[str, str]
    table_lineages: Dict[str, Set[str]]
    table_row_counts: Dict[str, int]
    gene_to_rows: Dict[str, Set[str]]
    row_to_table: Dict[str, str]
    table_to_rows: Dict[str, Set[str]]
    row_logfc: Dict[str, str]
    row_pvalue: Dict[str, str]
    gene_publications: Dict[str, Set[str]]
    gene_tables: Dict[str, Set[str]]
    gene_row_counts: Dict[str, int]


class GraphDataService:
    """Graph-focused data access service."""

    EDAM_BASE_URL = "http://edamontology.org/"
    EDAM_OLS_TEMPLATE = "https://www.ebi.ac.uk/ols4/api/ontologies/edam/terms?iri={encoded_iri}"

    def __init__(self):
        self._edam_label_cache: Dict[str, Optional[str]] = {}
        self._hgnc_symbol_cache: Dict[str, Optional[str]] = {}
        self._hgnc_to_symbol: Dict[str, str] = {}
        self._hgnc_mapping_loaded = False
        self._uuid_context_display_cache: Dict[Tuple[str, str, str], str] = {}
        self._filename_uuid_map: Dict[str, str] = {}
        self._row_uri_labels_cache: Dict[str, Dict[str, Any]] = {}
        self._row_sidecar_context_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._uuid_maps_loaded = False
        self._uuid_map_source_path = ""

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

    def gene_sort_key(self, gene_id: str) -> Tuple[int, int, str]:
        hgnc_id = self.extract_hgnc_id(gene_id)
        if hgnc_id.startswith("HGNC:"):
            numeric = hgnc_id.split(":", 1)[1]
            if numeric.isdigit():
                return (0, int(numeric), gene_id.lower())
        return (1, 0, gene_id.lower())

    def format_gene_display(self, gene_id: str) -> str:
        hgnc_id = self.extract_hgnc_id(gene_id)
        if not hgnc_id:
            return gene_id

        symbol = self.resolve_hgnc_symbol(gene_id)
        if symbol:
            return f"{hgnc_id} ({symbol})"
        return hgnc_id

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

    def display_value_with_uuid_context(
        self,
        value: str,
        input_dir: str = "",
        graph_path: str = "",
        resolve_row_context: bool = True,
    ) -> str:
        """Return a compact display string, resolving UUIDs to human-readable aliases where possible."""
        text = str(value).strip()
        if not text:
            return text

        normalized_input_dir = os.path.normpath(input_dir) if input_dir else ""
        normalized_graph_path = os.path.normpath(graph_path) if graph_path else ""
        cache_key = (f"{text}|rows={int(resolve_row_context)}", normalized_input_dir, normalized_graph_path)
        cached = self._uuid_context_display_cache.get(cache_key)
        if cached is not None:
            return cached

        if "urn:uuid:" not in text.lower():
            resolved = self.display_value(text)
            self._uuid_context_display_cache[cache_key] = resolved
            return resolved

        uuid_match = self._extract_uuid(text)
        if uuid_match:
            if input_dir or graph_path:
                self.load_uuid_maps(input_dir=input_dir, graph_path=graph_path)

            filename = self.resolve_uuid_to_filename(uuid_match)
            if filename:
                self._uuid_context_display_cache[cache_key] = filename
                return filename

            if resolve_row_context:
                row_context = self.resolve_uuid_to_row_context(text, graph_path, input_dir=input_dir)
                if row_context:
                    display_filename = str(row_context.get("display_filename") or row_context.get("filename") or "").strip()
                    row_label = str(row_context.get("row_label") or "").strip()
                    if display_filename and row_label:
                        resolved = f"{display_filename} {row_label}"
                        self._uuid_context_display_cache[cache_key] = resolved
                        return resolved
                    if display_filename:
                        self._uuid_context_display_cache[cache_key] = display_filename
                        return display_filename
                    if row_label:
                        self._uuid_context_display_cache[cache_key] = row_label
                        return row_label

        resolved = self.display_value(text)
        self._uuid_context_display_cache[cache_key] = resolved
        return resolved

    @staticmethod
    def is_has_output_predicate(predicate: str) -> bool:
        p = str(predicate).strip().lower()
        return "has_output" in p or p.endswith("/hasoutput") or p.endswith("#hasoutput")

    @staticmethod
    def is_gene_predicate(predicate: str) -> bool:
        p = str(predicate).strip().lower()
        return "biolink/vocab/gene" in p or p.endswith("/gene") or p.endswith("#gene")

    @staticmethod
    def is_logfc_predicate(predicate: str) -> bool:
        p = str(predicate).strip().lower()
        return "data_3754" in p or p.endswith("/logfc") or p.endswith("#logfc")

    @staticmethod
    def is_pvalue_predicate(predicate: str) -> bool:
        p = str(predicate).strip().lower()
        return "data_1669" in p or "pvalue" in p or p.endswith("/p-value") or p.endswith("#p-value")

    @staticmethod
    def format_metric_value(value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""

        if "^^" in text:
            text = text.split("^^", 1)[0].strip()
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            text = text[1:-1]
        return text

    @staticmethod
    def is_publication_node(value: str) -> bool:
        if MetadataService.normalize_pmid(value):
            return True
        lower = str(value).strip().lower()
        return "pubmed.ncbi.nlm.nih.gov" in lower or "/pmid/" in lower

    def build_provenance_index(self, triples: Iterable[Tuple[str, str, str]]) -> ProvenanceIndex:
        publication_tables: Dict[str, List[str]] = {}
        table_publication: Dict[str, str] = {}
        outgoing: Dict[str, List[str]] = {}
        gene_to_rows: Dict[str, Set[str]] = {}
        row_to_table: Dict[str, str] = {}
        table_to_rows: Dict[str, Set[str]] = {}
        row_logfc: Dict[str, str] = {}
        row_pvalue: Dict[str, str] = {}

        for subj, pred, obj in triples:
            outgoing.setdefault(subj, []).append(obj)
            if self.is_gene_predicate(pred):
                rows = gene_to_rows.setdefault(obj, set())
                rows.add(subj)
            elif self.is_logfc_predicate(pred):
                row_logfc.setdefault(subj, self.format_metric_value(obj))
            elif self.is_pvalue_predicate(pred):
                row_pvalue.setdefault(subj, self.format_metric_value(obj))

            if self.is_has_output_predicate(pred) and self.is_publication_node(subj):
                tables = publication_tables.setdefault(subj, [])
                if obj not in tables:
                    tables.append(obj)
                table_publication.setdefault(obj, subj)

        table_lineages: Dict[str, Set[str]] = {}
        table_row_counts: Dict[str, int] = {}
        for tables in publication_tables.values():
            for table_id in tables:
                children = set(outgoing.get(table_id, []))
                table_row_counts[table_id] = len(children)
                table_to_rows[table_id] = children
                for child_id in children:
                    row_to_table.setdefault(child_id, table_id)

                lineage: Set[str] = {table_id}
                frontier = [table_id]
                while frontier:
                    current = frontier.pop()
                    for nxt in outgoing.get(current, []):
                        if nxt in lineage:
                            continue
                        lineage.add(nxt)
                        frontier.append(nxt)
                table_lineages[table_id] = lineage

        for pub_id in publication_tables:
            publication_tables[pub_id].sort()

        gene_publications: Dict[str, Set[str]] = {}
        gene_tables: Dict[str, Set[str]] = {}
        gene_row_counts: Dict[str, int] = {}
        for gene_id, row_ids in gene_to_rows.items():
            tables_for_gene: Set[str] = set()
            publications_for_gene: Set[str] = set()
            for row_id in row_ids:
                table_id = row_to_table.get(row_id, "")
                if not table_id:
                    continue
                tables_for_gene.add(table_id)
                publication_id = table_publication.get(table_id, "")
                if publication_id:
                    publications_for_gene.add(publication_id)

            gene_tables[gene_id] = tables_for_gene
            gene_publications[gene_id] = publications_for_gene
            gene_row_counts[gene_id] = len(row_ids)

        return ProvenanceIndex(
            publication_tables=dict(sorted(publication_tables.items(), key=lambda kv: kv[0].lower())),
            table_publication=table_publication,
            table_lineages=table_lineages,
            table_row_counts=table_row_counts,
            gene_to_rows=gene_to_rows,
            row_to_table=row_to_table,
            table_to_rows=table_to_rows,
            row_logfc=row_logfc,
            row_pvalue=row_pvalue,
            gene_publications=gene_publications,
            gene_tables=gene_tables,
            gene_row_counts=gene_row_counts,
        )

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

    # ─────────────────────────────────────────────────────────────────────
    # UUID Resolution Methods
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_uuid(text: str) -> Optional[str]:
        """Extract urn:uuid:XXX from text, returning just the UUID part."""
        match = re.search(r"urn:uuid:([a-f0-9\-]+)", str(text), re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return None

    def load_uuid_maps(self, input_dir: str = "", graph_path: str = "") -> None:
        """
        Load filename_uuid_map.json from the standard location.
        This builds reverse map for UUID → filename lookup.
        """
        candidate_paths: List[str] = []
        if input_dir:
            candidate_paths.append(os.path.join(input_dir, "graph", "filename_uuid_map.json"))
            candidate_paths.append(os.path.join(input_dir, "filename_uuid_map.json"))

        if graph_path:
            graph_dir = os.path.dirname(os.path.abspath(graph_path))
            input_guess = os.path.dirname(graph_dir)
            candidate_paths.append(os.path.join(graph_dir, "filename_uuid_map.json"))
            candidate_paths.append(os.path.join(input_guess, "graph", "filename_uuid_map.json"))
            candidate_paths.append(os.path.join(input_guess, "filename_uuid_map.json"))

        seen: set[str] = set()
        deduped_candidates: List[str] = []
        for path in candidate_paths:
            normalized = os.path.normpath(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped_candidates.append(path)

        map_path = ""
        for candidate in deduped_candidates:
            if os.path.exists(candidate):
                map_path = candidate
                break

        if self._uuid_maps_loaded and map_path == self._uuid_map_source_path:
            return

        self._uuid_maps_loaded = True
        self._uuid_map_source_path = map_path
        self._filename_uuid_map = {}

        if not map_path:
            return

        try:
            with open(map_path, "r", encoding="utf-8") as f:
                forward_map = json.load(f)
            # Build reverse map: UUID → filename
            if isinstance(forward_map, dict):
                self._filename_uuid_map = {
                    str(v).lower(): str(k)
                    for k, v in forward_map.items()
                    if isinstance(v, str)
                }
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def resolve_uuid_to_filename(self, uuid_str: str) -> Optional[str]:
        """Resolve a UUID to its filename (e.g. 'expdata_TableS6')."""
        if not self._uuid_maps_loaded:
            return None
        return self._filename_uuid_map.get(uuid_str.lower())

    @staticmethod
    def _extract_graph_pmids(graph_path: str) -> List[str]:
        """Extract PMID tokens from combined graph filenames."""
        graph_name = os.path.basename(graph_path)
        stem = graph_name
        if stem.endswith(".nt"):
            stem = stem[:-3]
        if stem.endswith("_binned"):
            stem = stem[:-7]
        if not stem.startswith("combined_"):
            return []
        suffix = stem[len("combined_"):]
        return [part for part in suffix.split("_") if part.isdigit()]

    def _candidate_row_label_dirs(self, graph_path: str, input_dir: str = "") -> List[str]:
        candidates: List[str] = []

        graph_dir = os.path.dirname(os.path.abspath(graph_path)) if graph_path else ""
        if graph_dir:
            candidates.append(graph_dir)

        if input_dir:
            for pmid in self._extract_graph_pmids(graph_path):
                candidates.append(os.path.join(input_dir, "graph", pmid))
            supp_data_dir = os.path.join(input_dir, "supp_data")
            for pmid in self._extract_graph_pmids(graph_path):
                candidates.append(os.path.join(supp_data_dir, pmid))

        deduped: List[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = os.path.normpath(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(candidate)
        return deduped

    @staticmethod
    def _candidate_graph_sidecar_paths(graph_path: str) -> List[str]:
        candidates: List[str] = []
        if not graph_path:
            return candidates

        normalized = os.path.abspath(graph_path)
        candidates.append(normalized + ".row_uri_labels.json")

        if normalized.endswith("_binned.nt"):
            unbinned = normalized[: -len("_binned.nt")] + ".nt"
            candidates.append(unbinned + ".row_uri_labels.json")

        deduped: List[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized_candidate = os.path.normpath(candidate)
            if normalized_candidate in seen:
                continue
            seen.add(normalized_candidate)
            deduped.append(candidate)
        return deduped

    @staticmethod
    def _display_row_source_name(filename: str) -> str:
        display_name = str(filename)
        if display_name.startswith("graph_clean_"):
            display_name = display_name[len("graph_clean_"):]
        elif display_name.startswith("graph_"):
            display_name = display_name[len("graph_"):]

        for suffix in (".csv.nt", ".tsv.nt", ".xlsx.nt", ".xls.nt", ".nt"):
            if display_name.endswith(suffix):
                display_name = display_name[: -len(suffix)]
                break

        return display_name

    def _row_context_from_sidecar_entry(self, candidate: str, label: Any) -> Dict[str, Any]:
        if isinstance(label, dict):
            filename = str(label.get("filename") or label.get("source_filename") or "")
            row_label = str(label.get("row_label") or label.get("label") or "")
            row_index_value = label.get("row_index")
            row_index = str(row_index_value) if row_index_value not in (None, "") else row_label
        else:
            filename = ""
            row_label = str(label)
            row_index = row_label

        if not filename:
            if candidate.endswith("_row_uri_labels.json"):
                filename = candidate[: -len("_row_uri_labels.json")]
            elif candidate.endswith(".row_uri_labels.json"):
                filename = candidate[: -len(".row_uri_labels.json")]
            else:
                filename = candidate

        if not row_label:
            row_label = str(label)

        row_match = re.search(r"row\s+(\d+)", row_label, re.IGNORECASE)
        if row_match:
            row_index = row_match.group(1)

        return {
            "filename": filename,
            "display_filename": self._display_row_source_name(filename),
            "row_label": row_label,
            "row_index": row_index,
        }

    def _load_row_sidecar(self, sidecar_path: str) -> Dict[str, Dict[str, Any]]:
        """Load and cache row-context entries for a sidecar JSON file."""
        normalized_path = os.path.normpath(os.path.abspath(sidecar_path))
        cached = self._row_sidecar_context_cache.get(normalized_path)
        if cached is not None:
            return cached

        contexts: Dict[str, Dict[str, Any]] = {}
        if not os.path.exists(normalized_path):
            self._row_sidecar_context_cache[normalized_path] = contexts
            self._row_uri_labels_cache[normalized_path] = {}
            return contexts

        try:
            with open(normalized_path, "r", encoding="utf-8") as f:
                row_labels = json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            self._row_sidecar_context_cache[normalized_path] = contexts
            self._row_uri_labels_cache[normalized_path] = {}
            return contexts

        if not isinstance(row_labels, dict):
            self._row_sidecar_context_cache[normalized_path] = contexts
            self._row_uri_labels_cache[normalized_path] = {}
            return contexts

        self._row_uri_labels_cache[normalized_path] = row_labels
        candidate_name = os.path.basename(normalized_path)
        for urn_key, label in row_labels.items():
            extracted_uuid = self._extract_uuid(urn_key)
            if not extracted_uuid:
                continue
            contexts[extracted_uuid] = self._row_context_from_sidecar_entry(candidate_name, label)

        self._row_sidecar_context_cache[normalized_path] = contexts
        return contexts

    def prepopulate_row_context_cache(self, graph_path: str, input_dir: str = "") -> int:
        """Load candidate row sidecars into memory and return number of sidecar files loaded."""
        seen_paths: set[str] = set()
        loaded_count = 0

        for sidecar_path in self._candidate_graph_sidecar_paths(graph_path):
            normalized = os.path.normpath(os.path.abspath(sidecar_path))
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            if not os.path.exists(sidecar_path):
                continue
            self._load_row_sidecar(sidecar_path)
            loaded_count += 1

        for candidate_dir in self._candidate_row_label_dirs(graph_path, input_dir=input_dir):
            try:
                candidates = [
                    f
                    for f in os.listdir(candidate_dir)
                    if f.endswith("_row_uri_labels.json") or f.endswith(".row_uri_labels.json")
                ]
            except (OSError, FileNotFoundError):
                continue

            for candidate in candidates:
                full_path = os.path.join(candidate_dir, candidate)
                normalized = os.path.normpath(os.path.abspath(full_path))
                if normalized in seen_paths:
                    continue
                seen_paths.add(normalized)
                self._load_row_sidecar(full_path)
                loaded_count += 1

        return loaded_count

    def resolve_uuid_to_row_context(self, uuid_str: str, graph_path: str, input_dir: str = "") -> Optional[Dict[str, Any]]:
        """
        Attempt to find row context (filename, row index) for a row UUID.
        Searches for {graph_name}_row_uri_labels.json sidecars.
        Returns: {filename, row_index, row_label} or None.
        """
        uuid_clean = self._extract_uuid(uuid_str) or str(uuid_str).lower()

        for sidecar_path in self._candidate_graph_sidecar_paths(graph_path):
            contexts = self._load_row_sidecar(sidecar_path)
            context = contexts.get(uuid_clean)
            if context:
                return context

        candidate_dirs = self._candidate_row_label_dirs(graph_path, input_dir=input_dir)
        if not candidate_dirs:
            return None

        for candidate_dir in candidate_dirs:
            try:
                candidates = [
                    f
                    for f in os.listdir(candidate_dir)
                    if f.endswith("_row_uri_labels.json") or f.endswith(".row_uri_labels.json")
                ]
            except (OSError, FileNotFoundError):
                candidates = []

            for candidate in candidates:
                full_path = os.path.join(candidate_dir, candidate)
                contexts = self._load_row_sidecar(full_path)
                context = contexts.get(uuid_clean)
                if context:
                    return context

        return None

    def enhance_uuid_values(self, values: List[str], input_dir: str = "", graph_path: str = "") -> List[str]:
        """
        Replace urn:uuid:XXX with human-readable names where possible.
        Returns new list with enhanced values.
        """
        if not values:
            return values

        # Ensure UUID maps are loaded
        if input_dir or graph_path:
            self.load_uuid_maps(input_dir=input_dir, graph_path=graph_path)

        enhanced = []
        for value in values:
            uuid_match = self._extract_uuid(value)
            if not uuid_match:
                enhanced.append(value)
                continue

            # Try filename lookup first
            filename = self.resolve_uuid_to_filename(uuid_match)
            if filename:
                enhanced.append(f"{value} [{filename}]")
                continue

            # Try row context lookup
            row_context = self.resolve_uuid_to_row_context(value, graph_path, input_dir=input_dir)
            if row_context:
                enhanced.append(
                    f"{value} [from {row_context.get('display_filename', row_context['filename'])}, {row_context['row_label']}]"
                )
                continue

            # If nothing matched, keep original
            enhanced.append(value)

        return enhanced

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
        return self.run_query_text(graph, query_text, pmid=pmid)

    def run_query_text(self, graph: Any, query_text: str, pmid: str = "") -> QueryResultTable:
        if not GraphDataService.supports_sparql(graph):
            raise ValueError("SPARQL queries are not available for .hdt graphs. Load the .nt graph to run queries.")

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
