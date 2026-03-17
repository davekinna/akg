"""Shared services for loading and interrogating AKG RDF graphs."""

from __future__ import annotations

import os
import re
import csv
import io
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from rdflib import Graph

from akg import load_graph

PMID_PATTERN = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|\bpmid:)(\d{5,12})", re.IGNORECASE)


@dataclass
class QueryResultTable:
    headers: List[str]
    rows: List[List[str]]


class GraphDataService:
    """Graph-focused data access service."""

    def load_nt_graph(self, graph_path: str) -> Graph:
        if not graph_path:
            raise ValueError("Graph path is required")
        if not os.path.exists(graph_path):
            raise FileNotFoundError(f"Graph file not found: {graph_path}")
        return load_graph(graph_path)

    @staticmethod
    def triples_to_rows(graph: Graph) -> List[Tuple[str, str, str]]:
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

    def run_query(self, graph: Graph, query_name: str, pmid: str = "") -> QueryResultTable:
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
