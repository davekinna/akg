kg\_services — Service Layer
============================

.. module:: kg_services
   :synopsis: Domain services for loading and interrogating AKG RDF graphs.

This module contains all domain logic for the AKG Knowledge Graph Explorer.
It has **no dependency on PyQt5** and can be used independently of the GUI.

Module-level constants
----------------------

.. data:: PMID_PATTERN

   Pre-compiled :class:`re.Pattern` that matches PubMed identifiers in two
   forms:

   * ``pubmed.ncbi.nlm.nih.gov/<id>``
   * ``pmid:<id>``

   Capturing group 1 returns the bare numeric PMID (5–12 digits).

.. data:: HGNC_PATTERN

   Pre-compiled :class:`re.Pattern` that matches ``HGNC:<number>`` tokens
   (case-insensitive).  Capturing group 1 returns the identifier in upper
   case.

Data classes
------------

.. autoclass:: QueryResultTable
   :members:

   Holds the tabular result of a SPARQL query as parsed from CSV serialisation.

   .. attribute:: headers
      :type: List[str]

      Column names returned by the query (in order).

   .. attribute:: rows
      :type: List[List[str]]

      Data rows; each inner list corresponds one-to-one with *headers*.

.. autoclass:: NetworkNode
   :members:

   Represents a single node in a force-directed network diagram.

   .. attribute:: identifier
      :type: str

      The raw URI or literal string that uniquely identifies the node in
      the graph.

   .. attribute:: label
      :type: str

      Compact, human-readable label (at most 36 characters).

   .. attribute:: degree
      :type: int

      Number of edges (both incoming and outgoing) incident on this node.

   .. attribute:: pmid
      :type: str

      PubMed ID extracted from *identifier*, or ``""`` if not applicable.

   .. attribute:: is_literal
      :type: bool

      ``True`` when the node value is a plain literal rather than a URI.

.. autoclass:: NetworkEdge
   :members:

   Represents a directed predicate edge between two :class:`NetworkNode`
   instances.

   .. attribute:: source
      :type: str

      Raw URI of the subject node.

   .. attribute:: target
      :type: str

      Raw URI of the object node.

   .. attribute:: predicate
      :type: str

      Raw URI (or compact form) of the predicate.

   .. attribute:: label
      :type: str

      Compact, human-readable label for the predicate.

.. autoclass:: NetworkModel
   :members:

   Complete model for rendering a network graph view.

   .. attribute:: nodes
      :type: List[NetworkNode]

      All nodes, sorted by descending degree then label.

   .. attribute:: edges
      :type: List[NetworkEdge]

      All edges (up to the *max_edges* limit supplied to
      :meth:`GraphDataService.build_network_model`).

   .. attribute:: total_edges
      :type: int

      Actual number of edges included (may be less than the total triples
      in the graph when the *max_edges* cap was applied).

GraphDataService
----------------

.. autoclass:: GraphDataService
   :members:
   :undoc-members:
   :show-inheritance:

   Central service for RDF graph access, label resolution, UUID translation,
   and network-model construction.

   **Instance caches** (populated lazily and never evicted within a session):

   .. attribute:: _edam_label_cache
      :type: Dict[str, Optional[str]]

      Maps EDAM IRI → resolved OLS label (or ``None`` when the lookup
      failed).  Avoids repeat HTTP requests.

   .. attribute:: _hgnc_symbol_cache
      :type: Dict[str, Optional[str]]

      Maps ``HGNC:<id>`` → gene symbol (or ``None``) after the local HGNC
      complete-set JSON has been consulted.

   .. attribute:: _uuid_context_display_cache
      :type: Dict[Tuple[str, str, str], str]

      Memoises :meth:`display_value_with_uuid_context` results.  Key is
      ``(value_with_mode_suffix, normalised_input_dir, normalised_graph_path)``.

   .. attribute:: _filename_uuid_map
      :type: Dict[str, str]

      Reverse map ``uuid → filename`` built from
      ``filename_uuid_map.json``.

   .. attribute:: _row_uri_labels_cache
      :type: Dict[str, Dict[str, Any]]

      Maps normalised sidecar path → raw JSON payload loaded from disk.

   .. attribute:: _row_sidecar_context_cache
      :type: Dict[str, Dict[str, Dict[str, Any]]]

      Maps normalised sidecar path → ``{uuid: row_context_dict}``.  Once a
      sidecar is entered here its file is never re-opened.

   Graph loading
   ~~~~~~~~~~~~~

   .. automethod:: load_nt_graph

   Label resolution
   ~~~~~~~~~~~~~~~~

   .. automethod:: display_value
   .. automethod:: display_value_with_uuid_context
   .. automethod:: resolve_edam_label
   .. automethod:: resolve_hgnc_symbol
   .. automethod:: extract_hgnc_id
   .. automethod:: compact_resource_label
   .. automethod:: looks_like_literal

   Triple filtering and extraction
   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

   .. automethod:: triples_to_rows
   .. automethod:: filter_triples

   UUID resolution
   ~~~~~~~~~~~~~~~

   .. automethod:: load_uuid_maps
   .. automethod:: resolve_uuid_to_filename
   .. automethod:: resolve_uuid_to_row_context
   .. automethod:: enhance_uuid_values
   .. automethod:: prepopulate_row_context_cache

   Binning metadata
   ~~~~~~~~~~~~~~~~

   .. automethod:: load_binning_metadata
   .. automethod:: find_bin_index
   .. automethod:: format_bin_description

   Network model
   ~~~~~~~~~~~~~

   .. automethod:: build_network_model

   Utility methods (static / private)
   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

   .. automethod:: supports_sparql

QueryService
------------

.. autoclass:: QueryService
   :members:
   :undoc-members:
   :show-inheritance:

   Loads preset SPARQL ``.rq`` query files from a directory and executes them
   against a loaded graph.

   .. attribute:: query_dir
      :type: str

      Filesystem path to the directory containing ``.rq`` query files.

   Loading queries
   ~~~~~~~~~~~~~~~

   .. automethod:: list_query_files
   .. automethod:: load_query_text
   .. automethod:: render_query

   Executing queries
   ~~~~~~~~~~~~~~~~~

   .. automethod:: run_query

MetadataService
---------------

.. autoclass:: MetadataService
   :members:
   :undoc-members:
   :show-inheritance:

   Loads a CSV file of article metadata and exposes lookup by PMID.

   .. attribute:: metadata_csv_path
      :type: str

      Path to the CSV file supplied at construction time.

   .. attribute:: status_message
      :type: str

      Human-readable outcome set after each call to :meth:`load`.  Empty
      string before the first load.

   Loading metadata
   ~~~~~~~~~~~~~~~~

   .. automethod:: load

   Looking up articles
   ~~~~~~~~~~~~~~~~~~~~

   .. automethod:: get_by_pmid

   PMID normalisation
   ~~~~~~~~~~~~~~~~~~

   .. automethod:: normalize_pmid
   .. automethod:: extract_pmid_from_values
