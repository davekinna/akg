Architecture Overview
=====================

The AKG Knowledge Graph Explorer separates the domain layer from the GUI
layer.  This page describes the design decisions behind :mod:`kg_services`.

Layers at a glance
------------------

.. code-block:: text

   ┌──────────────────────────────────┐
   │         kg_explorer.py           │  PyQt5 GUI — zero domain logic
   │   KGExplorerWindow               │
   │   GraphLoadWorker (QThread)      │
   └────────────┬─────────────────────┘
                │ method calls only
                ▼
   ┌──────────────────────────────────┐
   │         kg_services.py           │  Pure Python — zero PyQt5
   │   GraphDataService               │
   │   QueryService                   │
   │   MetadataService                │
   └──────────────────────────────────┘

This strict separation keeps domain logic independently testable and allows
:mod:`kg_services` to be imported in notebooks or batch scripts without a
display.

Service responsibilities
------------------------

GraphDataService
~~~~~~~~~~~~~~~~

Handles everything related to the graph itself.

* **Graph loading** — delegates to ``akg.load_graph`` which supports both
  N-Triples (``.nt``) and HDT formats.  SPARQL queries are only available
  for N-Triples graphs; :meth:`~kg_services.GraphDataService.supports_sparql`
  checks capability at runtime.

* **Label resolution** — :meth:`~kg_services.GraphDataService.display_value`
  converts raw URIs and identifiers to human-readable labels by consulting,
  in priority order:

  1. HGNC gene symbols (local ``hgnc_complete_set.json`` file).
  2. EDAM ontology labels (live OLS4 API call with 2.5-second timeout,
     cached for the session).
  3. Compact fragment / path-tail extraction.

* **UUID translation** — rows in the knowledge graph are identified by
  ``urn:uuid:<uuid>`` URIs.
  :meth:`~kg_services.GraphDataService.display_value_with_uuid_context`
  resolves UUIDs to human-readable aliases in two steps:

  1. **Filename UUID map** — loaded once from ``filename_uuid_map.json``
     via :meth:`~kg_services.GraphDataService.load_uuid_maps`.  Resolves
     dataset-level UUIDs to source filenames such as ``expdata_TableS6``.

  2. **Row-label sidecars** — ``*.row_uri_labels.json`` files created by
     the AKG pipeline.  Each entry maps a row UUID to a dict containing
     ``filename``, ``row_label``, and ``row_index``.  Sidecars are parsed
     **once** by :meth:`~kg_services.GraphDataService._load_row_sidecar`
     and stored permanently in ``_row_sidecar_context_cache``.
     :meth:`~kg_services.GraphDataService.prepopulate_row_context_cache`
     pre-loads all candidate sidecars at graph-open time so that table
     rendering never touches the filesystem.

  Results are memoised in ``_uuid_context_display_cache`` keyed by
  ``(value, input_dir, graph_path)``.

* **Binning metadata** — numeric values in binned graphs are replaced by
  ``bin_<N>`` tokens.  :meth:`~kg_services.GraphDataService.load_binning_metadata`
  reads the companion ``.metadata.json`` sidecar and
  :meth:`~kg_services.GraphDataService.format_bin_description` converts a
  bin index back to an approximate numeric range for display.

* **Network model** — :meth:`~kg_services.GraphDataService.build_network_model`
  converts a triple iterable into :class:`~kg_services.NetworkModel`,
  computing per-node degree and applying an optional label-resolver callback.

QueryService
~~~~~~~~~~~~

Manages a directory of preset SPARQL ``.rq`` files.

* :meth:`~kg_services.QueryService.list_query_files` lists available queries.
* :meth:`~kg_services.QueryService.render_query` performs ``{{PMID}}``
  substitution so that parameterised queries can be scoped to a specific
  article.
* :meth:`~kg_services.QueryService.run_query` executes the query, serialises
  results as CSV, and returns a :class:`~kg_services.QueryResultTable`.

MetadataService
~~~~~~~~~~~~~~~

Reads a flat CSV of article metadata (title, authors, journal …) indexed by
PMID.

* :meth:`~kg_services.MetadataService.load` accepts any column named
  ``pmid``, ``pubmed_id``, ``pubmedid``, or ``pubmed id`` (case-insensitive).
* :meth:`~kg_services.MetadataService.normalize_pmid` strips prefixes and
  trailing ``.0`` artefacts introduced by some spreadsheet exports.
* :meth:`~kg_services.MetadataService.get_by_pmid` returns the raw row dict.

Caching strategy
----------------

To avoid repeated I/O during interactive use the service layer maintains
several in-memory caches:

+-----------------------------------+----------------------------------------+
| Cache                             | Scope                                  |
+===================================+========================================+
| ``_edam_label_cache``             | EDAM IRI → label (HTTP, session)       |
+-----------------------------------+----------------------------------------+
| ``_hgnc_symbol_cache``            | HGNC ID → gene symbol (session)        |
+-----------------------------------+----------------------------------------+
| ``_uuid_context_display_cache``   | (value, dir, graph) → display string   |
+-----------------------------------+----------------------------------------+
| ``_row_sidecar_context_cache``    | sidecar path → {uuid: context} map     |
+-----------------------------------+----------------------------------------+
| ``_row_uri_labels_cache``         | sidecar path → raw JSON payload        |
+-----------------------------------+----------------------------------------+

None of the caches are evicted during a session.  Loading a different graph
requires either a new :class:`~kg_services.GraphDataService` instance or a
manual call to :meth:`~kg_services.GraphDataService.load_uuid_maps` with the
new paths (which detects the changed source path and reloads the filename
map).

Async loading pattern
---------------------

The GUI defers graph loading to a ``GraphLoadWorker`` background thread
(defined in ``kg_explorer.py``) so the window renders before any I/O begins.
The worker emits staged progress messages:

1. *Loading graph* — calls :meth:`~kg_services.GraphDataService.load_nt_graph`.
2. *Extracting triples* — calls
   :meth:`~kg_services.GraphDataService.triples_to_rows`.
3. *Loading binning metadata* — calls
   :meth:`~kg_services.GraphDataService.load_binning_metadata`.
4. *Preloading row-label sidecars* — calls
   :meth:`~kg_services.GraphDataService.prepopulate_row_context_cache`.

Steps 3 and 4 are entirely service-layer calls; the worker is only glue.

Testing
-------

All public methods of :mod:`kg_services` have unit tests in
``test/test_kg_services.py``.  Because the module has no PyQt5 dependency,
the test suite can be run with plain ``pytest`` without a display.
