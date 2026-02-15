#!/usr/bin/env python3
"""
Review Check - Qt GUI tool for reviewing tracking file entries
Displays files where step=1 and suitable=TRUE with associated metadata
"""

import os
import sys
import argparse
from typing import Any, Dict
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, QTextEdit, 
                             QLabel, QPushButton, QGridLayout, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QSplitter, QSpinBox, 
                             QCheckBox, QComboBox, QMessageBox)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QColor


# Single-point config: maximum display width for table cells (in characters)
MAX_DISPLAY_CELL_CHARS = 20

# Single-point config: maximum visible characters for full-path display
MAX_FULL_PATH_DISPLAY_CHARS = 80


def load_tracking_file(filename: str = 'akg_tracking.xlsx') -> pd.DataFrame:
    """
    Load tracking file - supports both .xlsx and .csv formats
    
    Parameters:
        filename: str - path to tracking file
        
    Returns:
        pd.DataFrame - the tracking data
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f'Tracking file {filename} does not exist')
    
    if filename.endswith('.xlsx'):
        with pd.ExcelFile(filename) as xls:
            df = pd.read_excel(xls, "akg tracking", keep_default_na=False)
    else:  # .csv
        df = pd.read_csv(filename, keep_default_na=False)
    
    # Ensure correct dtypes
    df['step'] = df['step'].astype('int')
    df['suitable'] = df['suitable'].astype('bool')
    df['skip'] = df['skip'].astype('int')
    
    return df


def read_file_preview(file_path: str, num_lines: int = 10) -> str:
    """
    Read first num_lines from a file
    
    Parameters:
        file_path: str - path to file
        num_lines: int - number of lines to read
        
    Returns:
        str - content of file (up to num_lines)
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [f.readline() for _ in range(num_lines)]
            content = ''.join(lines)
            return content if content else "(empty file)"
    except Exception as e:
        return f"Error reading file: {e}"


def read_csv_as_dataframe(file_path: str, num_rows: int = 20) -> pd.DataFrame:
    """
    Read CSV file as pandas DataFrame
    
    Parameters:
        file_path: str - path to CSV file
        num_rows: int - number of rows to read
        
    Returns:
        pd.DataFrame - the data, or None if error/not CSV
    """
    try:
        if file_path.endswith('.csv') or file_path.endswith('.tsv'):
            separator = '\t' if file_path.endswith('.tsv') else ','
            # Read without header to show all lines including offset rows
            df = pd.read_csv(file_path, nrows=num_rows, sep=separator, 
                           encoding='utf-8', on_bad_lines='skip', header=None)
            return df
        return None
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return None


class ReviewCheckWindow(QMainWindow):
    """Main window for the review check application"""
    pending_gene_choices: Dict[int, str]
    pending_pval_choices: Dict[int, str]
    pending_lfc_choices: Dict[int, str]
    initial_row_values: Dict[int, Dict[str, Any]]
    saved_row_values: Dict[int, Dict[str, Any]]
    has_unsaved_changes: bool
    
    def __init__(self, tracking_df: pd.DataFrame, tracking_file: str, input_dir: str = 'data'):
        super().__init__()
        
        self.tracking_df = tracking_df
        self.tracking_file = tracking_file
        self.input_dir = input_dir
        
        # Filter data
        self.filtered = tracking_df[(tracking_df['step'] == 1) & 
                                    (tracking_df['suitable'] == True) &
                                    (tracking_df['excl'] == False)].reset_index(drop=True)
        
        if len(self.filtered) == 0:
            raise ValueError('No entries found with step=1, suitable=TRUE, and excl=FALSE')
        
        self.current_index = 0
        self.pending_gene_choices = {}  # type: Dict[int, str]
        self.pending_pval_choices = {}  # type: Dict[int, str]
        self.pending_lfc_choices = {}  # type: Dict[int, str]
        self.initial_row_values = {}
        self.saved_row_values = {}
        self.has_unsaved_changes = False

        for idx, row in self.filtered.iterrows():
            idx_int = int(idx)
            row_values = {
                'skip': int(row['skip']) if pd.notna(row['skip']) else 0,
                'gene': str(row['gene']).strip() if pd.notna(row['gene']) else '',
                'pval': str(row['pval']).strip() if pd.notna(row['pval']) else '',
                'lfc': str(row['lfc']).strip() if pd.notna(row['lfc']) else '',
                'excl': bool(row['excl']) if pd.notna(row['excl']) else False
            }
            self.initial_row_values[idx_int] = {
                'skip': row_values['skip'],
                'gene': row_values['gene'],
                'pval': row_values['pval'],
                'lfc': row_values['lfc']
            }
            self.saved_row_values[idx_int] = row_values
        
        # Set window properties
        self.setWindowTitle('Review Check')
        self.setGeometry(100, 100, 1200, 800)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(2)  # Minimal spacing
        main_layout.setContentsMargins(5, 5, 5, 5)  # Minimal margins
        
        # Title
        title_label = QLabel('Tracking Review - Entries with step=1, suitable=TRUE, excl=FALSE')
        title_font = title_label.font()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(title_label)
        
        # Data directory and total entries on one line
        info_layout = QHBoxLayout()
        info_layout.setSpacing(10)
        info_layout.setContentsMargins(0, 0, 0, 0)
        dir_label = QLabel(f'Data directory: {self.input_dir}')
        dir_label.setContentsMargins(0, 0, 0, 0)
        info_layout.addWidget(dir_label)
        info_layout.addStretch()
        self.total_label = QLabel(f'Total entries: {len(self.filtered)}')
        self.total_label.setContentsMargins(0, 0, 0, 0)
        info_layout.addWidget(self.total_label)
        main_layout.addLayout(info_layout)
        
        # Main content with splitter for resizable panels
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: file list widget
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel('Files to review:'))
        
        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        self.file_list.setWordWrap(False)  # Don't wrap file names
        self.file_list.setMinimumHeight(500)  # Show at least ~25 rows
        
        for idx, row in self.filtered.iterrows():
            item_text = f"[{row['pmid']}] {row['file']}"
            self.file_list.addItem(item_text)
        
        left_layout.addWidget(self.file_list)
        splitter.addWidget(left_widget)
        
        # Right side: preview and metadata widget
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Preview section
        right_layout.addWidget(QLabel('File Preview (first 20 rows):'))
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Read-only
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setAlternatingRowColors(True)
        right_layout.addWidget(self.preview_table)
        
        # Metadata section
        right_layout.addWidget(QLabel('Metadata:'))
        
        metadata_layout = QGridLayout()
        
        # Skip field (editable with spinbox)
        skip_header_label = QLabel('Skip:')
        metadata_layout.addWidget(skip_header_label, 0, 0)
        self.skip_spinbox = QSpinBox()
        self.skip_spinbox.setMinimum(0)
        self.skip_spinbox.setMaximum(10000)
        self.skip_spinbox.valueChanged.connect(self.on_skip_changed)
        metadata_layout.addWidget(self.skip_spinbox, 0, 1)
        
        # Exclude checkbox
        self.excl_checkbox = QCheckBox('Exclude this file from subsequent reviews')
        self.excl_checkbox.stateChanged.connect(self.on_excl_changed)
        metadata_layout.addWidget(self.excl_checkbox, 0, 3, 1, 2, Qt.AlignmentFlag.AlignRight)
        
        self.gene_header_label = QLabel('Gene:')
        metadata_layout.addWidget(self.gene_header_label, 1, 0)
        self.gene_label = QLabel('')
        metadata_layout.addWidget(self.gene_label, 1, 1)

        self.gene_choice_header_label = QLabel('Gene column:')
        metadata_layout.addWidget(self.gene_choice_header_label, 1, 3)
        self.gene_choice_combo = QComboBox()
        self.gene_choice_combo.currentIndexChanged.connect(self.on_gene_choice_changed)
        metadata_layout.addWidget(self.gene_choice_combo, 1, 4)

        self.pval_header_label = QLabel('P-value:')
        metadata_layout.addWidget(self.pval_header_label, 2, 0)
        self.pval_label = QLabel('')
        metadata_layout.addWidget(self.pval_label, 2, 1)

        self.pval_choice_header_label = QLabel('P-value column:')
        metadata_layout.addWidget(self.pval_choice_header_label, 2, 3)
        self.pval_choice_combo = QComboBox()
        self.pval_choice_combo.currentIndexChanged.connect(self.on_pval_choice_changed)
        metadata_layout.addWidget(self.pval_choice_combo, 2, 4)
        
        self.lfc_header_label = QLabel('Log FC:')
        metadata_layout.addWidget(self.lfc_header_label, 3, 0)
        self.lfc_label = QLabel('')
        metadata_layout.addWidget(self.lfc_label, 3, 1)

        self.lfc_choice_header_label = QLabel('Log FC column:')
        metadata_layout.addWidget(self.lfc_choice_header_label, 3, 3)
        self.lfc_choice_combo = QComboBox()
        self.lfc_choice_combo.currentIndexChanged.connect(self.on_lfc_choice_changed)
        metadata_layout.addWidget(self.lfc_choice_combo, 3, 4)

        metadata_layout.setHorizontalSpacing(16)
        
        right_layout.addLayout(metadata_layout)
        
        # Full path
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel('Full path:'))
        self.path_label = QLabel('')
        self.path_label.setWordWrap(False)
        self.path_label.setFont(QFont('Courier', 8))
        path_layout.addWidget(self.path_label)
        path_layout.addStretch()
        right_layout.addLayout(path_layout)
        
        splitter.addWidget(right_widget)
        
        # Set initial splitter sizes (30% left, 70% right)
        splitter.setSizes([300, 900])
        
        main_layout.addWidget(splitter)
        
        # Navigation and Save buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        prev_button = QPushButton('Previous')
        prev_button.clicked.connect(self.on_previous)
        button_layout.addWidget(prev_button)
        
        next_button = QPushButton('Next')
        next_button.clicked.connect(self.on_next)
        button_layout.addWidget(next_button)

        reset_button = QPushButton('Reset Fields')
        reset_button.clicked.connect(self.on_reset_fields)
        button_layout.addWidget(reset_button)
        
        save_button = QPushButton('Save Changes')
        save_button.clicked.connect(self.on_save_clicked)
        save_button.setStyleSheet('background-color: #4CAF50; color: white; font-weight: bold;')
        button_layout.addWidget(save_button)
        
        exit_button = QPushButton('Close')
        exit_button.clicked.connect(self.on_close_clicked)
        button_layout.addWidget(exit_button)
        
        main_layout.addLayout(button_layout)
        
        # Load initial display
        self.update_display(0)
        self.file_list.setCurrentRow(0)
    
    def update_display(self, idx: int, use_spinbox_value: bool = False):
        """Update all display fields for the given index"""
        self.current_index = idx
        row = self.filtered.iloc[idx]
        
        # Build full path
        full_path = os.path.join(row['path'], row['file'])
        
        # Get skip value - use spinbox if we're just updating after user changed it
        if use_spinbox_value:
            skip_value = self.skip_spinbox.value()
        else:
            skip_value = int(row['skip']) if pd.notna(row['skip']) else 0
        
        row_gene_col = str(row['gene']).strip() if pd.notna(row['gene']) else ''
        gene_col = self.pending_gene_choices.get(idx, row_gene_col)
        row_pval_col = str(row['pval']).strip() if pd.notna(row['pval']) else ''
        pval_col = self.pending_pval_choices.get(idx, row_pval_col)
        row_lfc_col = str(row['lfc']).strip() if pd.notna(row['lfc']) else ''
        lfc_col = self.pending_lfc_choices.get(idx, row_lfc_col)
        
        # Read file as DataFrame if CSV, otherwise show raw text
        df = read_csv_as_dataframe(full_path, 20)
        
        # Track which columns are found
        gene_found = False
        pval_found = False
        lfc_found = False
        gene_count = 0
        pval_count = 0
        lfc_count = 0
        
        if df is not None:
            # Display as table
            self.preview_table.clear()
            self.preview_table.setRowCount(len(df))
            self.preview_table.setColumnCount(len(df.columns))
            # Use generic column headers since we're showing raw file
            self.preview_table.setHorizontalHeaderLabels([f'Col {i}' for i in range(len(df.columns))])
            
            # Get the header row values if skip_value is valid
            header_row = None
            if 0 <= skip_value < len(df):
                header_row = df.iloc[skip_value].astype(str).str.strip()

            if header_row is not None:
                header_values = header_row.tolist()
                if gene_col:
                    gene_count = sum(1 for value in header_values if value == gene_col)
                    gene_found = gene_count == 1
                if pval_col:
                    pval_count = sum(1 for value in header_values if value == pval_col)
                    pval_found = pval_count == 1
                if lfc_col:
                    lfc_count = sum(1 for value in header_values if value == lfc_col)
                    lfc_found = lfc_count == 1

            # Populate gene column choices from the highlighted header row
            self.gene_choice_combo.blockSignals(True)
            self.gene_choice_combo.clear()
            self.gene_choice_combo.addItem('')

            self.pval_choice_combo.blockSignals(True)
            self.pval_choice_combo.clear()
            self.pval_choice_combo.addItem('')

            self.lfc_choice_combo.blockSignals(True)
            self.lfc_choice_combo.clear()
            self.lfc_choice_combo.addItem('')

            if header_row is not None:
                seen = set()
                for value in header_row.tolist():
                    value = str(value).strip()
                    if value and value not in seen:
                        seen.add(value)
                        self.gene_choice_combo.addItem(value)
                        self.pval_choice_combo.addItem(value)
                        self.lfc_choice_combo.addItem(value)

            combo_gene_choice = gene_col if gene_col in [self.gene_choice_combo.itemText(i) for i in range(self.gene_choice_combo.count())] else ''
            self.gene_choice_combo.setCurrentText(combo_gene_choice)
            combo_pval_choice = pval_col if pval_col in [self.pval_choice_combo.itemText(i) for i in range(self.pval_choice_combo.count())] else ''
            self.pval_choice_combo.setCurrentText(combo_pval_choice)
            combo_lfc_choice = lfc_col if lfc_col in [self.lfc_choice_combo.itemText(i) for i in range(self.lfc_choice_combo.count())] else ''
            self.lfc_choice_combo.setCurrentText(combo_lfc_choice)

            self.gene_choice_combo.blockSignals(False)
            self.pval_choice_combo.blockSignals(False)
            self.lfc_choice_combo.blockSignals(False)
            
            for i in range(len(df)):
                for j in range(len(df.columns)):
                    cell_value = str(df.iloc[i, j])
                    item = QTableWidgetItem(cell_value)
                    
                    # Highlight the row at 'skip' offset with yellow background
                    if i == skip_value:
                        item.setBackground(QColor(255, 255, 150))  # Light yellow
                        
                        # Check if this cell matches gene/pval/lfc columns
                        cell_stripped = cell_value.strip()
                        match_colors = []
                        if gene_col and cell_stripped == gene_col:
                            match_colors.append(QColor(144, 238, 144) if gene_count == 1 else QColor(255, 182, 182))
                        if pval_col and cell_stripped == pval_col:
                            match_colors.append(QColor(144, 238, 144) if pval_count == 1 else QColor(255, 182, 182))
                        if lfc_col and cell_stripped == lfc_col:
                            match_colors.append(QColor(144, 238, 144) if lfc_count == 1 else QColor(255, 182, 182))

                        if match_colors:
                            if any(color == QColor(255, 182, 182) for color in match_colors):
                                item.setBackground(QColor(255, 182, 182))  # Light red
                            else:
                                item.setBackground(QColor(144, 238, 144))  # Light green
                    
                    self.preview_table.setItem(i, j, item)
            
            # Auto-resize columns to content, then cap to max character width
            self.preview_table.resizeColumnsToContents()
            self.cap_preview_column_widths()
        else:
            # Not a CSV, show raw text preview
            self.preview_table.clear()
            self.preview_table.setRowCount(1)
            self.preview_table.setColumnCount(1)
            self.preview_table.setHorizontalHeaderLabels(['Preview'])
            preview_text = read_file_preview(full_path, 20)
            item = QTableWidgetItem(preview_text)
            self.preview_table.setItem(0, 0, item)
            self.cap_preview_column_widths()

            self.gene_choice_combo.blockSignals(True)
            self.gene_choice_combo.clear()
            self.gene_choice_combo.addItem('')
            self.gene_choice_combo.blockSignals(False)

            self.pval_choice_combo.blockSignals(True)
            self.pval_choice_combo.clear()
            self.pval_choice_combo.addItem('')
            self.pval_choice_combo.blockSignals(False)

            self.lfc_choice_combo.blockSignals(True)
            self.lfc_choice_combo.clear()
            self.lfc_choice_combo.addItem('')
            self.lfc_choice_combo.blockSignals(False)
        
        # Update metadata widgets with color coding
        if not use_spinbox_value:
            # Only update spinbox if we're not using its current value
            self.skip_spinbox.blockSignals(True)  # Prevent triggering value change during update
            self.skip_spinbox.setValue(int(skip_value))
            self.skip_spinbox.blockSignals(False)
        
        # Update exclude checkbox
        excl_value = bool(row['excl']) if pd.notna(row['excl']) else False
        self.excl_checkbox.blockSignals(True)
        self.excl_checkbox.setChecked(excl_value)
        self.excl_checkbox.blockSignals(False)
        
        # Gene field
        self.gene_label.setText(self.format_occurrence_display(gene_col, gene_count))
        if gene_col:
            if gene_found:
                self.gene_header_label.setStyleSheet('color: green; font-weight: bold;')
                self.gene_label.setStyleSheet('color: green; font-weight: bold;')
            else:
                self.gene_header_label.setStyleSheet('color: red; font-weight: bold;')
                self.gene_label.setStyleSheet('color: red; font-weight: bold;')
        else:
            self.gene_header_label.setStyleSheet('color: red; font-weight: bold;')
            self.gene_label.setStyleSheet('color: red; font-weight: bold;')
        
        # P-value field
        self.pval_label.setText(self.format_occurrence_display(pval_col, pval_count))
        if pval_col:
            if pval_found:
                self.pval_header_label.setStyleSheet('color: green; font-weight: bold;')
                self.pval_label.setStyleSheet('color: green; font-weight: bold;')
            else:
                self.pval_header_label.setStyleSheet('color: red; font-weight: bold;')
                self.pval_label.setStyleSheet('color: red; font-weight: bold;')
        else:
            self.pval_header_label.setStyleSheet('color: red; font-weight: bold;')
            self.pval_label.setStyleSheet('color: red; font-weight: bold;')
        
        # Log FC field
        self.lfc_label.setText(self.format_occurrence_display(lfc_col, lfc_count))
        if lfc_col:
            if lfc_found:
                self.lfc_header_label.setStyleSheet('color: green; font-weight: bold;')
                self.lfc_label.setStyleSheet('color: green; font-weight: bold;')
            else:
                self.lfc_header_label.setStyleSheet('color: red; font-weight: bold;')
                self.lfc_label.setStyleSheet('color: red; font-weight: bold;')
        else:
            self.lfc_header_label.setStyleSheet('color: red; font-weight: bold;')
            self.lfc_label.setStyleSheet('color: red; font-weight: bold;')
        
        self.path_label.setText(self.truncate_path_display(full_path))
        self.path_label.setToolTip(full_path)
        self.update_dirty_state()
    
    def on_skip_changed(self, value):
        """Handle skip value change - update display live"""
        self.update_display(self.current_index, use_spinbox_value=True)

    def on_gene_choice_changed(self, _index):
        """Handle user changing gene column choice from dropdown."""
        selected_gene = self.gene_choice_combo.currentText().strip()
        self.pending_gene_choices[self.current_index] = selected_gene
        self.update_display(self.current_index, use_spinbox_value=True)

    def on_pval_choice_changed(self, _index):
        """Handle user changing p-value column choice from dropdown."""
        selected_pval = self.pval_choice_combo.currentText().strip()
        self.pending_pval_choices[self.current_index] = selected_pval
        self.update_display(self.current_index, use_spinbox_value=True)

    def on_lfc_choice_changed(self, _index):
        """Handle user changing log FC column choice from dropdown."""
        selected_lfc = self.lfc_choice_combo.currentText().strip()
        self.pending_lfc_choices[self.current_index] = selected_lfc
        self.update_display(self.current_index, use_spinbox_value=True)

    def on_excl_changed(self, _state):
        """Track unsaved changes when exclude checkbox is changed."""
        self.update_dirty_state()

    def update_dirty_state(self):
        """Recompute dirty state from current values vs last saved values."""
        dirty = False

        saved_current = self.saved_row_values.get(self.current_index, {})
        current_skip = int(self.skip_spinbox.value())
        current_excl = bool(self.excl_checkbox.isChecked())
        current_gene = self.gene_choice_combo.currentText().strip()
        current_pval = self.pval_choice_combo.currentText().strip()
        current_lfc = self.lfc_choice_combo.currentText().strip()

        if current_skip != int(saved_current.get('skip', current_skip)):
            dirty = True
        if current_excl != bool(saved_current.get('excl', current_excl)):
            dirty = True
        if current_gene != str(saved_current.get('gene', current_gene)):
            dirty = True
        if current_pval != str(saved_current.get('pval', current_pval)):
            dirty = True
        if current_lfc != str(saved_current.get('lfc', current_lfc)):
            dirty = True

        for pending_map, field_name in (
            (self.pending_gene_choices, 'gene'),
            (self.pending_pval_choices, 'pval'),
            (self.pending_lfc_choices, 'lfc'),
        ):
            to_remove = []
            for idx, value in list(pending_map.items()):
                saved_value = str(self.saved_row_values.get(int(idx), {}).get(field_name, ''))
                if value == saved_value:
                    to_remove.append(idx)
                else:
                    dirty = True
            for idx in to_remove:
                pending_map.pop(idx, None)

        self.has_unsaved_changes = dirty

    def cap_preview_column_widths(self):
        """Cap preview table column widths to a configurable max character width."""
        if self.preview_table.columnCount() == 0:
            return

        char_width = self.preview_table.fontMetrics().horizontalAdvance('M')
        max_width_px = (char_width * MAX_DISPLAY_CELL_CHARS) + 16

        for col in range(self.preview_table.columnCount()):
            current_width = self.preview_table.columnWidth(col)
            if current_width > max_width_px:
                self.preview_table.setColumnWidth(col, max_width_px)

    def truncate_path_display(self, full_path: str) -> str:
        """Truncate file path for one-line display while preserving start/end context."""
        if len(full_path) <= MAX_FULL_PATH_DISPLAY_CHARS:
            return full_path

        if MAX_FULL_PATH_DISPLAY_CHARS <= 3:
            return '...'

        left_len = (MAX_FULL_PATH_DISPLAY_CHARS - 3) // 2
        right_len = MAX_FULL_PATH_DISPLAY_CHARS - 3 - left_len
        return f"{full_path[:left_len]}...{full_path[-right_len:]}"

    def format_occurrence_display(self, value: str, count: int) -> str:
        """Format metadata value with duplicate occurrence note when needed."""
        if not value:
            return ''
        if count <= 1:
            return value
        if count == 2:
            return f"{value} (occurs twice)"
        return f"{value} (occurs {count} times)"
    
    def on_file_selected(self):
        """Handle file list selection"""
        current_item = self.file_list.currentRow()
        if current_item >= 0:
            self.update_display(current_item)
    
    def on_save(self, show_success_dialog: bool = True) -> bool:
        """Save the modified values back to the tracking file."""
        try:
            # Get the original index in the unfiltered dataframe
            current_row = self.filtered.iloc[self.current_index]
            # Find the row in the original dataframe
            original_idx = self.tracking_df[
                (self.tracking_df['path'] == current_row['path']) &
                (self.tracking_df['file'] == current_row['file'])
            ].index[0]
            
            # Update the skip, excl, gene, pval, and lfc values in the tracking dataframe
            self.tracking_df.loc[original_idx, 'skip'] = self.skip_spinbox.value()
            self.tracking_df.loc[original_idx, 'excl'] = self.excl_checkbox.isChecked()
            selected_gene = self.gene_choice_combo.currentText().strip()
            selected_pval = self.pval_choice_combo.currentText().strip()
            selected_lfc = self.lfc_choice_combo.currentText().strip()
            self.tracking_df.loc[original_idx, 'gene'] = selected_gene
            self.tracking_df.loc[original_idx, 'pval'] = selected_pval
            self.tracking_df.loc[original_idx, 'lfc'] = selected_lfc

            # Keep filtered copy in sync for in-session navigation
            self.filtered.loc[self.current_index, 'skip'] = self.skip_spinbox.value()
            self.filtered.loc[self.current_index, 'excl'] = self.excl_checkbox.isChecked()
            self.filtered.loc[self.current_index, 'gene'] = selected_gene
            self.filtered.loc[self.current_index, 'pval'] = selected_pval
            self.filtered.loc[self.current_index, 'lfc'] = selected_lfc
            self.pending_gene_choices[self.current_index] = selected_gene
            self.pending_pval_choices[self.current_index] = selected_pval
            self.pending_lfc_choices[self.current_index] = selected_lfc

            self.saved_row_values[self.current_index] = {
                'skip': int(self.skip_spinbox.value()),
                'excl': bool(self.excl_checkbox.isChecked()),
                'gene': selected_gene,
                'pval': selected_pval,
                'lfc': selected_lfc
            }
            
            # Save the tracking file
            if self.tracking_file.endswith('.xlsx'):
                with pd.ExcelWriter(self.tracking_file) as writer:
                    self.tracking_df.sort_values(by=['step','pmid','file']).to_excel(
                        writer, index=False, sheet_name='akg tracking')
            else:  # CSV
                self.tracking_df.sort_values(by=['step','pmid','file']).to_csv(
                    self.tracking_file, index=False)
            
            # Show confirmation
            from PyQt5.QtWidgets import QMessageBox
            excl_status = 'EXCLUDED' if self.excl_checkbox.isChecked() else 'included'
            if show_success_dialog:
                QMessageBox.information(self, 'Success', 
                    f'Saved: skip={self.skip_spinbox.value()}, excl={excl_status}, '
                    f'gene={selected_gene or "(blank)"}, pval={selected_pval or "(blank)"}, '
                    f'lfc={selected_lfc or "(blank)"}')
            self.update_dirty_state()
            return True
            
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to save: {e}')
            return False

    def on_save_clicked(self):
        """Handle Save Changes button click."""
        self.on_save()

    def on_close_clicked(self):
        """Handle Close button click."""
        self.close()

    def on_reset_fields(self):
        """Reset skip, gene, pval, and lfc to initial values loaded for current file."""
        confirm = QMessageBox.question(
            self,
            'Confirm Reset',
            'Reset skip, gene, pval, and lfc to initial loaded values for this file?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        initial = self.initial_row_values.get(self.current_index, None)
        if initial is None:
            return

        self.pending_gene_choices[self.current_index] = initial['gene']
        self.pending_pval_choices[self.current_index] = initial['pval']
        self.pending_lfc_choices[self.current_index] = initial['lfc']

        self.skip_spinbox.blockSignals(True)
        self.skip_spinbox.setValue(int(initial['skip']))
        self.skip_spinbox.blockSignals(False)

        self.update_display(self.current_index, use_spinbox_value=True)

    def closeEvent(self, event):
        """Prompt before closing when there are unsaved changes."""
        if not self.has_unsaved_changes:
            event.accept()
            return

        reply = QMessageBox.warning(
            self,
            'Unsaved Changes',
            'You have unsaved changes. Save before exiting?',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save
        )

        if reply == QMessageBox.Save:
            save_ok = self.on_save(show_success_dialog=False)
            if save_ok:
                event.accept()
            else:
                event.ignore()
        elif reply == QMessageBox.Discard:
            event.accept()
        else:
            event.ignore()
    
    
    
    def on_next(self):
        """Navigate to next entry"""
        idx = (self.current_index + 1) % len(self.filtered)
        self.file_list.setCurrentRow(idx)
        self.update_display(idx)
    
    def on_previous(self):
        """Navigate to previous entry"""
        idx = (self.current_index - 1) % len(self.filtered)
        self.file_list.setCurrentRow(idx)
        self.update_display(idx)


def main():
    parser = argparse.ArgumentParser(
        description='Review tracking file entries with step=1, suitable=TRUE, and excl=FALSE'
    )
    parser.add_argument(
        '-i', '--input_dir',
        default='data',
        help='Top-level directory containing the files being reviewed (default: data)'
    )
    parser.add_argument(
        '-t', '--tracking',
        default=None,
        help='Path to tracking file (default: akg_tracking.xlsx in input_dir)'
    )
    
    args = parser.parse_args()
    
    # Resolve tracking file path
    if args.tracking:
        tracking_file = args.tracking
    else:
        tracking_file = os.path.join(args.input_dir, 'akg_tracking.xlsx')
    
    try:
        print(f"Input directory: {args.input_dir}")
        print(f"Loading tracking file: {tracking_file}")
        df = load_tracking_file(tracking_file)
        print(f"Loaded {len(df)} tracking entries")
        
        # Create Qt application and window
        app = QApplication(sys.argv)
        window = ReviewCheckWindow(df, tracking_file, args.input_dir)
        window.show()
        
        sys.exit(app.exec_())
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
