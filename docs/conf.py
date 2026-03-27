"""Sphinx configuration for the AKG service layer."""

import os
import sys

# ── path setup ───────────────────────────────────────────────────────────────
# Let autodoc import the package from the repo root.
sys.path.insert(0, os.path.abspath(".."))

# ── project metadata ─────────────────────────────────────────────────────────
project = "AKG Knowledge Graph Explorer"
copyright = "2025, AKG Project Contributors"
author = "AKG Project Contributors"

release = "1.0"

# ── extension list ───────────────────────────────────────────────────────────
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",       # NumPy / Google-style docstrings
    "sphinx.ext.viewcode",       # source links next to each member
    "sphinx.ext.intersphinx",    # cross-reference Python standard library
]

# ── autodoc defaults ─────────────────────────────────────────────────────────
# Document __init__, show type annotations, preserve original member order.
autoclass_content = "both"           # merge class + __init__ docstrings
autodoc_member_order = "bysource"    # keep source order rather than alphabetical
autodoc_typehints = "description"    # inject types into parameter descriptions
autodoc_typehints_description_target = "documented"

# ── Napoleon settings ─────────────────────────────────────────────────────────
napoleon_google_docstring = False
napoleon_numpy_docstring = False

# ── intersphinx ──────────────────────────────────────────────────────────────
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# ── HTML theme ───────────────────────────────────────────────────────────────
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "titles_only": False,
}

# ── build artefacts ──────────────────────────────────────────────────────────
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
