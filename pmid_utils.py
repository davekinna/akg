"""Shared helpers for PMID normalization and metadata/tracking comparisons."""

import os
from typing import Any

import pandas as pd


def normalize_pmid(value: Any) -> str:
    """Normalize PMID values so comparisons are stable."""
    if pd.isna(value):
        return ''
    pmid = str(value).strip()
    if pmid.endswith('.0') and pmid[:-2].isdigit():
        pmid = pmid[:-2]
    return pmid


def parse_bool(value: Any) -> bool:
    """Parse booleans from CSV/Excel values."""
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {'1', 'true', 't', 'yes', 'y'}


def sort_pmids(pmids: set[str]) -> list[str]:
    """Sort PMIDs with numeric values first, then lexical fallback."""
    return sorted(pmids, key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else p))


def extract_tracking_pmids(tdf: pd.DataFrame, step: int | None = None) -> set[str]:
    """Extract normalized PMID set from tracking DataFrame."""
    subset = tdf
    if step is not None:
        subset = tdf[tdf['step'] == step]

    pmids = set()
    for value in subset['pmid'].tolist():
        pmid = normalize_pmid(value)
        if pmid:
            pmids.add(pmid)
    return pmids


def _resolve_pmid_column(metadata_df: pd.DataFrame) -> str | None:
    column_map = {str(col).strip().lower(): col for col in metadata_df.columns}
    for candidate in ('pmid', 'pubmed_id', 'pubmedid', 'pubmed id'):
        if candidate in column_map:
            return column_map[candidate]
    return None


def load_metadata_pmids(metadata_file: str) -> tuple[set[str], str]:
    """Load metadata PMIDs, excluding rows where exclude is true."""
    if not os.path.isfile(metadata_file):
        return set(), f"Metadata file not found: {metadata_file}"

    try:
        metadata_df = pd.read_csv(metadata_file, keep_default_na=False)
    except Exception as exc:
        return set(), f"Failed to read metadata file {metadata_file}: {exc}"

    pmid_col = _resolve_pmid_column(metadata_df)
    if pmid_col is None:
        return set(), f"Metadata file {metadata_file} is missing a PMID column"

    column_map = {str(col).strip().lower(): col for col in metadata_df.columns}
    exclude_col = column_map.get('exclude')
    pmids = set()
    for _, row in metadata_df.iterrows():
        if exclude_col is not None and parse_bool(row.get(exclude_col, False)):
            continue
        pmid = normalize_pmid(row.get(pmid_col, ''))
        if pmid:
            pmids.add(pmid)

    return pmids, ''


def load_article_metadata_by_pmid(metadata_file: str) -> tuple[dict[str, dict[str, str]], str]:
    """Load article metadata CSV into lookup keyed by normalized PMID."""
    if not os.path.exists(metadata_file):
        return {}, f'Article metadata file not found: {metadata_file}. Continuing without article metadata.'

    try:
        metadata_df = pd.read_csv(metadata_file, keep_default_na=False)
    except Exception as exc:
        return {}, f'Failed to read article metadata file {metadata_file}: {exc}. Continuing without article metadata.'

    pmid_col = _resolve_pmid_column(metadata_df)
    if pmid_col is None:
        return {}, f'Article metadata file {metadata_file} is missing a PMID column.'

    lookup: dict[str, dict[str, str]] = {}
    for _, row in metadata_df.iterrows():
        pmid_key = normalize_pmid(row.get(pmid_col, ''))
        if not pmid_key:
            continue
        row_dict: dict[str, str] = {}
        for col in metadata_df.columns:
            key = str(col).strip()
            row_dict[key] = str(row.get(col, '')).strip()
        lookup[pmid_key] = row_dict

    if not lookup:
        return {}, f'Article metadata file {metadata_file} loaded but no valid PMID rows were found.'

    return lookup, ''


def compute_pmid_visibility(metadata_pmids: set[str], tracking_pmids: set[str]) -> dict[str, set[str]]:
    """Return overlap and differences between metadata and tracking PMID sets."""
    in_both = metadata_pmids.intersection(tracking_pmids)
    metadata_only = metadata_pmids.difference(tracking_pmids)
    tracking_only = tracking_pmids.difference(metadata_pmids)
    return {
        'in_both': in_both,
        'metadata_only': metadata_only,
        'tracking_only': tracking_only,
    }
