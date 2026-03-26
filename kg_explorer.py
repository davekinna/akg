#!/usr/bin/env python3
"""PyQt5 GUI for loading and interrogating AKG RDF knowledge graphs."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QKeySequence, QPainter, QPen
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
    QVBoxLayout,
    QWidget,
)

from kg_services import GraphDataService, MetadataService, NetworkNode, QueryResultTable, QueryService

SETTINGS_FILE = "kg_explorer_settings.json"
DEFAULT_VISIBLE_TRIPLES = 5000
DEFAULT_NETWORK_MAX_EDGES = 250
NETWORK_NODE_RADIUS = 18.0
ITEM_USER_ROLE = 32


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
        query_service: QueryService,
        callback: Any,
    ):
        super().__init__(daemon=True)
        self.graph = graph
        self.query_name = query_name
        self.pmid = pmid
        self.query_service = query_service
        self.callback = callback

    def run(self) -> None:
        try:
            table = self.query_service.run_query(self.graph, self.query_name, pmid=self.pmid)
            self.callback(table.headers, table.rows, "")
        except Exception as exc:
            self.callback([], [], str(exc))


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
        self.source_item.edge_items.append(self)
        self.target_item.edge_items.append(self)
        self.setPen(QPen(QColor("#8fa0b3"), 1.4))
        self.setZValue(0)
        self.setToolTip(f"Predicate: {predicate}")
        self.update_position()

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

        self.query_result_signal.connect(self.on_query_result)
        self._build_ui()
        self._populate_graph_list()

        self.settings_path = os.path.join(os.getcwd(), SETTINGS_FILE)
        self._load_settings()

        self._populate_query_list()
        self.metadata_status_label.setText(self.metadata_service.status_message)

        if graph_path:
            self.load_graph(graph_path)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Graph:"))
        self.graph_combo = QComboBox()
        self.graph_combo.setEditable(False)
        top_bar.addWidget(self.graph_combo, 1)

        self.load_selected_button = QPushButton("Load Selected")
        self.load_selected_button.clicked.connect(self.on_load_selected_graph_clicked)
        top_bar.addWidget(self.load_selected_button)

        self.refresh_graphs_button = QPushButton("Refresh")
        self.refresh_graphs_button.clicked.connect(self.on_refresh_graphs_clicked)
        top_bar.addWidget(self.refresh_graphs_button)

        self.load_button = QPushButton("Load Graph (.nt)")
        self.load_button.clicked.connect(self.on_load_graph_clicked)
        self.graph_label = QLabel("No graph loaded")
        self.graph_label.setWordWrap(True)
        top_bar.addWidget(self.load_button)
        top_bar.addWidget(self.graph_label, 2)
        root.addLayout(top_bar)

        splitter = QSplitter()
        root.addWidget(splitter, 1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([300, 900, 400])

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        query_group = QGroupBox("Preset SPARQL Queries")
        query_layout = QVBoxLayout(query_group)

        self.query_list = QListWidget()
        query_layout.addWidget(self.query_list, 1)

        pmid_row = QHBoxLayout()
        pmid_row.addWidget(QLabel("PMID:"))
        self.pmid_input = QLineEdit()
        self.pmid_input.setPlaceholderText("Optional, for parameterized queries")
        pmid_row.addWidget(self.pmid_input, 1)
        query_layout.addLayout(pmid_row)

        self.run_query_button = QPushButton("Run Selected Query")
        self.run_query_button.clicked.connect(self.on_run_query_clicked)
        query_layout.addWidget(self.run_query_button)

        self.export_button = QPushButton("Export Query Results to CSV")
        self.export_button.clicked.connect(self.on_export_csv_clicked)
        query_layout.addWidget(self.export_button)

        self.query_status_label = QLabel("Choose a query and click Run")
        self.query_status_label.setWordWrap(True)
        query_layout.addWidget(self.query_status_label)

        layout.addWidget(query_group, 1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        triples_tab = QWidget()
        triples_layout = QVBoxLayout(triples_tab)

        filter_box = QGroupBox("Triple Filters")
        filter_layout = QGridLayout(filter_box)

        self.subject_filter = QLineEdit()
        self.subject_filter.setPlaceholderText("Contains text in subject")
        self.predicate_filter = QLineEdit()
        self.predicate_filter.setPlaceholderText("Contains text in predicate")
        self.object_filter = QLineEdit()
        self.object_filter.setPlaceholderText("Contains text in object")

        self.subject_filter.textChanged.connect(self.apply_filters)
        self.predicate_filter.textChanged.connect(self.apply_filters)
        self.object_filter.textChanged.connect(self.apply_filters)

        clear_filters_btn = QPushButton("Clear")
        clear_filters_btn.clicked.connect(self.clear_filters)

        filter_layout.addWidget(QLabel("Subject"), 0, 0)
        filter_layout.addWidget(self.subject_filter, 0, 1)
        filter_layout.addWidget(QLabel("Predicate"), 1, 0)
        filter_layout.addWidget(self.predicate_filter, 1, 1)
        filter_layout.addWidget(QLabel("Object"), 2, 0)
        filter_layout.addWidget(self.object_filter, 2, 1)
        filter_layout.addWidget(clear_filters_btn, 0, 2, 3, 1)

        triples_layout.addWidget(filter_box)

        self.triples_count_label = QLabel("Triples: 0")
        triples_layout.addWidget(self.triples_count_label)

        self.triples_table = QTableWidget(0, 3)
        self.triples_table.setHorizontalHeaderLabels(["Subject", "Predicate", "Object"])
        self.triples_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.triples_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.triples_table.itemSelectionChanged.connect(self.on_triples_selection_changed)
        triples_layout.addWidget(self.triples_table, 1)

        self.tabs.addTab(triples_tab, "Triples")

        query_tab = QWidget()
        query_layout = QVBoxLayout(query_tab)
        self.query_results_table = QTableWidget(0, 0)
        self.query_results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.query_results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.query_results_table.itemSelectionChanged.connect(self.on_query_selection_changed)
        query_layout.addWidget(self.query_results_table, 1)
        self.tabs.addTab(query_tab, "Query Results")

        network_tab = QWidget()
        network_layout = QVBoxLayout(network_tab)

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

        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(self.fit_network_view)
        network_controls.addWidget(fit_button)

        network_layout.addLayout(network_controls)

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

        self.tabs.addTab(network_tab, "Network")

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        row_group = QGroupBox("Selected Row Details")
        row_layout = QVBoxLayout(row_group)
        self.detail_text = QTextBrowser()
        self.detail_text.setReadOnly(True)
        self.detail_text.setOpenExternalLinks(True)
        row_layout.addWidget(self.detail_text)

        metadata_group = QGroupBox("PMID Metadata")
        metadata_layout = QVBoxLayout(metadata_group)
        self.metadata_status_label = QLabel("")
        self.metadata_status_label.setWordWrap(True)
        self.metadata_text = QTextBrowser()
        self.metadata_text.setReadOnly(True)
        self.metadata_text.setOpenExternalLinks(True)
        metadata_layout.addWidget(self.metadata_status_label)
        metadata_layout.addWidget(self.metadata_text, 1)

        layout.addWidget(row_group, 1)
        layout.addWidget(metadata_group, 1)
        return panel

    def _populate_query_list(self) -> None:
        self.query_list.clear()
        for query_name in self.query_service.list_query_files():
            self.query_list.addItem(query_name)

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

        try:
            graph = self.graph_service.load_nt_graph(graph_path)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))
            return

        self.graph = graph
        self.current_graph_path = graph_path
        self.all_triples = self.graph_service.triples_to_rows(graph)
        self._load_binning_metadata(graph_path)
        self.filtered_triples = list(self.all_triples)

        if os.path.isdir(self.graph_dir):
            graph_name = os.path.basename(graph_path)
            if graph_name.lower().endswith(".nt"):
                if graph_name not in self.available_graph_files:
                    self._populate_graph_list()
                if graph_name in self.available_graph_files:
                    self.graph_combo.setCurrentText(graph_name)

        self.graph_label.setText(f"Loaded: {graph_path} ({len(self.all_triples)} triples)")
        self.apply_filters()

    def _load_binning_metadata(self, graph_path: str) -> None:
        self.binning_metadata = self.graph_service.load_binning_metadata(graph_path)

    def apply_filters(self) -> None:
        self.filtered_triples = self.graph_service.filter_triples(
            self.all_triples,
            subject_filter=self.subject_filter.text(),
            predicate_filter=self.predicate_filter.text(),
            object_filter=self.object_filter.text(),
        )
        self._render_triples_table(self.filtered_triples)
        self.refresh_network_view()

    def clear_filters(self) -> None:
        self.subject_filter.clear()
        self.predicate_filter.clear()
        self.object_filter.clear()
        self.apply_filters()

    def _render_triples_table(self, triples: List[Tuple[str, str, str]]) -> None:
        to_show = triples[:DEFAULT_VISIBLE_TRIPLES]
        self.triples_table.setRowCount(len(to_show))
        self.triples_table.setColumnCount(3)

        for row_idx, (subj, pred, obj) in enumerate(to_show):
            self.triples_table.setItem(row_idx, 0, self._make_table_item(subj, raw_value=subj))
            self.triples_table.setItem(row_idx, 1, self._make_table_item(pred, raw_value=pred))
            self.triples_table.setItem(row_idx, 2, self._make_table_item(obj, raw_value=obj))

        suffix = ""
        if len(triples) > DEFAULT_VISIBLE_TRIPLES:
            suffix = f" (showing first {DEFAULT_VISIBLE_TRIPLES})"
        self.triples_count_label.setText(f"Triples: {len(triples)}{suffix}")
        self.triples_table.resizeColumnsToContents()

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

        self.query_status_label.setText(f"Running {query_name}...")
        self.run_query_button.setEnabled(False)

        worker = QueryWorker(
            graph=self.graph,
            query_name=query_name,
            pmid=pmid,
            query_service=self.query_service,
            callback=self.query_result_signal.emit,
        )
        worker.start()
        self._active_worker = worker

    def on_query_result(self, headers: List[str], rows: List[List[str]], error: str) -> None:
        self.run_query_button.setEnabled(True)

        if error:
            self.query_status_label.setText(f"Query failed: {error}")
            QMessageBox.warning(self, "Query Error", error)
            return

        self.current_query_result = QueryResultTable(headers=headers, rows=rows)
        self._render_query_results(headers, rows)
        self.tabs.setCurrentIndex(1)
        self.query_status_label.setText(f"Query returned {len(rows)} rows")

    def _render_query_results(self, headers: List[str], rows: List[List[str]]) -> None:
        self.query_results_table.setColumnCount(len(headers))
        self.query_results_table.setHorizontalHeaderLabels(headers)
        self.query_results_table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row):
                self.query_results_table.setItem(row_idx, col_idx, self._make_table_item(value, raw_value=value))

        self.query_results_table.resizeColumnsToContents()

    def _make_table_item(self, value: str, raw_value: str = "") -> QTableWidgetItem:
        raw = raw_value if raw_value else value
        graph_service = self.__dict__.get("graph_service")
        if graph_service is not None:
            display = graph_service.display_value(raw)
        else:
            display = raw

        item = QTableWidgetItem(display)
        item.setData(ITEM_USER_ROLE, raw)

        tooltip = self._format_bin_metadata([raw])
        if tooltip:
            item.setToolTip(tooltip)
        return item

    def refresh_network_view(self) -> None:
        self.network_scene.clear()
        self._network_node_lookup = {}

        if not self.filtered_triples:
            self.network_summary_label.setText("Nodes: 0 | Edges: 0")
            return

        model = self.graph_service.build_network_model(
            self.filtered_triples,
            max_edges=int(self.network_edge_limit.value()),
            label_resolver=self.graph_service.display_value,
        )
        self._network_node_lookup = {node.identifier: node for node in model.nodes}
        positions = self._compute_network_positions(model.nodes)

        node_items: Dict[str, NetworkNodeItem] = {}

        for node in model.nodes:
            pos = positions.get(node.identifier)
            if pos is None:
                continue

            node_item = NetworkNodeItem(NETWORK_NODE_RADIUS)
            node_item.setBrush(QBrush(self._network_node_color(node)))
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
            self.network_scene.addItem(edge_item)

        self.network_summary_label.setText(f"Nodes: {len(model.nodes)} | Edges: {len(model.edges)}")
        self.fit_network_view()

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
            return

        node_identifier = selected_items[0].data(0)
        if not isinstance(node_identifier, str):
            return

        node = self._network_node_lookup.get(node_identifier)
        if node is None:
            return

        values = [
            f"Identifier: {node.identifier}",
            f"Label: {node.label}",
            f"Degree: {node.degree}",
        ]
        self._update_detail_and_metadata(values)

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
            return

        values = [
            self._table_value(self.triples_table, row, 0),
            self._table_value(self.triples_table, row, 1),
            self._table_value(self.triples_table, row, 2),
        ]
        self._update_detail_and_metadata(values)

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
        browser.setHtml(
            "<html><head><style>"
            "body { font-family: Segoe UI, sans-serif; font-size: 11pt; }"
            "a { color: #1e5fbf; text-decoration: underline; }"
            "</style></head><body>"
            f"{self._linkify_text(text)}"
            "</body></html>"
        )

    def _update_detail_and_metadata(self, values: List[str]) -> None:
        self._set_linkified_text(self.detail_text, "\n".join(values))

        bin_info = self._format_bin_metadata(values)
        if bin_info:
            self._set_linkified_text(self.metadata_text, bin_info)
            return

        pmid = MetadataService.extract_pmid_from_values(values)
        if not pmid:
            self._set_linkified_text(self.metadata_text, "No PMID detected in selected row")
            return

        metadata = self.metadata_service.get_by_pmid(pmid)
        if not metadata:
            self._set_linkified_text(self.metadata_text, f"PMID {pmid} not found in metadata")
            return

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

        self._set_linkified_text(self.metadata_text, "\n".join(lines))

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

    def _load_settings(self) -> None:
        if not os.path.exists(self.settings_path):
            return

        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
            if not isinstance(settings, dict):
                return
        except Exception:
            return

        geometry_hex = settings.get("window_geometry")
        if isinstance(geometry_hex, str):
            try:
                self.restoreGeometry(bytes.fromhex(geometry_hex))
            except Exception:
                pass

        last_graph = settings.get("last_graph_path", "")
        if isinstance(last_graph, str) and last_graph and os.path.exists(last_graph):
            self.load_graph(last_graph)

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
