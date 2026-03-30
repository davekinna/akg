#!/usr/bin/env python3
"""PyQt5 GUI for loading and interrogating AKG RDF knowledge graphs."""

from __future__ import annotations

import argparse
import html
import itertools
import json
import math
import os
import re
import threading
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from PyQt5.QtCore import QPoint, QPointF, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSplitter,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kg_services import GraphDataService, MetadataService, NetworkNode, QueryResultTable, QueryService

SETTINGS_FILE = "kg_explorer_settings.json"
DEFAULT_VISIBLE_TRIPLES = 1000
DEFAULT_NETWORK_MAX_EDGES = 250
NETWORK_NODE_RADIUS = 18.0
ITEM_USER_ROLE = 32
OVERVIEW_KIND_ROLE = ITEM_USER_ROLE + 1
OVERVIEW_ID_ROLE = ITEM_USER_ROLE + 2


class QueryWorker(threading.Thread):
    """Background thread for running a SPARQL query.

    *callback* is called with ``(headers, rows, error_message)`` on completion.
    Using a plain callable keeps this class independent of any GUI framework.
    """

    def __init__(
        self,
        graph: Any,
        query_name: str,
        pmid: str,
        query_text_override: str,
        query_service: QueryService,
        callback: Any,
    ):
        super().__init__(daemon=True)
        self.graph = graph
        self.query_name = query_name
        self.pmid = pmid
        self.query_text_override = query_text_override
        self.query_service = query_service
        self.callback = callback

    def run(self) -> None:
        try:
            if self.query_text_override.strip():
                table = self.query_service.run_query_text(self.graph, self.query_text_override, pmid=self.pmid)
            else:
                table = self.query_service.run_query(self.graph, self.query_name, pmid=self.pmid)
            self.callback(table.headers, table.rows, "")
        except Exception as exc:
            self.callback([], [], str(exc))


class GraphLoadWorker(threading.Thread):
    """Background thread for loading a graph and related startup artifacts."""

    def __init__(
        self,
        graph_path: str,
        input_dir: str,
        graph_service: GraphDataService,
        progress_callback: Any,
        callback: Any,
    ):
        super().__init__(daemon=True)
        self.graph_path = graph_path
        self.input_dir = input_dir
        self.graph_service = graph_service
        self.progress_callback = progress_callback
        self.callback = callback

    def run(self) -> None:
        try:
            self.progress_callback(f"Loading graph: {self.graph_path}")
            graph = self.graph_service.load_nt_graph(self.graph_path)

            self.progress_callback("Extracting triples...")
            all_triples = self.graph_service.triples_to_rows(graph)

            self.progress_callback("Loading binning metadata...")
            binning_metadata = self.graph_service.load_binning_metadata(self.graph_path)

            self.progress_callback("Preloading row-label sidecars...")
            sidecar_count = self.graph_service.prepopulate_row_context_cache(
                graph_path=self.graph_path,
                input_dir=self.input_dir,
            )

            self.callback(self.graph_path, graph, all_triples, binning_metadata, sidecar_count, "")
        except Exception as exc:
            self.callback(self.graph_path, None, [], {}, 0, str(exc))


class NetworkGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self._is_panning = False
        self._pan_start = QPoint()

    def wheelEvent(self, event: Any) -> None:
        if event.angleDelta().y() > 0:
            self.scale(1.15, 1.15)
        else:
            self.scale(1 / 1.15, 1 / 1.15)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MiddleButton:
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._is_panning:
            delta = self.mapToScene(event.pos()) - self.mapToScene(self._pan_start)
            self.translate(-delta.x(), -delta.y())
            self._pan_start = event.pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MiddleButton and self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class NetworkEdgeItem(QGraphicsLineItem):
    def __init__(self, source_item: "NetworkNodeItem", target_item: "NetworkNodeItem", predicate: str):
        super().__init__()
        self.source_item = source_item
        self.target_item = target_item
        self.predicate = predicate
        self._base_color = QColor("#8fa0b3")
        self._highlighted = False
        self._dimmed = False
        self.source_item.edge_items.append(self)
        self.target_item.edge_items.append(self)
        self.setPen(QPen(self._base_color, 1.4))
        self.setZValue(0)
        self.setToolTip(f"Predicate: {predicate}")
        self.update_position()

    def set_base_color(self, color: QColor) -> None:
        self._base_color = QColor(color)
        if not self._highlighted:
            self._apply_visual_state()

    def set_highlighted(self, highlighted: bool) -> None:
        self._highlighted = highlighted
        if highlighted:
            self.setPen(QPen(QColor("#d9480f"), 2.6))
            self.setZValue(1)
        else:
            self._apply_visual_state()

    def set_dimmed(self, dimmed: bool) -> None:
        self._dimmed = dimmed
        if not self._highlighted:
            self._apply_visual_state()

    def _apply_visual_state(self) -> None:
        color = QColor(self._base_color)
        width = 1.4
        z_value = 0
        if self._dimmed:
            color.setAlpha(55)
            width = 1.0
            z_value = -0.2
        self.setPen(QPen(color, width))
        self.setZValue(z_value)

    def update_position(self) -> None:
        source_pos = self.source_item.scenePos()
        target_pos = self.target_item.scenePos()
        self.setLine(source_pos.x(), source_pos.y(), target_pos.x(), target_pos.y())


class NetworkNodeItem(QGraphicsEllipseItem):
    def __init__(self, radius: float):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.radius = radius
        self.edge_items: List[NetworkEdgeItem] = []
        self.label_item: Optional[QGraphicsSimpleTextItem] = None
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.ItemPositionHasChanged:
            for edge_item in self.edge_items:
                edge_item.update_position()
            if self.label_item is not None:
                self.label_item.setPos(self.x() - 30, self.y() + self.radius + 2)
        return super().itemChange(change, value)


class KGExplorerWindow(QMainWindow):
    query_result_signal = pyqtSignal(object, object, str)
    graph_load_progress_signal = pyqtSignal(str)
    graph_load_result_signal = pyqtSignal(str, object, object, object, int, str)

    def __init__(
        self,
        input_dir: str,
        query_dir: str,
        metadata_csv: str,
        graph_path: str = "",
    ):
        super().__init__()
        self.setWindowTitle("AKG Knowledge Graph Explorer")
        self.resize(1600, 950)

        self.input_dir = input_dir
        self.graph_dir = os.path.join(self.input_dir, "graph")
        self.query_dir = query_dir
        self.metadata_csv = metadata_csv

        self.graph_service = GraphDataService()
        self.query_service = QueryService(query_dir=query_dir)
        self.metadata_service = MetadataService(metadata_csv_path=metadata_csv)
        self.metadata_service.load()

        self.graph = None
        self.current_graph_path = ""
        self.available_graph_files: List[str] = []
        self.all_triples: List[Tuple[str, str, str]] = []
        self.filtered_triples: List[Tuple[str, str, str]] = []
        self.current_query_result = QueryResultTable(headers=[], rows=[])
        self.binning_metadata: Dict[str, Any] = {}
        self._network_node_lookup: Dict[str, NetworkNode] = {}
        self._network_node_items: Dict[str, NetworkNodeItem] = {}
        self._network_edge_items: List[NetworkEdgeItem] = []
        self._network_group_node_colors: Dict[str, QColor] = {}
        self._network_group_edge_colors: Dict[Tuple[str, str, str], QColor] = {}
        self._network_table_colors: Dict[str, QColor] = {}
        self._network_table_publications: Dict[str, str] = {}
        self._network_table_lineages: Dict[str, Set[str]] = {}
        self._network_table_children: Dict[str, Set[str]] = {}
        self._network_legend_table_links: Dict[str, str] = {}
        self._network_table_focus_identifiers: Set[str] = set()
        self._network_table_focus_tables: Set[str] = set()
        self._scope_publication_tables: Dict[str, List[str]] = {}
        self._scope_table_publication: Dict[str, str] = {}
        self._scope_table_lineages: Dict[str, Set[str]] = {}
        self._scope_table_row_counts: Dict[str, int] = {}
        self._gene_to_rows: Dict[str, Set[str]] = {}
        self._row_to_table: Dict[str, str] = {}
        self._table_to_rows: Dict[str, Set[str]] = {}
        self._row_logfc: Dict[str, str] = {}
        self._row_pvalue: Dict[str, str] = {}
        self._gene_publications: Dict[str, Set[str]] = {}
        self._gene_tables: Dict[str, Set[str]] = {}
        self._gene_row_counts: Dict[str, int] = {}
        self._gene_display_to_id: Dict[str, str] = {}
        self._last_scope_rebuild_seconds = 0.0
        self._overview_tree_updating = False
        self._triples_page_index = 0
        self._busy_cursor_depth = 0
        self._active_graph_worker: Optional[GraphLoadWorker] = None
        self._graph_loading_path = ""
        self._graph_load_started_at: Optional[float] = None
        self._startup_graph_path = ""
        self._selection_sync_active = False
        self._network_focus_identifiers: List[str] = []
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(180)
        self._filter_timer.timeout.connect(self.apply_filters)

        self.query_result_signal.connect(self.on_query_result)
        self.graph_load_progress_signal.connect(self.on_graph_load_progress)
        self.graph_load_result_signal.connect(self.on_graph_load_result)
        self._build_ui()
        self._populate_graph_list()

        self.settings_path = os.path.join(os.getcwd(), SETTINGS_FILE)
        self._load_settings()

        status_bar = self.statusBar()
        if status_bar is not None:
            font = QFont(status_bar.font())
            font.setPointSize(max(12, font.pointSize() + 2))
            status_bar.setFont(font)

        self._populate_query_list()
        self.query_status_label.setText("No graph loaded")
        if status_bar is not None:
            status_bar.showMessage("No graph loaded")

    def _load_startup_graph(self) -> None:
        startup_graph_path = self._startup_graph_path
        self._startup_graph_path = ""
        if startup_graph_path:
            self.load_graph(startup_graph_path)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        splitter = QSplitter()
        root.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Graph:"))
        self.graph_combo = QComboBox()
        self.graph_combo.setEditable(False)
        self.graph_combo.setMaximumWidth(560)
        top_bar.addWidget(self.graph_combo, 1)

        self.load_selected_button = QPushButton("Load Selected")
        self.load_selected_button.clicked.connect(self.on_load_selected_graph_clicked)
        top_bar.addWidget(self.load_selected_button)

        self.refresh_graphs_button = QPushButton("Refresh")
        self.refresh_graphs_button.clicked.connect(self.on_refresh_graphs_clicked)
        top_bar.addWidget(self.refresh_graphs_button)

        self.load_button = QPushButton("Load Graph (.nt)")
        self.load_button.clicked.connect(self.on_load_graph_clicked)
        top_bar.addWidget(self.load_button)
        top_bar.addStretch(1)
        left_layout.addLayout(top_bar)

        left_layout.addWidget(self._build_center_panel(), 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([820, 780])

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)

        overview_help = QLabel(
            "Select publications/tables to define working scope. "
            "Triples and Network views will use only this scope (within their current numeric limits)."
        )
        overview_help.setWordWrap(True)
        overview_layout.addWidget(overview_help)

        overview_actions = QHBoxLayout()
        self.overview_select_all_button = QPushButton("Select all")
        self.overview_select_all_button.clicked.connect(lambda: self._set_all_overview_tables(Qt.Checked))
        overview_actions.addWidget(self.overview_select_all_button)
        self.overview_select_none_button = QPushButton("Select none")
        self.overview_select_none_button.clicked.connect(lambda: self._set_all_overview_tables(Qt.Unchecked))
        overview_actions.addWidget(self.overview_select_none_button)
        overview_actions.addStretch(1)
        overview_layout.addLayout(overview_actions)

        self.overview_tree = QTreeWidget()
        self.overview_tree.setHeaderLabels(["Publication / Table", "Rows"])
        self.overview_tree.itemChanged.connect(self.on_overview_tree_item_changed)
        self.overview_tree.itemSelectionChanged.connect(self.on_overview_tree_selection_changed)
        overview_layout.addWidget(self.overview_tree, 1)

        self.overview_summary_label = QLabel("No graph loaded")
        self.overview_summary_label.setWordWrap(True)
        overview_layout.addWidget(self.overview_summary_label)

        self.tabs.addTab(overview_tab, "Overview")

        gene_tab = QWidget()
        self.gene_tab = gene_tab
        gene_layout = QVBoxLayout(gene_tab)

        gene_help = QLabel(
            "Choose a gene to list row, table, and publication provenance within the current Overview scope."
        )
        gene_help.setWordWrap(True)
        gene_layout.addWidget(gene_help)

        gene_controls = QHBoxLayout()
        gene_controls.addWidget(QLabel("Gene:"))

        self.gene_combo = QComboBox()
        self.gene_combo.setEditable(True)
        self.gene_combo.setMinimumWidth(420)
        self.gene_combo.setInsertPolicy(QComboBox.NoInsert)
        self.gene_combo.setPlaceholderText("Type or pick a gene URI in scope")
        gene_controls.addWidget(self.gene_combo, 1)

        self.gene_find_button = QPushButton("Find provenance")
        self.gene_find_button.clicked.connect(self.on_gene_find_clicked)
        self.gene_find_button.setEnabled(False)
        gene_controls.addWidget(self.gene_find_button)

        self.gene_refresh_button = QPushButton("Refresh genes")
        self.gene_refresh_button.clicked.connect(self.on_gene_refresh_clicked)
        self.gene_refresh_button.setEnabled(False)
        gene_controls.addWidget(self.gene_refresh_button)

        gene_layout.addLayout(gene_controls)

        self.gene_ranked_table = QTableWidget(0, 4)
        self.gene_ranked_table.setHorizontalHeaderLabels(["Gene", "Publications", "Tables", "Rows"])
        self.gene_ranked_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.gene_ranked_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gene_ranked_table.itemSelectionChanged.connect(self.on_gene_ranked_selection_changed)
        self.gene_ranked_table.itemDoubleClicked.connect(self.on_gene_ranked_item_double_clicked)
        gene_layout.addWidget(self.gene_ranked_table)

        self.gene_tree = QTreeWidget()
        self.gene_tree.setHeaderLabels(["Publication / Table / Row", "Count", "LogFC", "p-value"])
        self.gene_tree.itemDoubleClicked.connect(self.on_gene_tree_item_double_clicked)
        self.gene_tree.itemSelectionChanged.connect(self.on_gene_tree_selection_changed)
        gene_layout.addWidget(self.gene_tree, 1)

        self.gene_summary_label = QLabel("No graph loaded")
        self.gene_summary_label.setWordWrap(True)
        gene_layout.addWidget(self.gene_summary_label)

        self.tabs.addTab(gene_tab, "Gene")

        triples_tab = QWidget()
        self.triples_tab = triples_tab
        triples_layout = QVBoxLayout(triples_tab)

        filter_box = QGroupBox("Triple Filters")
        filter_layout = QGridLayout(filter_box)

        self.subject_filter = QLineEdit()
        self.subject_filter.setPlaceholderText("Contains text in subject")
        self.predicate_filter = QLineEdit()
        self.predicate_filter.setPlaceholderText("Contains text in predicate")
        self.object_filter = QLineEdit()
        self.object_filter.setPlaceholderText("Contains text in object")

        self.subject_filter.textChanged.connect(self.request_apply_filters)
        self.predicate_filter.textChanged.connect(self.request_apply_filters)
        self.object_filter.textChanged.connect(self.request_apply_filters)

        clear_filters_btn = QPushButton("Clear all")
        clear_filters_btn.clicked.connect(self.clear_filters)

        clear_subject_btn = QPushButton("Clear")
        clear_subject_btn.clicked.connect(lambda: self.clear_single_filter("subject"))
        clear_predicate_btn = QPushButton("Clear")
        clear_predicate_btn.clicked.connect(lambda: self.clear_single_filter("predicate"))
        clear_object_btn = QPushButton("Clear")
        clear_object_btn.clicked.connect(lambda: self.clear_single_filter("object"))

        filter_layout.addWidget(QLabel("Subject"), 0, 0)
        filter_layout.addWidget(self.subject_filter, 0, 1)
        filter_layout.addWidget(clear_subject_btn, 0, 2)
        filter_layout.addWidget(QLabel("Predicate"), 1, 0)
        filter_layout.addWidget(self.predicate_filter, 1, 1)
        filter_layout.addWidget(clear_predicate_btn, 1, 2)
        filter_layout.addWidget(QLabel("Object"), 2, 0)
        filter_layout.addWidget(self.object_filter, 2, 1)
        filter_layout.addWidget(clear_object_btn, 2, 2)

        quick_pred_row = QHBoxLayout()
        gene_pred_button = QPushButton("Gene")
        gene_pred_button.setToolTip("https://w3id.org/biolink/vocab/Gene")
        gene_pred_button.clicked.connect(lambda: self.set_predicate_filter_preset("https://w3id.org/biolink/vocab/Gene"))
        quick_pred_row.addWidget(gene_pred_button)

        logfc_pred_button = QPushButton("LogFC")
        logfc_pred_button.setToolTip("http://edamontology.org/data_3754")
        logfc_pred_button.clicked.connect(lambda: self.set_predicate_filter_preset("http://edamontology.org/data_3754"))
        quick_pred_row.addWidget(logfc_pred_button)

        pvalue_pred_button = QPushButton("P-value")
        pvalue_pred_button.setToolTip("http://edamontology.org/data_1669")
        pvalue_pred_button.clicked.connect(lambda: self.set_predicate_filter_preset("http://edamontology.org/data_1669"))
        quick_pred_row.addWidget(pvalue_pred_button)

        clear_pred_button = QPushButton("Clear predicate")
        clear_pred_button.clicked.connect(lambda: self.set_predicate_filter_preset(""))
        quick_pred_row.addWidget(clear_pred_button)
        quick_pred_row.addStretch(1)

        filter_layout.addWidget(QLabel("Quick predicates"), 3, 0)
        filter_layout.addLayout(quick_pred_row, 3, 1)
        filter_layout.addWidget(clear_filters_btn, 3, 2)

        triples_layout.addWidget(filter_box)

        triples_nav = QHBoxLayout()
        self.triples_count_label = QLabel("Triples: 0")
        triples_nav.addWidget(self.triples_count_label, 1)

        self.triples_first_button = QPushButton("First")
        self.triples_first_button.setEnabled(False)
        self.triples_first_button.clicked.connect(self.on_triples_first_page)
        triples_nav.addWidget(self.triples_first_button)

        self.triples_prev_button = QPushButton("Prev")
        self.triples_prev_button.setEnabled(False)
        self.triples_prev_button.clicked.connect(self.on_triples_prev_page)
        triples_nav.addWidget(self.triples_prev_button)

        self.triples_page_label = QLabel("Page 1/1")
        triples_nav.addWidget(self.triples_page_label)

        self.triples_next_button = QPushButton("Next")
        self.triples_next_button.setEnabled(False)
        self.triples_next_button.clicked.connect(self.on_triples_next_page)
        triples_nav.addWidget(self.triples_next_button)

        self.triples_last_button = QPushButton("Last")
        self.triples_last_button.setEnabled(False)
        self.triples_last_button.clicked.connect(self.on_triples_last_page)
        triples_nav.addWidget(self.triples_last_button)

        triples_layout.addLayout(triples_nav)

        self.triples_table = QTableWidget(0, 3)
        self.triples_table.setHorizontalHeaderLabels(["Subject", "Predicate", "Object"])
        self.triples_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.triples_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.triples_table.itemSelectionChanged.connect(self.on_triples_selection_changed)
        triples_layout.addWidget(self.triples_table, 1)

        self.tabs.addTab(triples_tab, "Triples")

        query_tab = QWidget()
        self.query_tab = query_tab
        query_outer = QHBoxLayout(query_tab)

        query_group = QGroupBox("Preset SPARQL Queries")
        query_group_layout = QVBoxLayout(query_group)

        self.query_list = QListWidget()
        self.query_list.currentItemChanged.connect(self.on_query_preset_changed)
        query_group_layout.addWidget(self.query_list, 1)

        pmid_row = QHBoxLayout()
        pmid_row.addWidget(QLabel("PMID:"))
        self.pmid_input = QLineEdit()
        self.pmid_input.setPlaceholderText("Optional, for parameterized queries")
        pmid_row.addWidget(self.pmid_input, 1)
        query_group_layout.addLayout(pmid_row)

        self.run_query_button = QPushButton("Run Selected Query")
        self.run_query_button.clicked.connect(self.on_run_query_clicked)
        query_group_layout.addWidget(self.run_query_button)

        self.export_button = QPushButton("Export Query Results to CSV")
        self.export_button.clicked.connect(self.on_export_csv_clicked)
        query_group_layout.addWidget(self.export_button)

        self.query_status_label = QLabel("Choose a query and click Run")
        self.query_status_label.setWordWrap(True)
        query_group_layout.addWidget(self.query_status_label)

        query_outer.addWidget(query_group)

        query_right_panel = QWidget()
        query_right_layout = QVBoxLayout(query_right_panel)
        query_right_layout.setContentsMargins(0, 0, 0, 0)

        query_right_layout.addWidget(QLabel("Query Text (editable)"))
        self.query_text_editor = QTextEdit()
        self.query_text_editor.setPlaceholderText("Select a query from the left to load it here")
        self.query_text_editor.setAcceptRichText(False)
        self.query_text_editor.setMinimumHeight(160)
        query_right_layout.addWidget(self.query_text_editor)

        query_right_layout.addWidget(QLabel("Results"))

        self.query_results_table = QTableWidget(0, 0)
        self.query_results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.query_results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.query_results_table.itemSelectionChanged.connect(self.on_query_selection_changed)
        query_right_layout.addWidget(self.query_results_table, 1)

        query_outer.addWidget(query_right_panel, 1)

        self.tabs.addTab(query_tab, "Queries")
        self.tabs.setCurrentIndex(0)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        right_splitter = QSplitter(Qt.Vertical)

        detail_panel = QWidget()
        row_layout = QVBoxLayout(detail_panel)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_text = QTextBrowser()
        self.detail_text.setReadOnly(True)
        self.detail_text.setOpenExternalLinks(True)
        row_layout.addWidget(self.detail_text)

        network_panel = QWidget()
        network_layout = QVBoxLayout(network_panel)
        network_layout.setContentsMargins(0, 0, 0, 0)

        network_controls = QHBoxLayout()
        network_controls.addWidget(QLabel("Max edges:"))
        self.network_edge_limit = QSpinBox()
        self.network_edge_limit.setRange(10, 5000)
        self.network_edge_limit.setValue(DEFAULT_NETWORK_MAX_EDGES)
        self.network_edge_limit.valueChanged.connect(self.refresh_network_view)
        network_controls.addWidget(self.network_edge_limit)

        self.network_summary_label = QLabel("Nodes: 0 | Edges: 0")
        self.network_summary_label.setWordWrap(True)
        network_controls.addWidget(self.network_summary_label, 1)

        clear_network_selection_button = QPushButton("Clear selection")
        clear_network_selection_button.clicked.connect(self.on_clear_network_selection_clicked)
        network_controls.addWidget(clear_network_selection_button)

        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(self.fit_network_view)
        network_controls.addWidget(fit_button)

        network_controls.addWidget(QLabel("View:"))
        self.network_detail_mode = QComboBox()
        self.network_detail_mode.addItem("Overview", "overview")
        self.network_detail_mode.addItem("Tables", "tables")
        self.network_detail_mode.addItem("Full", "full")
        self.network_detail_mode.setCurrentIndex(0)
        self.network_detail_mode.setToolTip(
            "Overview: publications and table roots only.\n"
            "Tables: add direct children of table roots.\n"
            "Full: show all nodes."
        )
        self.network_detail_mode.currentIndexChanged.connect(self.refresh_network_view)
        network_controls.addWidget(self.network_detail_mode)

        network_layout.addLayout(network_controls)

        self.network_legend_text = QTextBrowser()
        self.network_legend_text.setReadOnly(True)
        self.network_legend_text.setOpenLinks(False)
        self.network_legend_text.setOpenExternalLinks(False)
        self.network_legend_text.setMaximumHeight(150)
        self.network_legend_text.setPlaceholderText("Table color legend will appear after graph render")
        self.network_legend_text.anchorClicked.connect(self.on_network_legend_link_clicked)
        network_layout.addWidget(self.network_legend_text)

        self.network_scene = QGraphicsScene(self)
        self.network_scene.selectionChanged.connect(self.on_network_selection_changed)
        self.network_view = NetworkGraphicsView(self.network_scene)
        self.network_view.setRenderHint(QPainter.Antialiasing, True)
        self.network_view.setToolTip("Wheel: zoom | Middle-drag: pan | Ctrl+= zoom in | Ctrl+- zoom out | Ctrl+0 fit")
        network_layout.addWidget(self.network_view, 1)

        self.network_zoom_in_shortcut = QShortcut(QKeySequence("Ctrl++"), self.network_view)
        self.network_zoom_in_shortcut.activated.connect(lambda: self.zoom_network(1.15))
        self.network_zoom_in_shortcut_alt = QShortcut(QKeySequence("Ctrl+="), self.network_view)
        self.network_zoom_in_shortcut_alt.activated.connect(lambda: self.zoom_network(1.15))
        self.network_zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self.network_view)
        self.network_zoom_out_shortcut.activated.connect(lambda: self.zoom_network(1 / 1.15))
        self.network_zoom_reset_shortcut = QShortcut(QKeySequence("Ctrl+0"), self.network_view)
        self.network_zoom_reset_shortcut.activated.connect(self.reset_network_zoom)

        right_splitter.addWidget(detail_panel)
        right_splitter.addWidget(network_panel)
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 4)
        right_splitter.setSizes([220, 640])

        layout.addWidget(right_splitter, 1)
        return panel

    def _populate_query_list(self) -> None:
        self.query_list.clear()
        for query_name in self.query_service.list_query_files():
            self.query_list.addItem(query_name)
        if self.query_list.count() > 0:
            self.query_list.setCurrentRow(0)

    def on_query_preset_changed(self, current: Any, previous: Any = None) -> None:
        del previous
        if current is None:
            self.query_text_editor.clear()
            return

        query_name = current.text().strip()
        if not query_name:
            self.query_text_editor.clear()
            return

        try:
            query_text = self.query_service.load_query_text(query_name)
        except Exception as exc:
            self.query_status_label.setText(f"Could not load query text: {exc}")
            self.query_text_editor.clear()
            return

        self.query_text_editor.setPlainText(query_text)

    def _populate_graph_list(self) -> None:
        current = self.graph_combo.currentText().strip()
        self.graph_combo.blockSignals(True)
        self.graph_combo.clear()

        self.available_graph_files = []
        if os.path.isdir(self.graph_dir):
            self.available_graph_files = sorted(
                [name for name in os.listdir(self.graph_dir) if name.lower().endswith(".nt")]
            )

        if self.available_graph_files:
            self.graph_combo.addItems(self.available_graph_files)
            if current and current in self.available_graph_files:
                self.graph_combo.setCurrentText(current)
            else:
                self.graph_combo.setCurrentIndex(0)
            self.load_selected_button.setEnabled(True)
        else:
            self.graph_combo.addItem("(no .nt files found)")
            self.load_selected_button.setEnabled(False)

        self.graph_combo.blockSignals(False)

    def on_refresh_graphs_clicked(self) -> None:
        self._populate_graph_list()
        if self.available_graph_files:
            self.query_status_label.setText(f"Found {len(self.available_graph_files)} graph files in {self.graph_dir}")
        else:
            self.query_status_label.setText(f"No .nt files found in {self.graph_dir}")

    def on_load_selected_graph_clicked(self) -> None:
        if not self.available_graph_files:
            QMessageBox.information(self, "No Graphs", f"No .nt files found in {self.graph_dir}")
            return

        selected_name = self.graph_combo.currentText().strip()
        if not selected_name:
            selected_name = self.available_graph_files[0]

        graph_path = os.path.join(self.graph_dir, selected_name)
        self.load_graph(graph_path)

    def on_load_graph_clicked(self) -> None:
        start_dir = self.graph_dir if os.path.isdir(self.graph_dir) else os.getcwd()
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open RDF Graph",
            start_dir,
            "N-Triples (*.nt);;All Files (*.*)",
        )
        if filename:
            self.load_graph(filename)
            self._populate_graph_list()

    def load_graph(self, graph_path: str) -> None:
        if graph_path and not os.path.isabs(graph_path):
            candidate = os.path.join(self.graph_dir, graph_path)
            if os.path.exists(candidate):
                graph_path = candidate

        if self._active_graph_worker is not None:
            QMessageBox.information(self, "Graph Loading", f"Already loading graph: {self._graph_loading_path}")
            return

        self._graph_loading_path = graph_path
        self._graph_load_started_at = perf_counter()
        self._set_graph_loading_state(True)
        self.statusBar().showMessage(f"Loading graph: {graph_path}")

        worker = GraphLoadWorker(
            graph_path=graph_path,
            input_dir=self.input_dir,
            graph_service=self.graph_service,
            progress_callback=self.graph_load_progress_signal.emit,
            callback=self.graph_load_result_signal.emit,
        )
        self._active_graph_worker = worker
        worker.start()

    def on_graph_load_progress(self, message: str) -> None:
        self.statusBar().showMessage(message)
        self.query_status_label.setText(message)

    def on_graph_load_result(
        self,
        graph_path: str,
        graph: Any,
        all_triples: List[Tuple[str, str, str]],
        binning_metadata: Dict[str, Any],
        sidecar_count: int,
        error: str,
    ) -> None:
        self._active_graph_worker = None
        self._graph_loading_path = ""

        if error:
            self._graph_load_started_at = None
            self._set_graph_loading_state(False)
            self.statusBar().showMessage(f"Graph load failed: {error}")
            QMessageBox.critical(self, "Load Error", error)
            return

        self.graph = graph
        self.current_graph_path = graph_path
        self.binning_metadata = binning_metadata
        self.all_triples = all_triples
        self.filtered_triples = list(self.all_triples)

        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage("Building overview scope and provenance indexes...")
        scope_rebuild_started = perf_counter()
        self._rebuild_scope_hierarchy()
        self._last_scope_rebuild_seconds = perf_counter() - scope_rebuild_started
        self._populate_overview_tree()
        self._refresh_gene_scope_options()

        total_load_seconds = 0.0
        if self._graph_load_started_at is not None:
            total_load_seconds = perf_counter() - self._graph_load_started_at
        self._graph_load_started_at = None

        if os.path.isdir(self.graph_dir):
            graph_name = os.path.basename(graph_path)
            if graph_name.lower().endswith(".nt"):
                if graph_name not in self.available_graph_files:
                    self._populate_graph_list()
                if graph_name in self.available_graph_files:
                    self.graph_combo.setCurrentText(graph_name)

        load_message = (
            f"Loaded {os.path.basename(graph_path)}: {len(self.all_triples)} triples, "
            f"{len(self._gene_to_rows)} genes indexed, {len(self._row_to_table)} row links, "
            f"scope build {self._last_scope_rebuild_seconds:.2f}s, total load {total_load_seconds:.2f}s, "
            f"sidecars checked: {sidecar_count}"
        )
        if status_bar is not None:
            status_bar.showMessage(load_message)
        self.query_status_label.setText(
            f"Graph loaded: {os.path.basename(graph_path)} | scope build {self._last_scope_rebuild_seconds:.2f}s"
        )
        self._set_graph_loading_state(False)
        self.apply_filters()

    def _set_graph_loading_state(self, is_loading: bool) -> None:
        self.load_button.setEnabled(not is_loading)
        self.load_selected_button.setEnabled((not is_loading) and bool(self.available_graph_files))
        self.refresh_graphs_button.setEnabled(not is_loading)
        self.graph_combo.setEnabled(not is_loading)
        self.run_query_button.setEnabled((not is_loading) and self.graph is not None)
        self.export_button.setEnabled(not is_loading)
        self.gene_find_button.setEnabled((not is_loading) and self.graph is not None)
        self.gene_refresh_button.setEnabled((not is_loading) and self.graph is not None)
        self.gene_ranked_table.setEnabled((not is_loading) and self.graph is not None)

    def _load_binning_metadata(self, graph_path: str) -> None:
        self.binning_metadata = self.graph_service.load_binning_metadata(graph_path)

    def request_apply_filters(self) -> None:
        self._filter_timer.start()

    def apply_filters(self) -> None:
        self._reset_triples_paging()
        sf = self.subject_filter.text().strip().lower()
        pf = self.predicate_filter.text().strip().lower()
        of = self.object_filter.text().strip().lower()

        if not sf and not pf and not of:
            self.filtered_triples = self._apply_scope_selection(self.all_triples)
            self._render_current_triples_table()
            self.refresh_network_view()
            return

        display_cache: Dict[str, str] = {}

        def display_for(value: str) -> str:
            cached = display_cache.get(value)
            if cached is not None:
                return cached
            resolved = self.graph_service.display_value_with_uuid_context(
                value,
                input_dir=self.input_dir,
                graph_path=self.current_graph_path,
                resolve_row_context=True,
            )
            display_cache[value] = resolved
            return resolved

        def matches(value: str, needle: str) -> bool:
            if not needle:
                return True
            raw_lower = value.lower()
            if needle in raw_lower:
                return True
            return needle in display_for(value).lower()

        filtered: List[Tuple[str, str, str]] = []
        for subj, pred, obj in self.all_triples:
            if not matches(subj, sf):
                continue
            if not matches(pred, pf):
                continue
            if not matches(obj, of):
                continue
            filtered.append((subj, pred, obj))

        self.filtered_triples = self._apply_scope_selection(filtered)
        self._render_current_triples_table()
        self.refresh_network_view()

    def clear_filters(self) -> None:
        self._filter_timer.stop()
        self.subject_filter.blockSignals(True)
        self.predicate_filter.blockSignals(True)
        self.object_filter.blockSignals(True)
        try:
            self.subject_filter.clear()
            self.predicate_filter.clear()
            self.object_filter.clear()
        finally:
            self.object_filter.blockSignals(False)
            self.predicate_filter.blockSignals(False)
            self.subject_filter.blockSignals(False)
        self.apply_filters()

    def clear_single_filter(self, field_name: str) -> None:
        if field_name == "subject":
            self.subject_filter.clear()
            return
        if field_name == "predicate":
            self.predicate_filter.clear()
            return
        if field_name == "object":
            self.object_filter.clear()

    def on_clear_network_selection_clicked(self) -> None:
        self._network_focus_identifiers = []
        self._network_table_focus_identifiers = set()
        self._network_table_focus_tables = set()
        self._select_network_nodes([])
        self._render_network_legend()
        self._set_html_text(self.detail_text, "")
        self._reset_triples_paging()
        self._render_current_triples_table()
        self._clear_triples_table_selection()

    def set_predicate_filter_preset(self, predicate: str) -> None:
        self.predicate_filter.setText(predicate)
        self.predicate_filter.setFocus()
        self.predicate_filter.selectAll()

    def _rebuild_scope_hierarchy(self) -> None:
        provenance = self.graph_service.build_provenance_index(self.all_triples)
        self._scope_publication_tables = provenance.publication_tables
        self._scope_table_publication = provenance.table_publication
        self._scope_table_lineages = provenance.table_lineages
        self._scope_table_row_counts = provenance.table_row_counts
        self._gene_to_rows = provenance.gene_to_rows
        self._row_to_table = provenance.row_to_table
        self._table_to_rows = provenance.table_to_rows
        self._row_logfc = provenance.row_logfc
        self._row_pvalue = provenance.row_pvalue
        self._gene_publications = provenance.gene_publications
        self._gene_tables = provenance.gene_tables
        self._gene_row_counts = provenance.gene_row_counts

    def _populate_overview_tree(self) -> None:
        previous_selection = self._selected_table_ids()
        has_existing_tree = self.overview_tree.topLevelItemCount() > 0

        self._overview_tree_updating = True
        try:
            self.overview_tree.clear()
            total_tables = 0

            for publication_id, table_ids in self._scope_publication_tables.items():
                pub_label = self.graph_service.display_value_with_uuid_context(
                    publication_id,
                    input_dir=self.input_dir,
                    graph_path=self.current_graph_path,
                    resolve_row_context=True,
                )
                pub_item = QTreeWidgetItem([pub_label, ""])
                pub_item.setData(0, OVERVIEW_KIND_ROLE, "publication")
                pub_item.setData(0, OVERVIEW_ID_ROLE, publication_id)
                pub_item.setFlags(pub_item.flags() | Qt.ItemIsUserCheckable)

                for table_id in table_ids:
                    table_label = self.graph_service.display_value_with_uuid_context(
                        table_id,
                        input_dir=self.input_dir,
                        graph_path=self.current_graph_path,
                        resolve_row_context=True,
                    )
                    row_count = self._scope_table_row_counts.get(table_id, 0)
                    table_item = QTreeWidgetItem([table_label, str(row_count)])
                    table_item.setData(0, OVERVIEW_KIND_ROLE, "table")
                    table_item.setData(0, OVERVIEW_ID_ROLE, table_id)
                    table_item.setFlags(table_item.flags() | Qt.ItemIsUserCheckable)

                    is_checked = True
                    if has_existing_tree:
                        is_checked = table_id in previous_selection
                    table_item.setCheckState(0, Qt.Checked if is_checked else Qt.Unchecked)

                    pub_item.addChild(table_item)
                    total_tables += 1

                self._refresh_publication_check_state(pub_item)
                self.overview_tree.addTopLevelItem(pub_item)

            self.overview_tree.expandAll()
            self.overview_tree.resizeColumnToContents(0)
            self.overview_summary_label.setText(
                f"Publications: {len(self._scope_publication_tables)} | "
                f"Tables: {total_tables} | Selected tables: {len(self._selected_table_ids())}"
            )
        finally:
            self._overview_tree_updating = False

    def _set_all_overview_tables(self, state: Qt.CheckState) -> None:
        self._overview_tree_updating = True
        try:
            for top_idx in range(self.overview_tree.topLevelItemCount()):
                pub_item = self.overview_tree.topLevelItem(top_idx)
                for child_idx in range(pub_item.childCount()):
                    table_item = pub_item.child(child_idx)
                    if table_item.data(0, OVERVIEW_KIND_ROLE) == "table":
                        table_item.setCheckState(0, state)
                self._refresh_publication_check_state(pub_item)
        finally:
            self._overview_tree_updating = False
        self._refresh_overview_summary()
        self._begin_busy_cursor("Applying overview scope...")
        try:
            self.apply_filters()
            self._refresh_gene_scope_options()
        finally:
            self._end_busy_cursor(f"Scope applied: {len(self.filtered_triples)} triples")

    def _refresh_publication_check_state(self, publication_item: QTreeWidgetItem) -> None:
        checked = 0
        partial = 0
        total = 0
        for child_idx in range(publication_item.childCount()):
            child = publication_item.child(child_idx)
            if child.data(0, OVERVIEW_KIND_ROLE) != "table":
                continue
            total += 1
            state = child.checkState(0)
            if state == Qt.Checked:
                checked += 1
            elif state == Qt.PartiallyChecked:
                partial += 1

        if total == 0:
            publication_item.setCheckState(0, Qt.Unchecked)
            return
        if checked == total:
            publication_item.setCheckState(0, Qt.Checked)
            return
        if checked == 0 and partial == 0:
            publication_item.setCheckState(0, Qt.Unchecked)
            return
        publication_item.setCheckState(0, Qt.PartiallyChecked)

    def _refresh_overview_summary(self) -> None:
        total_tables = sum(len(tables) for tables in self._scope_publication_tables.values())
        self.overview_summary_label.setText(
            f"Publications: {len(self._scope_publication_tables)} | "
            f"Tables: {total_tables} | Selected tables: {len(self._selected_table_ids())}"
        )

    def on_overview_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._overview_tree_updating:
            return

        kind = item.data(0, OVERVIEW_KIND_ROLE)
        if kind == "publication":
            state = item.checkState(0)
            if state in (Qt.Checked, Qt.Unchecked):
                self._overview_tree_updating = True
                try:
                    for child_idx in range(item.childCount()):
                        child = item.child(child_idx)
                        if child.data(0, OVERVIEW_KIND_ROLE) == "table":
                            child.setCheckState(0, state)
                finally:
                    self._overview_tree_updating = False
        elif kind == "table":
            parent = item.parent()
            if parent is not None:
                self._overview_tree_updating = True
                try:
                    self._refresh_publication_check_state(parent)
                finally:
                    self._overview_tree_updating = False

        self._refresh_overview_summary()
        self._begin_busy_cursor("Applying overview scope...")
        try:
            self.apply_filters()
            self._refresh_gene_scope_options()
        finally:
            self._end_busy_cursor(f"Scope applied: {len(self.filtered_triples)} triples")

    def on_overview_tree_selection_changed(self) -> None:
        selected_publications: List[str] = []
        for item in self.overview_tree.selectedItems():
            if item.data(0, OVERVIEW_KIND_ROLE) != "publication":
                continue
            publication_id = str(item.data(0, OVERVIEW_ID_ROLE) or "")
            if publication_id:
                selected_publications.append(publication_id)

        if selected_publications:
            self._update_detail_and_metadata([selected_publications[0]])

    def on_gene_refresh_clicked(self) -> None:
        self._refresh_gene_scope_options()

    def _refresh_gene_scope_options(self) -> None:
        current_gene_id = self._resolve_selected_gene_id()
        selected_tables = self._selected_table_ids()

        self.gene_combo.blockSignals(True)
        try:
            self.gene_combo.clear()
            self.gene_tree.clear()
            self.gene_ranked_table.setRowCount(0)
            self._gene_display_to_id = {}

            if self.graph is None:
                self.gene_summary_label.setText("No graph loaded")
                return

            if not selected_tables:
                self.gene_summary_label.setText("No tables selected in Overview")
                return

            scoped_rows: Set[str] = set()
            for table_id in selected_tables:
                scoped_rows.update(self._table_to_rows.get(table_id, set()))

            scoped_genes: List[str] = []
            for gene_id, row_ids in self._gene_to_rows.items():
                if row_ids.intersection(scoped_rows):
                    scoped_genes.append(gene_id)

            scoped_genes.sort(key=self.graph_service.gene_sort_key)
            for gene_id in scoped_genes:
                label = self.graph_service.format_gene_display(gene_id)
                self.gene_combo.addItem(label, gene_id)
                self._gene_display_to_id[label] = gene_id

            if current_gene_id and current_gene_id in scoped_genes:
                for idx in range(self.gene_combo.count()):
                    item_gene_id = self.gene_combo.itemData(idx)
                    if isinstance(item_gene_id, str) and item_gene_id == current_gene_id:
                        self.gene_combo.setCurrentIndex(idx)
                        break
            elif scoped_genes:
                self.gene_combo.setCurrentIndex(0)

            self._populate_gene_ranked_table(scoped_genes, selected_tables, current_gene_id)

            self.gene_summary_label.setText(f"Genes in current scope: {len(scoped_genes)}")
        finally:
            self.gene_combo.blockSignals(False)

    def on_gene_find_clicked(self) -> None:
        gene_id = self._resolve_selected_gene_id()
        if not gene_id:
            self.gene_summary_label.setText("Enter or select a gene first")
            return
        self._set_gene_combo_to_gene_id(gene_id)
        self._select_gene_ranked_row(gene_id)
        self._populate_gene_provenance_tree(gene_id)

    def _set_gene_combo_to_gene_id(self, gene_id: str) -> None:
        for idx in range(self.gene_combo.count()):
            item_gene_id = self.gene_combo.itemData(idx)
            if isinstance(item_gene_id, str) and item_gene_id == gene_id:
                self.gene_combo.setCurrentIndex(idx)
                return

    def _scoped_gene_counts(self, gene_id: str, selected_tables: Set[str]) -> Tuple[int, int, int]:
        scoped_tables = self._gene_tables.get(gene_id, set()).intersection(selected_tables)
        scoped_publications: Set[str] = set()
        for table_id in scoped_tables:
            publication_id = self._scope_table_publication.get(table_id, "")
            if publication_id:
                scoped_publications.add(publication_id)

        scoped_rows = 0
        for row_id in self._gene_to_rows.get(gene_id, set()):
            if self._row_to_table.get(row_id, "") in selected_tables:
                scoped_rows += 1

        return len(scoped_publications), len(scoped_tables), scoped_rows

    def _populate_gene_ranked_table(
        self,
        scoped_genes: List[str],
        selected_tables: Set[str],
        selected_gene_id: str,
    ) -> None:
        rows: List[Tuple[str, int, int, int]] = []
        for gene_id in scoped_genes:
            pub_count, table_count, row_count = self._scoped_gene_counts(gene_id, selected_tables)
            rows.append((gene_id, pub_count, table_count, row_count))

        rows.sort(
            key=lambda item: (-item[1], -item[2], -item[3], self.graph_service.gene_sort_key(item[0]))
        )

        self.gene_ranked_table.blockSignals(True)
        try:
            self.gene_ranked_table.setRowCount(len(rows))
            for row_idx, (gene_id, pub_count, table_count, row_count) in enumerate(rows):
                gene_label = self.graph_service.format_gene_display(gene_id)
                gene_item = self._make_table_item(gene_label, raw_value=gene_id, display_override=gene_label)
                self.gene_ranked_table.setItem(row_idx, 0, gene_item)
                self.gene_ranked_table.setItem(row_idx, 1, self._make_table_item(str(pub_count), raw_value=str(pub_count)))
                self.gene_ranked_table.setItem(row_idx, 2, self._make_table_item(str(table_count), raw_value=str(table_count)))
                self.gene_ranked_table.setItem(row_idx, 3, self._make_table_item(str(row_count), raw_value=str(row_count)))

            if len(rows) <= 1000:
                self.gene_ranked_table.resizeColumnsToContents()
            self.gene_ranked_table.setColumnWidth(0, max(self.gene_ranked_table.columnWidth(0), 420))
        finally:
            self.gene_ranked_table.blockSignals(False)

        if selected_gene_id:
            self._select_gene_ranked_row(selected_gene_id)

    def _select_gene_ranked_row(self, gene_id: str) -> None:
        self.gene_ranked_table.blockSignals(True)
        try:
            self.gene_ranked_table.clearSelection()
            for row_idx in range(self.gene_ranked_table.rowCount()):
                item = self.gene_ranked_table.item(row_idx, 0)
                if item is None:
                    continue
                raw_gene_id = item.data(ITEM_USER_ROLE)
                if isinstance(raw_gene_id, str) and raw_gene_id == gene_id:
                    self.gene_ranked_table.selectRow(row_idx)
                    self.gene_ranked_table.scrollToItem(item)
                    break
        finally:
            self.gene_ranked_table.blockSignals(False)

    def on_gene_ranked_selection_changed(self) -> None:
        row_idx = self.gene_ranked_table.currentRow()
        if row_idx < 0:
            return

        item = self.gene_ranked_table.item(row_idx, 0)
        if item is None:
            return
        gene_id = item.data(ITEM_USER_ROLE)
        if isinstance(gene_id, str) and gene_id:
            self._set_gene_combo_to_gene_id(gene_id)

    def on_gene_ranked_item_double_clicked(self, item: QTableWidgetItem) -> None:
        row_idx = item.row()
        gene_item = self.gene_ranked_table.item(row_idx, 0)
        if gene_item is None:
            return
        gene_id = gene_item.data(ITEM_USER_ROLE)
        if isinstance(gene_id, str) and gene_id:
            self._set_gene_combo_to_gene_id(gene_id)
            self._populate_gene_provenance_tree(gene_id)

    def _resolve_selected_gene_id(self) -> str:
        current_text = self.gene_combo.currentText().strip()
        if not current_text:
            return ""

        current_idx = self.gene_combo.currentIndex()
        if current_idx >= 0 and current_text == self.gene_combo.itemText(current_idx):
            item_gene_id = self.gene_combo.itemData(current_idx)
            if isinstance(item_gene_id, str) and item_gene_id:
                return item_gene_id

        mapped_gene_id = self._gene_display_to_id.get(current_text)
        if mapped_gene_id:
            return mapped_gene_id

        if current_text.upper().startswith("HGNC:"):
            wanted_hgnc_id = current_text.upper()
            for gene_id in self._gene_to_rows:
                if self.graph_service.extract_hgnc_id(gene_id) == wanted_hgnc_id:
                    return gene_id

        return current_text

    def _populate_gene_provenance_tree(self, gene_id: str) -> None:
        self.gene_tree.clear()

        selected_tables = self._selected_table_ids()
        if not selected_tables:
            self.gene_summary_label.setText("No tables selected in Overview")
            return

        row_ids = self._gene_to_rows.get(gene_id, set())
        if not row_ids:
            self.gene_summary_label.setText("Gene not found in current graph")
            return

        grouped: Dict[str, Dict[str, List[str]]] = {}
        scoped_row_count = 0

        for row_id in sorted(row_ids):
            table_id = self._row_to_table.get(row_id, "")
            if not table_id or table_id not in selected_tables:
                continue

            publication_id = self._scope_table_publication.get(table_id, "")
            grouped.setdefault(publication_id, {}).setdefault(table_id, []).append(row_id)
            scoped_row_count += 1

        if not grouped:
            self.gene_summary_label.setText("Gene not present in currently selected Overview scope")
            return

        for publication_id in sorted(grouped.keys()):
            pub_rows = sum(len(rows) for rows in grouped[publication_id].values())
            publication_label = self.graph_service.display_value_with_uuid_context(
                publication_id,
                input_dir=self.input_dir,
                graph_path=self.current_graph_path,
                resolve_row_context=True,
            )
            pub_item = QTreeWidgetItem([publication_label, str(pub_rows), "", ""])
            pub_item.setData(0, OVERVIEW_KIND_ROLE, "gene_publication")
            pub_item.setData(0, OVERVIEW_ID_ROLE, publication_id)

            for table_id in sorted(grouped[publication_id].keys()):
                table_rows = grouped[publication_id][table_id]
                sorted_table_rows = sorted(table_rows, key=self._gene_row_sort_key)
                table_label = self.graph_service.display_value_with_uuid_context(
                    table_id,
                    input_dir=self.input_dir,
                    graph_path=self.current_graph_path,
                    resolve_row_context=True,
                )
                table_item = QTreeWidgetItem([table_label, str(len(table_rows)), "", ""])
                table_item.setData(0, OVERVIEW_KIND_ROLE, "gene_table")
                table_item.setData(0, OVERVIEW_ID_ROLE, table_id)

                for row_id in sorted_table_rows:
                    row_label = self.graph_service.display_value_with_uuid_context(
                        row_id,
                        input_dir=self.input_dir,
                        graph_path=self.current_graph_path,
                        resolve_row_context=True,
                    )
                    row_logfc = self._row_logfc.get(row_id, "")
                    row_pvalue = self._row_pvalue.get(row_id, "")
                    row_item = QTreeWidgetItem([row_label, "1", row_logfc, row_pvalue])
                    row_item.setData(0, OVERVIEW_KIND_ROLE, "gene_row")
                    row_item.setData(0, OVERVIEW_ID_ROLE, row_id)
                    table_item.addChild(row_item)

                pub_item.addChild(table_item)

            self.gene_tree.addTopLevelItem(pub_item)

        self.gene_tree.expandToDepth(1)
        self.gene_tree.resizeColumnToContents(0)
        self.gene_tree.resizeColumnToContents(1)
        self.gene_tree.resizeColumnToContents(2)
        self.gene_tree.resizeColumnToContents(3)

        table_count = sum(len(tables) for tables in grouped.values())
        publication_count = len(grouped)
        self.gene_summary_label.setText(
            f"Gene provenance for {gene_id}: {publication_count} publications | "
            f"{table_count} tables | {scoped_row_count} rows"
        )

    def on_gene_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        del column

        kind = item.data(0, OVERVIEW_KIND_ROLE)
        identifier = str(item.data(0, OVERVIEW_ID_ROLE) or "")
        if not identifier:
            return

        if kind == "gene_row":
            self._selection_sync_active = True
            try:
                self._network_focus_identifiers = [identifier]
                self._set_triples_page_for_identifiers([identifier])
                self._render_current_triples_table()
                self.tabs.setCurrentWidget(self.triples_tab)
                self._select_triple_rows_for_identifiers([identifier])
            finally:
                self._selection_sync_active = False
            return

        if kind == "gene_table":
            self._focus_table_lineage(identifier)

    @staticmethod
    def _parse_metric_numeric(value: str) -> Optional[float]:
        text = str(value).strip()
        if not text:
            return None

        try:
            return float(text)
        except ValueError:
            pass

        lower = text.lower()
        if lower.startswith("bin_"):
            suffix = lower.split("_", 1)[1]
            if suffix.isdigit():
                return float(int(suffix))
        return None

    def _gene_row_sort_key(self, row_id: str) -> Tuple[float, float, str]:
        logfc_text = self._row_logfc.get(row_id, "")
        pvalue_text = self._row_pvalue.get(row_id, "")

        logfc_num = self._parse_metric_numeric(logfc_text)
        pvalue_num = self._parse_metric_numeric(pvalue_text)

        abs_logfc = abs(logfc_num) if logfc_num is not None else float("-inf")
        pvalue_sort = pvalue_num if pvalue_num is not None else float("inf")
        return (-abs_logfc, pvalue_sort, row_id)

    def on_gene_tree_selection_changed(self) -> None:
        selected_publications: List[str] = []
        for item in self.gene_tree.selectedItems():
            if item.data(0, OVERVIEW_KIND_ROLE) != "gene_publication":
                continue
            publication_id = str(item.data(0, OVERVIEW_ID_ROLE) or "")
            if publication_id:
                selected_publications.append(publication_id)

        if selected_publications:
            self._update_detail_and_metadata([selected_publications[0]])

    def _selected_table_ids(self) -> Set[str]:
        selected: Set[str] = set()
        for top_idx in range(self.overview_tree.topLevelItemCount()):
            pub_item = self.overview_tree.topLevelItem(top_idx)
            for child_idx in range(pub_item.childCount()):
                table_item = pub_item.child(child_idx)
                if table_item.data(0, OVERVIEW_KIND_ROLE) != "table":
                    continue
                if table_item.checkState(0) != Qt.Checked:
                    continue
                table_id = str(table_item.data(0, OVERVIEW_ID_ROLE) or "")
                if table_id:
                    selected.add(table_id)
        return selected

    def _apply_scope_selection(self, triples: Iterable[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
        selected_tables = self._selected_table_ids()
        if not selected_tables:
            return []

        scoped_nodes: Set[str] = set()
        for table_id in selected_tables:
            scoped_nodes.update(self._scope_table_lineages.get(table_id, {table_id}))
            publication_id = self._scope_table_publication.get(table_id, "")
            if publication_id:
                scoped_nodes.add(publication_id)

        scoped: List[Tuple[str, str, str]] = []
        for subj, pred, obj in triples:
            # Keep publication -> has_output edges only for currently selected tables.
            if self._is_publication_node(subj) and self._is_has_output_predicate(pred):
                if obj in selected_tables:
                    scoped.append((subj, pred, obj))
                continue
            if subj in scoped_nodes or obj in scoped_nodes:
                scoped.append((subj, pred, obj))
        return scoped

    def _scope_nodes_for_selected_tables(self) -> Set[str]:
        selected_tables = self._selected_table_ids()
        scoped_nodes: Set[str] = set()
        for table_id in selected_tables:
            scoped_nodes.update(self._scope_table_lineages.get(table_id, {table_id}))
            publication_id = self._scope_table_publication.get(table_id, "")
            if publication_id:
                scoped_nodes.add(publication_id)
        return scoped_nodes

    def _build_query_graph_for_selection(self) -> Tuple[Any, int, int]:
        if self.graph is None:
            return None, 0, 0

        selected_tables = self._selected_table_ids()
        if not selected_tables:
            return None, 0, 0

        all_tables = set(self._scope_table_publication.keys())
        if all_tables and selected_tables == all_tables:
            triple_count = len(self.all_triples)
            return self.graph, triple_count, triple_count

        scoped_nodes = self._scope_nodes_for_selected_tables()
        source_graph = self.graph
        graph_type = type(source_graph)
        scoped_graph = graph_type()

        kept = 0
        total = 0
        for subj, pred, obj in source_graph:
            total += 1
            subj_s = str(subj)
            obj_s = str(obj)

            if self._is_publication_node(subj_s) and self._is_has_output_predicate(str(pred)):
                if obj_s in selected_tables:
                    scoped_graph.add((subj, pred, obj))
                    kept += 1
                continue

            if subj_s in scoped_nodes or obj_s in scoped_nodes:
                scoped_graph.add((subj, pred, obj))
                kept += 1

        return scoped_graph, kept, total

    def _focused_triples(self) -> List[Tuple[str, str, str]]:
        return self.filtered_triples

    def _set_triples_page_for_identifiers(self, identifiers: Iterable[str]) -> None:
        target_identifiers = {identifier for identifier in identifiers if identifier}
        if not target_identifiers:
            return

        match_index = -1
        for idx, (subj, _, obj) in enumerate(self._iter_prioritized_triples(self.filtered_triples)):
            if subj in target_identifiers or obj in target_identifiers:
                match_index = idx
                break

        if match_index >= 0:
            self._triples_page_index = match_index // DEFAULT_VISIBLE_TRIPLES

    def _set_triples_page_for_table_focus(self, lineage_identifiers: Set[str], focused_tables: Set[str]) -> None:
        if not lineage_identifiers or not focused_tables:
            return

        match_index = -1
        for idx, (subj, pred, obj) in enumerate(self._iter_prioritized_triples(self.filtered_triples)):
            if not self._matches_table_focus_triple(subj, pred, obj, lineage_identifiers, focused_tables):
                continue
            match_index = idx
            break

        if match_index >= 0:
            self._triples_page_index = match_index // DEFAULT_VISIBLE_TRIPLES

    def _matches_table_focus_triple(
        self,
        subj: str,
        pred: str,
        obj: str,
        lineage_identifiers: Set[str],
        focused_tables: Set[str],
    ) -> bool:
        # Keep parent publication -> has_output edges only for currently focused tables.
        if self._is_publication_node(subj) and self._is_has_output_predicate(pred):
            return obj in focused_tables
        return subj in lineage_identifiers or obj in lineage_identifiers

    def _render_current_triples_table(self) -> None:
        self._render_triples_table(self._focused_triples())

    def _reset_triples_paging(self) -> None:
        self._triples_page_index = 0

    def on_triples_prev_page(self) -> None:
        if self._triples_page_index <= 0:
            return
        self._triples_page_index -= 1
        self._render_current_triples_table()

    def on_triples_first_page(self) -> None:
        if self._triples_page_index == 0:
            return
        self._triples_page_index = 0
        self._render_current_triples_table()

    def on_triples_next_page(self) -> None:
        total = len(self._focused_triples())
        page_count = max(1, math.ceil(total / DEFAULT_VISIBLE_TRIPLES)) if total else 1
        if self._triples_page_index >= page_count - 1:
            return
        self._triples_page_index += 1
        self._render_current_triples_table()

    def on_triples_last_page(self) -> None:
        total = len(self._focused_triples())
        page_count = max(1, math.ceil(total / DEFAULT_VISIBLE_TRIPLES)) if total else 1
        target_index = max(0, page_count - 1)
        if self._triples_page_index == target_index:
            return
        self._triples_page_index = target_index
        self._render_current_triples_table()

    def _render_triples_table(self, triples: List[Tuple[str, str, str]]) -> None:
        total = len(triples)
        page_size = DEFAULT_VISIBLE_TRIPLES
        page_count = max(1, math.ceil(total / page_size)) if total else 1
        if self._triples_page_index >= page_count:
            self._triples_page_index = max(0, page_count - 1)

        start = self._triples_page_index * page_size
        to_show = self._prioritized_triple_slice(triples, start, page_size)
        self.triples_table.blockSignals(True)
        try:
            self.triples_table.setRowCount(len(to_show))
            self.triples_table.setColumnCount(3)
            if to_show:
                self.triples_table.setVerticalHeaderLabels([str(start + idx + 1) for idx in range(len(to_show))])
            else:
                self.triples_table.setVerticalHeaderLabels([])
            display_cache: Dict[str, str] = {}

            def uuid_display(value: str) -> str:
                cached = display_cache.get(value)
                if cached is not None:
                    return cached
                resolved = self.graph_service.display_value_with_uuid_context(
                    value,
                    input_dir=self.input_dir,
                    graph_path=self.current_graph_path,
                    resolve_row_context=True,
                )
                display_cache[value] = resolved
                return resolved

            for row_idx, (subj, pred, obj) in enumerate(to_show):
                self.triples_table.setItem(
                    row_idx,
                    0,
                    self._make_table_item(subj, raw_value=subj, display_override=uuid_display(subj)),
                )
                self.triples_table.setItem(
                    row_idx,
                    1,
                    self._make_table_item(pred, raw_value=pred, display_override=uuid_display(pred)),
                )
                self.triples_table.setItem(
                    row_idx,
                    2,
                    self._make_table_item(obj, raw_value=obj, display_override=uuid_display(obj)),
                )

            if total == 0:
                self.triples_count_label.setText("Triples: 0")
            else:
                end = start + len(to_show)
                suffix = ""
                if total > page_size:
                    suffix = " (structural rows first)"
                self.triples_count_label.setText(
                    f"Triples: {total} (showing {start + 1}-{end}){suffix}"
                )

            self.triples_page_label.setText(f"Page {self._triples_page_index + 1}/{page_count}")
            self.triples_first_button.setEnabled(self._triples_page_index > 0)
            self.triples_prev_button.setEnabled(self._triples_page_index > 0)
            self.triples_next_button.setEnabled(self._triples_page_index < page_count - 1)
            self.triples_last_button.setEnabled(self._triples_page_index < page_count - 1)
            if len(to_show) <= 1000:
                self.triples_table.resizeColumnsToContents()
        finally:
            self.triples_table.blockSignals(False)

    def _triple_priority_bucket(self, triple: Tuple[str, str, str]) -> int:
        subj, pred, _ = triple
        is_publication = self._is_publication_node(subj)
        is_has_output = self._is_has_output_predicate(pred)
        if is_publication and is_has_output:
            return 0
        if is_has_output or is_publication:
            return 1
        return 2

    def _iter_prioritized_triples(self, triples: Iterable[Tuple[str, str, str]]) -> Iterable[Tuple[str, str, str]]:
        tier1: List[Tuple[str, str, str]] = []
        tier2: List[Tuple[str, str, str]] = []
        tier3: List[Tuple[str, str, str]] = []
        for triple in triples:
            bucket = self._triple_priority_bucket(triple)
            if bucket == 0:
                tier1.append(triple)
            elif bucket == 1:
                tier2.append(triple)
            else:
                tier3.append(triple)
        return itertools.chain(tier1, tier2, tier3)

    def _prioritized_triple_slice(
        self,
        triples: Iterable[Tuple[str, str, str]],
        offset: int,
        limit: int,
    ) -> List[Tuple[str, str, str]]:
        return list(itertools.islice(self._iter_prioritized_triples(triples), offset, offset + limit))

    def on_run_query_clicked(self) -> None:
        if self.graph is None:
            QMessageBox.warning(self, "No Graph", "Load a graph before running queries.")
            return

        selected = self.query_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Query", "Select a query file first.")
            return

        query_name = selected[0].text()
        pmid = self.pmid_input.text().strip()
        query_text = self.query_text_editor.toPlainText().strip()
        if not query_text:
            QMessageBox.warning(self, "Empty Query", "Query text is empty. Select a preset or enter a query.")
            return

        scoped_graph, scoped_triples, total_triples = self._build_query_graph_for_selection()
        if scoped_graph is None:
            QMessageBox.information(
                self,
                "No Scope Selected",
                "Select at least one table in the Overview tab before running a query.",
            )
            return

        if scoped_graph is self.graph:
            self.query_status_label.setText(f"Running {query_name} on full selected scope...")
        else:
            self.query_status_label.setText(
                f"Running {query_name} on scoped selection ({scoped_triples}/{total_triples} triples)..."
            )
        self.run_query_button.setEnabled(False)
        self._begin_busy_cursor("Running query...")

        worker = QueryWorker(
            graph=scoped_graph,
            query_name=query_name,
            pmid=pmid,
            query_text_override=query_text,
            query_service=self.query_service,
            callback=self.query_result_signal.emit,
        )
        worker.start()
        self._active_worker = worker

    def on_query_result(self, headers: List[str], rows: List[List[str]], error: str) -> None:
        self._end_busy_cursor("Query finished")
        self.run_query_button.setEnabled(True)

        if error:
            self.query_status_label.setText(f"Query failed: {error}")
            QMessageBox.warning(self, "Query Error", error)
            return

        self.current_query_result = QueryResultTable(headers=headers, rows=rows)
        self._render_query_results(headers, rows)
        self.tabs.setCurrentWidget(self.query_tab)
        self.query_status_label.setText(f"Query returned {len(rows)} rows")

    def _begin_busy_cursor(self, status_message: str = "") -> None:
        if status_message:
            status_bar = self.statusBar()
            if status_bar is not None:
                status_bar.showMessage(status_message)
        if self._busy_cursor_depth == 0:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        self._busy_cursor_depth += 1

    def _end_busy_cursor(self, status_message: str = "") -> None:
        if self._busy_cursor_depth <= 0:
            return
        self._busy_cursor_depth -= 1
        if self._busy_cursor_depth == 0:
            QApplication.restoreOverrideCursor()
            if status_message:
                status_bar = self.statusBar()
                if status_bar is not None:
                    status_bar.showMessage(status_message)

    def _render_query_results(self, headers: List[str], rows: List[List[str]]) -> None:
        self.query_results_table.setColumnCount(len(headers))
        self.query_results_table.setHorizontalHeaderLabels(headers)
        self.query_results_table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row):
                self.query_results_table.setItem(row_idx, col_idx, self._make_table_item(value, raw_value=value))

        self.query_results_table.resizeColumnsToContents()

    def _make_table_item(self, value: str, raw_value: str = "", display_override: str = "") -> QTableWidgetItem:
        raw = raw_value if raw_value else value
        if display_override:
            display = display_override
        else:
            graph_service = self.__dict__.get("graph_service")
            if graph_service is not None:
                display = graph_service.display_value(raw)
            else:
                display = raw

        item = QTableWidgetItem(display)
        item.setData(ITEM_USER_ROLE, raw)
        return item

    def refresh_network_view(self) -> None:
        selected_identifiers = self._selected_network_identifiers()
        fallback_identifiers = self._current_triple_node_identifiers()

        self.network_scene.blockSignals(True)
        try:
            self.network_scene.clear()
            self._network_node_lookup = {}
            self._network_node_items = {}
            self._network_edge_items = []
            self._network_group_node_colors = {}
            self._network_group_edge_colors = {}
            self._network_table_colors = {}
            self._network_table_publications = {}
            self._network_table_lineages = {}
            self._network_table_children = {}
            self._network_legend_table_links = {}

            if not self.filtered_triples:
                self.network_summary_label.setText("Nodes: 0 | Edges: 0")
                self._set_html_text(self.network_legend_text, "<b>Table legend:</b><br>None")
                return

            def network_label(value: str) -> str:
                return self.graph_service.display_value_with_uuid_context(
                    value,
                    input_dir=self.input_dir,
                    graph_path=self.current_graph_path,
                    resolve_row_context=True,
                )

            model = self.graph_service.build_network_model(
                self._iter_prioritized_triples(self.filtered_triples),
                max_edges=int(self.network_edge_limit.value()),
                label_resolver=network_label,
            )

            (
                self._network_group_node_colors,
                self._network_group_edge_colors,
                self._network_table_colors,
                self._network_table_publications,
                self._network_table_lineages,
                self._network_table_children,
            ) = self._compute_table_lineage_colors(model)

            self._network_node_lookup = {node.identifier: node for node in model.nodes}
            positions = self._compute_network_positions(model.nodes)

            detail_mode = self._network_detail_mode_value()
            visible_ids = self._visible_network_identifiers(model.nodes, detail_mode)

            node_items: Dict[str, NetworkNodeItem] = {}

            for node in model.nodes:
                if node.identifier not in visible_ids:
                    continue
                pos = positions.get(node.identifier)
                if pos is None:
                    continue

                node_item = NetworkNodeItem(NETWORK_NODE_RADIUS)
                base_color = self._network_group_node_colors.get(node.identifier, self._network_node_color(node))
                node_item.setBrush(QBrush(base_color))
                node_item.setPen(QPen(QColor("#314355"), 1.2))
                node_item.setData(0, node.identifier)
                node_item.setToolTip(self._network_node_tooltip(node))
                node_item.setZValue(2)
                node_item.setPos(pos)
                self.network_scene.addItem(node_item)

                label_item = QGraphicsSimpleTextItem(node.label)
                label_item.setBrush(QBrush(QColor("#1f2933")))
                label_item.setPos(pos.x() - 30, pos.y() + NETWORK_NODE_RADIUS + 2)
                label_item.setZValue(3)
                self.network_scene.addItem(label_item)
                node_item.label_item = label_item
                node_items[node.identifier] = node_item

            for edge in model.edges:
                source_item = node_items.get(edge.source)
                target_item = node_items.get(edge.target)
                if source_item is None or target_item is None:
                    continue

                edge_item = NetworkEdgeItem(source_item, target_item, edge.predicate)
                edge_key = (edge.source, edge.predicate, edge.target)
                edge_base_color = self._network_group_edge_colors.get(edge_key)
                if edge_base_color is not None:
                    edge_item.set_base_color(edge_base_color)
                self.network_scene.addItem(edge_item)
                self._network_edge_items.append(edge_item)

            self._network_node_items = node_items
            detail_note = f" ({detail_mode})"
            self.network_summary_label.setText(
                f"Nodes: {len(node_items)} | Edges: {len(self._network_edge_items)}{detail_note}"
            )
            self._render_network_legend(network_label)
        finally:
            self.network_scene.blockSignals(False)

        restored_identifiers = selected_identifiers or fallback_identifiers
        if restored_identifiers:
            self._select_network_nodes(restored_identifiers)
        else:
            self._apply_network_node_highlight(set())
            self._apply_network_edge_highlight(set(), set())

        self.fit_network_view()

    def _selected_network_identifiers(self) -> List[str]:
        identifiers: List[str] = []
        for item in self.network_scene.selectedItems():
            identifier = item.data(0)
            if isinstance(identifier, str) and identifier:
                identifiers.append(identifier)
        return identifiers

    def _current_triple_node_identifiers(self) -> List[str]:
        row = self.triples_table.currentRow()
        if row < 0:
            return []

        identifiers: List[str] = []
        for col in (0, 2):
            value = self._table_value(self.triples_table, row, col)
            if value:
                identifiers.append(value)
        return identifiers

    @staticmethod
    def _is_has_output_predicate(predicate: str) -> bool:
        p = predicate.strip().lower()
        return "has_output" in p or p.endswith("/hasoutput") or p.endswith("#hasoutput")

    @staticmethod
    def _is_gene_predicate(predicate: str) -> bool:
        p = predicate.strip().lower()
        return "biolink/vocab/gene" in p or p.endswith("/gene") or p.endswith("#gene")

    @staticmethod
    def _is_logfc_predicate(predicate: str) -> bool:
        p = predicate.strip().lower()
        return "data_3754" in p or p.endswith("/logfc") or p.endswith("#logfc")

    @staticmethod
    def _is_pvalue_predicate(predicate: str) -> bool:
        p = predicate.strip().lower()
        return "data_1669" in p or "pvalue" in p or p.endswith("/p-value") or p.endswith("#p-value")

    @staticmethod
    def _format_metric_value(value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""

        if "^^" in text:
            text = text.split("^^", 1)[0].strip()
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            text = text[1:-1]
        return text

    @staticmethod
    def _is_publication_node(value: str) -> bool:
        if MetadataService.normalize_pmid(value):
            return True
        lower = value.strip().lower()
        return "pubmed.ncbi.nlm.nih.gov" in lower or "/pmid/" in lower

    def _compute_table_lineage_colors(
        self,
        model: Any,
    ) -> Tuple[
        Dict[str, QColor],
        Dict[Tuple[str, str, str], QColor],
        Dict[str, QColor],
        Dict[str, str],
        Dict[str, Set[str]],
        Dict[str, Set[str]],
    ]:
        root_edges: List[Tuple[str, str, str]] = []
        table_publications: Dict[str, str] = {}
        for edge in model.edges:
            if not self._is_has_output_predicate(edge.predicate):
                continue
            if self._is_publication_node(edge.source):
                root_edges.append((edge.source, edge.predicate, edge.target))
                table_publications.setdefault(edge.target, edge.source)

        table_roots: List[str] = []
        seen_roots: set[str] = set()
        for _, _, target in root_edges:
            if target in seen_roots:
                continue
            seen_roots.add(target)
            table_roots.append(target)

        outgoing: Dict[str, List[Tuple[str, str, str]]] = {}
        for edge in model.edges:
            outgoing.setdefault(edge.source, []).append((edge.source, edge.predicate, edge.target))

        node_to_tables: Dict[str, set[str]] = {}
        edge_to_tables: Dict[Tuple[str, str, str], set[str]] = {}
        table_lineages: Dict[str, Set[str]] = {}
        table_children: Dict[str, Set[str]] = {}

        for source, predicate, target in root_edges:
            edge_key = (source, predicate, target)
            edge_to_tables.setdefault(edge_key, set()).add(target)

        for table_root in table_roots:
            lineage_nodes: Set[str] = {table_root}
            direct_children: Set[str] = set()
            frontier: List[Tuple[str, int]] = [(table_root, 0)]
            seen_nodes = {table_root}
            while frontier:
                current, depth = frontier.pop()
                node_to_tables.setdefault(current, set()).add(table_root)
                for edge_key in outgoing.get(current, []):
                    edge_to_tables.setdefault(edge_key, set()).add(table_root)
                    nxt = edge_key[2]
                    lineage_nodes.add(nxt)
                    if depth == 0:
                        direct_children.add(nxt)
                    if nxt in seen_nodes:
                        continue
                    seen_nodes.add(nxt)
                    frontier.append((nxt, depth + 1))
            table_lineages[table_root] = lineage_nodes
            table_children[table_root] = direct_children

        table_roots_sorted = sorted(table_roots)
        table_colors: Dict[str, QColor] = {
            table_root: self._table_group_color(index)
            for index, table_root in enumerate(table_roots_sorted)
        }

        neutral = QColor("#c7ccd4")
        node_colors: Dict[str, QColor] = {}
        for node_id, tables in node_to_tables.items():
            if len(tables) == 1:
                table_root = next(iter(tables))
                node_colors[node_id] = table_colors[table_root]
            else:
                node_colors[node_id] = neutral

        edge_colors: Dict[Tuple[str, str, str], QColor] = {}
        for edge_key, tables in edge_to_tables.items():
            if len(tables) == 1:
                table_root = next(iter(tables))
                edge_colors[edge_key] = table_colors[table_root]
            else:
                edge_colors[edge_key] = neutral

        return node_colors, edge_colors, table_colors, table_publications, table_lineages, table_children

    def _render_network_legend(self, label_resolver: Optional[Any] = None) -> None:
        self._network_legend_table_links = {}
        if not self._network_table_colors:
            self._set_html_text(self.network_legend_text, "<b>Table legend:</b><br>None")
            return

        if label_resolver is None:
            def label_resolver(value: str) -> str:
                return self.graph_service.display_value_with_uuid_context(
                    value,
                    input_dir=self.input_dir,
                    graph_path=self.current_graph_path,
                    resolve_row_context=True,
                )

        parts: List[str] = ["<b>Table legend:</b>"]
        focused_count = len(self._network_table_focus_tables)
        if focused_count > 0:
            parts.append(
                f'<span style="background:#fff4ce; border:1px solid #f59f00; border-radius:4px; '
                f'padding:2px 6px; font-weight:600;">Focused tables: {focused_count}</span>'
            )
        legend_entries: List[Tuple[str, str, str, QColor]] = []
        for table_id, color in self._network_table_colors.items():
            publication_id = self._network_table_publications.get(table_id, "")
            publication_label = str(label_resolver(publication_id)) if publication_id else ""
            table_label = str(label_resolver(table_id))
            legend_entries.append((publication_label.lower(), table_label.lower(), table_id, color))

        current_pub_display = ""
        for index, (_, _, table_id, color) in enumerate(sorted(legend_entries)):
            publication_id = self._network_table_publications.get(table_id, "")
            publication_label = html.escape(str(label_resolver(publication_id))) if publication_id else "(no publication root)"
            table_label = html.escape(str(label_resolver(table_id)))
            color_hex = color.name()
            link_key = str(index)
            self._network_legend_table_links[link_key] = table_id
            if publication_label != current_pub_display:
                parts.append(f"<b>{publication_label}</b>")
                current_pub_display = publication_label

            selected_style_open = ""
            selected_style_close = ""
            selected_marker = ""
            if table_id in self._network_table_focus_tables:
                selected_style_open = (
                    '<span style="background:#fff4ce; border:1px solid #f59f00; '
                    'border-radius:4px; padding:1px 4px; font-weight:700;">'
                )
                selected_style_close = "</span>"
                selected_marker = "&#10003; "

            parts.append(
                f'<a href="table:{link_key}">'
                f"{selected_style_open}"
                f'{selected_marker}<span style="color:{color_hex}; font-size:14pt;">&#9632;</span> '
                f"{table_label}"
                f"{selected_style_close}</a>"
            )

        self._set_html_text(self.network_legend_text, "<br>".join(parts))

    def _network_detail_mode_value(self) -> str:
        return str(self.network_detail_mode.currentData() or "overview")

    def _visible_network_identifiers(self, nodes: List[NetworkNode], detail_mode: str) -> Set[str]:
        if detail_mode == "full":
            return {node.identifier for node in nodes}

        visible_ids: Set[str] = set(self._network_table_colors.keys())
        for node in nodes:
            if self._is_publication_node(node.identifier):
                visible_ids.add(node.identifier)

        if detail_mode == "tables":
            for child_ids in self._network_table_children.values():
                visible_ids.update(child_ids)

        return visible_ids

    def on_network_legend_link_clicked(self, url: QUrl) -> None:
        if url.scheme() != "table":
            return

        link_key = url.path().lstrip("/")
        if not link_key:
            link_key = url.toString().split(":", 1)[-1]
        table_id = self._network_legend_table_links.get(link_key)
        if not table_id:
            return

        modifiers = QApplication.keyboardModifiers()
        ctrl_pressed = bool(modifiers & Qt.ControlModifier)
        if ctrl_pressed:
            focused_tables = set(self._network_table_focus_tables)
            if table_id in focused_tables:
                focused_tables.remove(table_id)
            else:
                focused_tables.add(table_id)
            self._focus_table_lineages(focused_tables, primary_table_id=table_id)
            return

        self._focus_table_lineages({table_id}, primary_table_id=table_id)

    def _focus_table_lineage(self, table_id: str) -> None:
        self._focus_table_lineages({table_id}, primary_table_id=table_id)

    def _focus_table_lineages(self, table_ids: Set[str], primary_table_id: str = "") -> None:
        self._network_table_focus_tables = set(table_ids)
        self._render_network_legend()
        if not table_ids:
            self._network_table_focus_identifiers = set()
            self._network_focus_identifiers = []
            self._apply_network_node_highlight(set())
            self._apply_network_edge_highlight(set(), set())
            self._set_html_text(self.detail_text, "")
            self._clear_triples_table_selection()
            return

        lineage_ids: Set[str] = set()
        publication_ids: Set[str] = set()
        for table_id in table_ids:
            table_lineage = set(self._network_table_lineages.get(table_id, set()))
            if not table_lineage:
                table_lineage = {table_id}
            lineage_ids.update(table_lineage)
            publication_id = self._network_table_publications.get(table_id, "")
            if publication_id:
                lineage_ids.add(publication_id)
                publication_ids.add(publication_id)

        self._network_table_focus_identifiers = set(lineage_ids)

        visible_ids = [identifier for identifier in lineage_ids if identifier in self._network_node_items]
        self._select_network_nodes(visible_ids)

        primary_table = primary_table_id or sorted(table_ids)[0]
        primary_label = self.graph_service.display_value_with_uuid_context(
            primary_table,
            input_dir=self.input_dir,
            graph_path=self.current_graph_path,
            resolve_row_context=True,
        )
        detail_values = [
            f"Focused tables: {len(table_ids)}",
            f"Primary table: {primary_label}",
            f"Publications covered: {len(publication_ids)}",
            f"Lineage nodes: {len(lineage_ids)}",
            f"Visible nodes in current view: {len(visible_ids)}",
            "Tip: Ctrl-click legend entries to add/remove tables from focus.",
        ]

        self._selection_sync_active = True
        try:
            self._network_focus_identifiers = sorted(lineage_ids)
            self._update_detail_and_metadata(detail_values)
            self._set_triples_page_for_table_focus(lineage_ids, table_ids)
            self._render_current_triples_table()
            self.tabs.setCurrentWidget(self.triples_tab)
            self._select_triple_rows_for_table_focus(lineage_ids, table_ids)
        finally:
            self._selection_sync_active = False

    def _apply_network_node_highlight(self, identifiers: set[str]) -> None:
        focused_identifiers = self._network_table_focus_identifiers
        for identifier, item in self._network_node_items.items():
            node = self._network_node_lookup.get(identifier)
            if node is None:
                continue

            brush_color = self._network_group_node_colors.get(identifier, self._network_node_color(node))
            label_color = QColor("#1f2933")
            pen = QPen(QColor("#314355"), 1.2)
            if focused_identifiers and identifier not in focused_identifiers:
                dim_color = QColor(brush_color)
                dim_color.setAlpha(65)
                brush_color = dim_color
                label_color = QColor("#7f8c96")
                pen = QPen(QColor("#9aa5b1"), 0.8)
            if identifier in identifiers:
                brush_color = brush_color.lighter(120)
                label_color = QColor("#7c2d12")
                pen = QPen(QColor("#d9480f"), 2.6)

            item.setBrush(QBrush(brush_color))
            item.setPen(pen)
            if item.label_item is not None:
                item.label_item.setBrush(QBrush(label_color))

    def _apply_network_edge_highlight(self, edge_keys: set[Tuple[str, str, str]], node_identifiers: set[str]) -> None:
        focused_identifiers = self._network_table_focus_identifiers
        for edge_item in self._network_edge_items:
            edge_key = (
                str(edge_item.source_item.data(0) or ""),
                edge_item.predicate,
                str(edge_item.target_item.data(0) or ""),
            )
            highlighted = edge_key in edge_keys
            if not highlighted and node_identifiers:
                highlighted = edge_key[0] in node_identifiers or edge_key[2] in node_identifiers
            dimmed = bool(
                focused_identifiers
                and edge_key[0] not in focused_identifiers
                and edge_key[2] not in focused_identifiers
            )
            edge_item.set_dimmed(dimmed)
            edge_item.set_highlighted(highlighted)

    def _select_network_nodes(self, identifiers: Iterable[str]) -> None:
        target_identifiers = {identifier for identifier in identifiers if identifier in self._network_node_items}

        self.network_scene.blockSignals(True)
        try:
            for item in self._network_node_items.values():
                item.setSelected(False)
            for identifier in target_identifiers:
                self._network_node_items[identifier].setSelected(True)
        finally:
            self.network_scene.blockSignals(False)

        self._apply_network_node_highlight(target_identifiers)
        self._apply_network_edge_highlight(set(), target_identifiers)

    def _select_triple_rows_for_identifiers(self, identifiers: Iterable[str]) -> None:
        target_identifiers = {identifier for identifier in identifiers if identifier}
        matching_rows: List[int] = []

        self.triples_table.blockSignals(True)
        try:
            self.triples_table.clearSelection()
            for row in range(self.triples_table.rowCount()):
                subj = self._table_value(self.triples_table, row, 0)
                obj = self._table_value(self.triples_table, row, 2)
                if subj not in target_identifiers and obj not in target_identifiers:
                    continue
                matching_rows.append(row)

            if matching_rows:
                self.triples_table.setCurrentCell(matching_rows[0], 0)
                for row in matching_rows:
                    for col in range(self.triples_table.columnCount()):
                        item = self.triples_table.item(row, col)
                        if item is not None:
                            item.setSelected(True)
                first_item = self.triples_table.item(matching_rows[0], 0)
                if first_item is not None:
                    self.triples_table.scrollToItem(first_item)
        finally:
            self.triples_table.blockSignals(False)

    def _clear_triples_table_selection(self) -> None:
        self.triples_table.blockSignals(True)
        try:
            self.triples_table.clearSelection()
            self.triples_table.setCurrentCell(-1, -1)
        finally:
            self.triples_table.blockSignals(False)

    def _select_triple_rows_for_table_focus(self, lineage_identifiers: Set[str], focused_tables: Set[str]) -> None:
        if not lineage_identifiers or not focused_tables:
            self._select_triple_rows_for_identifiers([])
            return

        matching_rows: List[int] = []

        self.triples_table.blockSignals(True)
        try:
            self.triples_table.clearSelection()
            for row in range(self.triples_table.rowCount()):
                subj = self._table_value(self.triples_table, row, 0)
                pred = self._table_value(self.triples_table, row, 1)
                obj = self._table_value(self.triples_table, row, 2)
                if not self._matches_table_focus_triple(subj, pred, obj, lineage_identifiers, focused_tables):
                    continue
                matching_rows.append(row)

            if matching_rows:
                self.triples_table.setCurrentCell(matching_rows[0], 0)
                for row in matching_rows:
                    for col in range(self.triples_table.columnCount()):
                        item = self.triples_table.item(row, col)
                        if item is not None:
                            item.setSelected(True)
                first_item = self.triples_table.item(matching_rows[0], 0)
                if first_item is not None:
                    self.triples_table.scrollToItem(first_item)
        finally:
            self.triples_table.blockSignals(False)

    def _selected_triple_rows(self) -> List[int]:
        selected_rows = {index.row() for index in self.triples_table.selectionModel().selectedRows()} if self.triples_table.selectionModel() else set()
        if not selected_rows:
            current_row = self.triples_table.currentRow()
            if current_row >= 0:
                selected_rows.add(current_row)
        return sorted(selected_rows)

    def _selected_triple_edge_keys(self) -> List[Tuple[str, str, str]]:
        edge_keys: List[Tuple[str, str, str]] = []
        for row in self._selected_triple_rows():
            edge_keys.append(
                (
                    self._table_value(self.triples_table, row, 0),
                    self._table_value(self.triples_table, row, 1),
                    self._table_value(self.triples_table, row, 2),
                )
            )
        return edge_keys

    def zoom_network(self, factor: float) -> None:
        self.network_view.scale(factor, factor)

    def reset_network_zoom(self) -> None:
        self.network_view.resetTransform()
        self.fit_network_view()

    def fit_network_view(self) -> None:
        rect = self.network_scene.itemsBoundingRect()
        if rect.isNull():
            return
        self.network_view.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)

    @staticmethod
    def _compute_network_positions(nodes: List[NetworkNode]) -> Dict[str, QPointF]:
        positions: Dict[str, QPointF] = {}
        n = len(nodes)
        if not n:
            return positions

        # Sunflower / Fibonacci spiral: evenly fills a disc with ~uniform spacing.
        # golden_angle ≈ 137.5° ensures no two spokes align.
        golden_angle = math.pi * (3.0 - math.sqrt(5.0))
        scale = 95.0 * math.sqrt(n)

        for index, node in enumerate(nodes):
            r = scale * math.sqrt((index + 0.5) / n)
            theta = index * golden_angle
            positions[node.identifier] = QPointF(r * math.cos(theta), r * math.sin(theta))
        return positions

    @staticmethod
    def _network_node_color(node: NetworkNode) -> QColor:
        if node.pmid:
            return QColor("#74b9ff")
        if node.is_literal:
            return QColor("#f7c59f")
        return QColor("#7bd389")

    @staticmethod
    def _table_group_color(index: int) -> QColor:
        hue = int((index * 137) % 360)
        saturation = 190
        value = 220
        return QColor.fromHsv(hue, saturation, value)

    def _network_node_tooltip(self, node: NetworkNode) -> str:
        lines = [
            f"Label: {node.label}",
            f"Identifier: {node.identifier}",
            f"Degree: {node.degree}",
        ]
        if node.pmid:
            lines.append(f"PMID: {node.pmid}")

        bin_info = self._format_bin_metadata([node.identifier])
        if bin_info:
            lines.append("")
            lines.append(bin_info)
        return "\n".join(lines)

    def on_network_selection_changed(self) -> None:
        selected_items = self.network_scene.selectedItems()
        if not selected_items:
            self._network_focus_identifiers = []
            if not self._selection_sync_active:
                self._network_table_focus_identifiers = set()
                self._network_table_focus_tables = set()
                self._render_network_legend()
            if not self._selection_sync_active:
                self._reset_triples_paging()
                self._render_current_triples_table()
            self._apply_network_node_highlight(set())
            self._apply_network_edge_highlight(set(), set())
            return

        node_identifiers = []
        for item in selected_items:
            identifier = item.data(0)
            if isinstance(identifier, str) and identifier:
                node_identifiers.append(identifier)

        if not node_identifiers:
            self._network_focus_identifiers = []
            if not self._selection_sync_active:
                self._network_table_focus_identifiers = set()
                self._network_table_focus_tables = set()
                self._render_network_legend()
            if not self._selection_sync_active:
                self._reset_triples_paging()
                self._render_current_triples_table()
            self._apply_network_node_highlight(set())
            self._apply_network_edge_highlight(set(), set())
            return

        self._apply_network_node_highlight(set(node_identifiers))
        self._apply_network_edge_highlight(set(), set(node_identifiers))
        node_identifier = node_identifiers[0]
        node = self._network_node_lookup.get(node_identifier)
        if node is None:
            return

        values = [
            f"Identifier: {node.identifier}",
            f"Label: {node.label}",
            f"Degree: {node.degree}",
        ]
        self._update_detail_and_metadata(values)
        if self._selection_sync_active:
            return

        self._network_table_focus_identifiers = set()
        self._network_table_focus_tables = set()
        self._render_network_legend()

        self._selection_sync_active = True
        try:
            self._network_focus_identifiers = node_identifiers
            self._set_triples_page_for_identifiers(node_identifiers)
            self._render_current_triples_table()
            self.tabs.setCurrentWidget(self.triples_tab)
            self._select_triple_rows_for_identifiers(node_identifiers)
        finally:
            self._selection_sync_active = False

    def on_export_csv_clicked(self) -> None:
        headers = self.current_query_result.headers
        rows = self.current_query_result.rows
        if not headers:
            QMessageBox.information(self, "No Data", "Run a query before exporting.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Query Results",
            os.path.join(os.getcwd(), "query_results.csv"),
            "CSV (*.csv)",
        )
        if not filename:
            return

        try:
            import csv

            with open(filename, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(rows)
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
            return

        self.query_status_label.setText(f"Exported {len(rows)} rows to {filename}")

    def on_triples_selection_changed(self) -> None:
        row = self.triples_table.currentRow()
        if row < 0:
            if not self._selection_sync_active:
                self._select_network_nodes([])
            return

        values = [
            self._table_value(self.triples_table, row, 0),
            self._table_value(self.triples_table, row, 1),
            self._table_value(self.triples_table, row, 2),
        ]
        self._update_detail_and_metadata(values)
        selected_edge_keys = self._selected_triple_edge_keys()
        selected_node_identifiers = {
            identifier
            for subj, _, obj in selected_edge_keys
            for identifier in (subj, obj)
            if identifier
        }
        self._apply_network_edge_highlight(set(selected_edge_keys), selected_node_identifiers)
        if self._selection_sync_active:
            return

        self._selection_sync_active = True
        try:
            self._network_focus_identifiers = []
            self._select_network_nodes(selected_node_identifiers)
            self._apply_network_edge_highlight(set(selected_edge_keys), selected_node_identifiers)
        finally:
            self._selection_sync_active = False

    def on_query_selection_changed(self) -> None:
        row = self.query_results_table.currentRow()
        if row < 0:
            return

        values: List[str] = []
        for col in range(self.query_results_table.columnCount()):
            values.append(self._table_value(self.query_results_table, row, col))
        self._update_detail_and_metadata(values)

    @staticmethod
    def _table_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text() if item else ""

    @staticmethod
    def _table_value(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        if item is None:
            return ""
        raw = item.data(ITEM_USER_ROLE)
        if isinstance(raw, str) and raw:
            return raw
        return item.text()

    @staticmethod
    def _linkify_text(text: str) -> str:
        escaped = html.escape(text)
        url_pattern = re.compile(r"(https?://[^\s<>\"]+)")

        def repl(match: re.Match[str]) -> str:
            url = match.group(1)
            return f'<a href="{url}">{url}</a>'

        linked = url_pattern.sub(repl, escaped)
        return linked.replace("\n", "<br>")

    def _set_linkified_text(self, browser: QTextBrowser, text: str) -> None:
        self._set_html_text(browser, self._linkify_text(text))

    def _set_html_text(self, browser: QTextBrowser, html_body: str) -> None:
        browser.setHtml(
            "<html><head><style>"
            "body { font-family: Segoe UI, sans-serif; font-size: 11pt; }"
            "a { color: #1e5fbf; text-decoration: underline; }"
            "b { font-weight: 600; }"
            "</style></head><body>"
            f"{html_body}"
            "</body></html>"
        )

    def _update_detail_and_metadata(self, values: List[str]) -> None:
        display_values = [
            self.graph_service.display_value_with_uuid_context(
                value,
                input_dir=self.input_dir,
                graph_path=self.current_graph_path,
            )
            for value in values
        ]

        detail_html_parts: List[str] = ["<b>Selected values:</b>"]
        detail_html_parts.extend(self._linkify_text(value) for value in display_values)

        if any(display != raw for display, raw in zip(display_values, values)):
            detail_html_parts.append("")
            detail_html_parts.append("<b>Raw values:</b>")
            detail_html_parts.extend(self._linkify_text(value) for value in values)

        bin_info = self._format_bin_metadata(values)
        if bin_info:
            detail_html_parts.append("")
            detail_html_parts.append("Bin information:")
            detail_html_parts.append(self._linkify_text(bin_info))

        pmid = MetadataService.extract_pmid_from_values(values)
        if pmid:
            metadata = self.metadata_service.get_by_pmid(pmid)
            if not metadata:
                detail_html_parts.append("")
                detail_html_parts.append("PMID metadata:")
                detail_html_parts.append(self._linkify_text(f"PMID {pmid} not found in metadata"))
            else:
                ordered_keys = [
                    "pmid",
                    "title",
                    "doi",
                    "journal",
                    "year",
                    "abstract",
                ]
                used = set()
                lines: List[str] = [f"PMID: {pmid}"]
                for key in ordered_keys:
                    for candidate in metadata.keys():
                        if candidate.strip().lower() == key and candidate not in used:
                            value = metadata.get(candidate, "")
                            if value:
                                lines.append(f"{candidate}: {value}")
                            used.add(candidate)
                            break

                for key, value in metadata.items():
                    if key in used or not value:
                        continue
                    lines.append(f"{key}: {value}")

                detail_html_parts.append("")
                detail_html_parts.append("PMID metadata:")
                detail_html_parts.extend(self._linkify_text(line) for line in lines)

        self._set_html_text(self.detail_text, "<br>".join(detail_html_parts))

    def _format_bin_metadata(self, values: List[str]) -> str:
        if not self.binning_metadata:
            return ""
        bin_index = self.graph_service.find_bin_index(values)
        if bin_index is None:
            return ""
        return self.graph_service.format_bin_description(bin_index, self.binning_metadata)

    def closeEvent(self, event: Any) -> None:
        self._save_settings()
        super().closeEvent(event)

    def _load_settings(self) -> str:
        if not os.path.exists(self.settings_path):
            return ""

        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
            if not isinstance(settings, dict):
                return ""
        except Exception:
            return ""

        geometry_hex = settings.get("window_geometry")
        if isinstance(geometry_hex, str):
            try:
                self.restoreGeometry(bytes.fromhex(geometry_hex))
            except Exception:
                pass

        last_graph = settings.get("last_graph_path", "")
        startup_graph = ""
        if isinstance(last_graph, str) and last_graph and os.path.exists(last_graph):
            startup_graph = last_graph

        last_query = settings.get("last_query_name", "")
        if isinstance(last_query, str) and last_query:
            for idx in range(self.query_list.count()):
                item = self.query_list.item(idx)
                if item is None:
                    continue
                if item.text() == last_query:
                    self.query_list.setCurrentRow(idx)
                    break

        last_pmid = settings.get("last_pmid", "")
        if isinstance(last_pmid, str):
            self.pmid_input.setText(last_pmid)

        return startup_graph

    def _save_settings(self) -> None:
        settings: Dict[str, Any] = {}
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    settings.update(loaded)
            except Exception:
                pass

        settings["window_geometry"] = bytes(self.saveGeometry()).hex()
        settings["last_graph_path"] = self.current_graph_path
        selected = self.query_list.selectedItems()
        settings["last_query_name"] = selected[0].text() if selected else ""
        settings["last_pmid"] = self.pmid_input.text().strip()

        try:
            with open(self.settings_path, "w", encoding="utf-8") as handle:
                json.dump(settings, handle, indent=2)
        except Exception:
            pass


def resolve_default_metadata_path(input_dir: str) -> str:
    input_candidate = os.path.join(input_dir, "asd_article_metadata.csv")
    if os.path.exists(input_candidate):
        return input_candidate

    workspace_candidate = os.path.join("data", "asd_article_metadata.csv")
    if os.path.exists(workspace_candidate):
        return workspace_candidate

    return input_candidate


def resolve_query_dir(input_dir: str, query_dir_arg: str) -> str:
    query_dir_value = (query_dir_arg or "").strip()
    if not query_dir_value:
        return os.path.join(input_dir, "query")

    if os.path.isabs(query_dir_value):
        return query_dir_arg

    return os.path.join(input_dir, query_dir_value)


def resolve_graph_arg(input_dir: str, graph_arg: str) -> str:
    if not graph_arg:
        return ""
    if os.path.isabs(graph_arg):
        return graph_arg

    graph_candidate = os.path.join(input_dir, "graph", graph_arg)
    if os.path.exists(graph_candidate):
        return graph_candidate

    return graph_arg


def prefer_hdt_graph_path(graph_path: str) -> str:
    return graph_path


def main() -> None:
    parser = argparse.ArgumentParser(description="AKG knowledge graph explorer GUI")
    parser.add_argument(
        "-i",
        "--input_dir",
        default="data",
        help="Top-level input directory. Graph files are expected under <input_dir>/graph",
    )
    parser.add_argument("--graph", default="", help="Optional graph filename/path. Relative values are resolved under <input_dir>/graph")
    parser.add_argument(
        "--query-dir",
        default="",
        help="Directory containing preset .rq files. Defaults to <input_dir>/query",
    )
    parser.add_argument("--metadata", default="", help="Metadata CSV path (defaults to <input_dir>/asd_article_metadata.csv)")
    args = parser.parse_args()

    input_dir = args.input_dir
    query_dir = resolve_query_dir(input_dir, args.query_dir)
    metadata_csv = args.metadata if args.metadata else resolve_default_metadata_path(input_dir)
    graph_path = resolve_graph_arg(input_dir, args.graph)

    app = QApplication([])
    window = KGExplorerWindow(
        input_dir=input_dir,
        query_dir=query_dir,
        metadata_csv=metadata_csv,
        graph_path=graph_path,
    )
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
