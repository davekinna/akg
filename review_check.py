#!/usr/bin/env python3
"""
Review Check - Qt GUI tool for reviewing tracking file entries
Displays files where step=1 and suitable=TRUE with associated metadata
"""

import os
import sys
import argparse
import json
from typing import Any, Dict, Optional, Tuple
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QTextEdit, 
                             QLabel, QPushButton, QGridLayout, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QSpinBox, 
                             QCheckBox, QComboBox, QMessageBox, QStyle, QLineEdit)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor


# Preview/table display
MAX_DISPLAY_CELL_CHARS = 20
DEFAULT_PREVIEW_VISIBLE_ROWS = 10
PREVIEW_EXTRA_PADDING_PX = 36

# Article panel display
ABSTRACT_PREVIEW_MAX_LINES = 5
ABSTRACT_PREVIEW_MAX_CHARS = 1200
ABSTRACT_COLLAPSED_HEIGHT = 110
ABSTRACT_EXPANDED_HEIGHT = 260

# Persisted settings
SETTINGS_FILENAME = 'review_check_settings.json'

# Field status styles
FIELD_STYLE_OK = 'color: green; font-weight: bold;'
FIELD_STYLE_ERR = 'color: red; font-weight: bold;'
FIELD_STYLE_WARN_LABEL = (
    'color: #B00020; font-weight: bold; '
    'background-color: #FDECEA; border: 1px solid #F5C2C7; '
    'border-radius: 4px; padding: 1px 6px;'
)


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


def read_csv_as_dataframe(file_path: str, num_rows: int = 20) -> Optional[pd.DataFrame]:
    """
    Read CSV file as pandas DataFrame
    
    Parameters:
        file_path: str - path to CSV file
        num_rows: int - number of rows to read
        
    Returns:
        Optional[pd.DataFrame] - the data, or None if error/not CSV
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


def normalize_pmid(value: Any) -> str:
    """Normalize PMID value to a comparable string key."""
    if pd.isna(value):
        return ''
    pmid = str(value).strip()
    if pmid.endswith('.0') and pmid[:-2].isdigit():
        pmid = pmid[:-2]
    return pmid


def load_article_metadata_by_pmid(metadata_file: str) -> Tuple[Dict[str, Dict[str, str]], str]:
    """Load article metadata CSV into lookup keyed by normalized PMID.

    Returns:
        (lookup, status_message)
    """
    if not os.path.exists(metadata_file):
        return {}, f'Article metadata file not found: {metadata_file}. Continuing without article metadata.'

    try:
        metadata_df = pd.read_csv(metadata_file, keep_default_na=False)
    except Exception as e:
        return {}, f'Failed to read article metadata file {metadata_file}: {e}. Continuing without article metadata.'

    column_map = {str(col).strip().lower(): col for col in metadata_df.columns}

    pmid_col = None
    for candidate in ('pmid', 'pubmed_id', 'pubmedid', 'pubmed id'):
        if candidate in column_map:
            pmid_col = column_map[candidate]
            break
    if pmid_col is None:
        return {}, f'Article metadata file {metadata_file} is missing a PMID column.'

    lookup: Dict[str, Dict[str, str]] = {}
    for _, row in metadata_df.iterrows():
        pmid_key = normalize_pmid(row.get(pmid_col, ''))
        if not pmid_key:
            continue
        row_dict: Dict[str, str] = {}
        for col in metadata_df.columns:
            key = str(col).strip()
            row_dict[key] = str(row.get(col, '')).strip()
        lookup[pmid_key] = row_dict

    if not lookup:
        return {}, f'Article metadata file {metadata_file} loaded but no valid PMID rows were found.'

    return lookup, ''


def load_ui_settings(settings_file: str) -> Dict[str, Any]:
    """Load persisted UI settings from JSON file."""
    if not os.path.exists(settings_file):
        return {}
    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"Warning: failed to load UI settings from {settings_file}: {e}")
        return {}


def save_ui_settings(settings_file: str, settings: Dict[str, Any]):
    """Save UI settings to JSON file."""
    try:
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Warning: failed to save UI settings to {settings_file}: {e}")


class ReviewCheckWindow(QMainWindow):
    """Main window for the review check application"""
    pending_gene_choices: Dict[int, str]
    pending_pval_choices: Dict[int, str]
    pending_lfc_choices: Dict[int, str]
    pending_excl_values: Dict[int, bool]
    pending_reason_values: Dict[int, str]
    initial_row_values: Dict[int, Dict[str, Any]]
    saved_row_values: Dict[int, Dict[str, Any]]
    article_metadata_by_pmid: Dict[str, Dict[str, str]]
    article_metadata_file: str
    article_metadata_status_message: str
    settings_file: str
    preview_visible_rows: int
    current_article_abstract_text: str
    article_abstract_expanded: bool
    has_unsaved_changes: bool
    
    def __init__(self, tracking_df: pd.DataFrame, tracking_file: str, input_dir: str = 'data'):
        super().__init__()
        
        self.tracking_df = tracking_df
        self.tracking_file = tracking_file
        self.input_dir = input_dir

        tracking_dir = os.path.dirname(os.path.abspath(tracking_file)) or '.'
        self.article_metadata_file = os.path.join(tracking_dir, 'asd_article_metadata.csv')
        self.settings_file = os.path.join(tracking_dir, SETTINGS_FILENAME)
        self.article_metadata_by_pmid, self.article_metadata_status_message = load_article_metadata_by_pmid(self.article_metadata_file)
        self.current_article_abstract_text = ''
        ui_settings = load_ui_settings(self.settings_file)
        self.article_abstract_expanded = bool(ui_settings.get('article_abstract_expanded', False))
        preview_rows_raw = ui_settings.get('preview_visible_rows', DEFAULT_PREVIEW_VISIBLE_ROWS)
        try:
            self.preview_visible_rows = int(preview_rows_raw)
        except (TypeError, ValueError):
            self.preview_visible_rows = DEFAULT_PREVIEW_VISIBLE_ROWS
        self.preview_visible_rows = max(3, min(50, self.preview_visible_rows))

        settings_updated = False
        if ui_settings.get('preview_visible_rows') != self.preview_visible_rows:
            ui_settings['preview_visible_rows'] = self.preview_visible_rows
            settings_updated = True
        if 'article_abstract_expanded' not in ui_settings:
            ui_settings['article_abstract_expanded'] = self.article_abstract_expanded
            settings_updated = True
        if settings_updated:
            save_ui_settings(self.settings_file, ui_settings)
        
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
        self.pending_excl_values = {}  # type: Dict[int, bool]
        self.pending_reason_values = {}  # type: Dict[int, str]
        self.initial_row_values = {}
        self.saved_row_values = {}
        self.has_unsaved_changes = False

        if 'manualreason' not in self.tracking_df.columns:
            self.tracking_df['manualreason'] = ''
        if 'manual' not in self.tracking_df.columns:
            self.tracking_df['manual'] = False

        for idx_int in range(len(self.filtered)):
            row = self.filtered.iloc[idx_int]
            row_values = {
                'skip': int(row['skip']) if pd.notna(row['skip']) else 0,
                'gene': str(row['gene']).strip() if pd.notna(row['gene']) else '',
                'pval': str(row['pval']).strip() if pd.notna(row['pval']) else '',
                'lfc': str(row['lfc']).strip() if pd.notna(row['lfc']) else '',
                'excl': bool(row['excl']) if pd.notna(row['excl']) else False,
                'manualreason': str(row.get('manualreason', '')).strip() if pd.notna(row.get('manualreason', '')) else ''
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
        self.setGeometry(100, 100, 1200, 900)
        
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

        # Article metadata panel (for selected PMID)
        article_panel = QWidget()
        article_layout = QGridLayout(article_panel)
        article_layout.setContentsMargins(0, 0, 0, 0)
        article_layout.setHorizontalSpacing(8)
        article_layout.setVerticalSpacing(2)

        article_layout.addWidget(QLabel('PMID:'), 0, 0)
        self.article_pmid_value_label = QLabel('')
        self.article_pmid_value_label.setWordWrap(False)
        article_layout.addWidget(self.article_pmid_value_label, 0, 1)

        article_layout.addWidget(QLabel('Title:'), 1, 0)
        self.article_title_value_label = QLabel('')
        self.article_title_value_label.setWordWrap(True)
        self.article_title_value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        article_layout.addWidget(self.article_title_value_label, 1, 1)

        article_layout.addWidget(QLabel('Abstract:'), 2, 0, Qt.AlignmentFlag.AlignTop)
        self.article_abstract_preview = QTextEdit()
        self.article_abstract_preview.setReadOnly(True)
        self.article_abstract_preview.setMaximumHeight(ABSTRACT_COLLAPSED_HEIGHT)
        article_layout.addWidget(self.article_abstract_preview, 2, 1)

        self.toggle_abstract_button = QPushButton('Show more')
        self.toggle_abstract_button.clicked.connect(self.on_toggle_abstract)
        article_layout.addWidget(self.toggle_abstract_button, 3, 1, Qt.AlignmentFlag.AlignRight)

        article_layout.addWidget(QLabel('Other metadata:'), 4, 0, Qt.AlignmentFlag.AlignTop)
        self.article_other_metadata_text = QTextEdit()
        self.article_other_metadata_text.setReadOnly(True)
        self.article_other_metadata_text.setMaximumHeight(95)
        article_layout.addWidget(self.article_other_metadata_text, 4, 1)

        self.article_metadata_status_label = QLabel('')
        self.article_metadata_status_label.setStyleSheet('color: #b00020;')
        self.article_metadata_status_label.setWordWrap(True)
        article_layout.addWidget(self.article_metadata_status_label, 5, 0, 1, 2)

        if self.article_metadata_status_message:
            self.article_metadata_status_label.setText(self.article_metadata_status_message)

        main_layout.addWidget(article_panel)
        
        # Main content grid: left file list, top-right preview, bottom-right metadata
        content_layout = QGridLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setHorizontalSpacing(8)
        content_layout.setVerticalSpacing(8)
        
        # Left side: file list widget
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel('Supplementary files to review:'))
        
        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        self.file_list.setWordWrap(False)  # Don't wrap file names
        self.file_list.setMinimumHeight(500)  # Show at least ~25 rows
        
        for idx, row in self.filtered.iterrows():
            item_text = f"[{row['pmid']}] {row['file']}"
            self.file_list.addItem(item_text)
        
        left_layout.addWidget(self.file_list)
        content_layout.addWidget(left_widget, 0, 0, 2, 1)
        
        # Top-right: preview widget
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        # Preview section
        self.preview_header_label = QLabel('Preview (first 20 rows) of:')
        self.preview_header_label.setWordWrap(False)
        preview_layout.addWidget(self.preview_header_label)
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Read-only
        preview_header = self.preview_table.horizontalHeader()
        if isinstance(preview_header, QHeaderView):
            preview_header.setStretchLastSection(True)
        self.preview_table.setAlternatingRowColors(True)
        preview_layout.addWidget(self.preview_table)
        content_layout.addWidget(preview_widget, 0, 1)

        # Bottom-right: metadata widget
        metadata_widget = QWidget()
        metadata_widget_layout = QVBoxLayout(metadata_widget)
        metadata_widget_layout.setContentsMargins(0, 0, 0, 0)
        
        metadata_layout = QGridLayout()
        metadata_layout.setContentsMargins(0, 6, 0, 0)
        
        # Skip field (editable with spinbox)
        skip_header_label = QLabel('Skip:')
        metadata_layout.addWidget(skip_header_label, 0, 0)
        self.skip_spinbox = QSpinBox()
        self.skip_spinbox.setMinimum(0)
        self.skip_spinbox.setMaximum(10000)
        self.skip_spinbox.valueChanged.connect(self.on_skip_changed)
        metadata_layout.addWidget(self.skip_spinbox, 0, 1)
        
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

        # Bottom row controls
        self.excl_checkbox = QCheckBox('Exclude this file from subsequent reviews')
        self.excl_checkbox.stateChanged.connect(self.on_excl_changed)
        metadata_layout.addWidget(self.excl_checkbox, 4, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)

        self.reason_header_label = QLabel('Exclude reason:')
        metadata_layout.addWidget(self.reason_header_label, 4, 3)
        self.reason_input = QLineEdit()
        self.reason_input.textChanged.connect(self.on_reason_changed)
        metadata_layout.addWidget(self.reason_input, 4, 4)

        metadata_layout.setHorizontalSpacing(16)
        
        metadata_widget_layout.addLayout(metadata_layout)
        content_layout.addWidget(metadata_widget, 1, 1)

        content_layout.setColumnStretch(0, 3)
        content_layout.setColumnStretch(1, 7)
        content_layout.setRowStretch(0, 1)
        content_layout.setRowStretch(1, 0)

        main_layout.addLayout(content_layout)
        
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
        self.adjust_initial_window_size()
    
    def update_display(self, idx: int, use_spinbox_value: bool = False):
        """Update all display fields for the given index"""
        self.current_index = idx
        row = self.filtered.iloc[idx]
        self.update_article_metadata_display(row)
        
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
            self.adjust_preview_table_height()
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
            self.adjust_preview_table_height()

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
        row_excl_value = bool(row['excl']) if pd.notna(row['excl']) else False
        excl_value = self.pending_excl_values.get(idx, row_excl_value)
        self.excl_checkbox.blockSignals(True)
        self.excl_checkbox.setChecked(excl_value)
        self.excl_checkbox.blockSignals(False)

        # Update reason field
        row_reason = str(row.get('manualreason', '')).strip() if pd.notna(row.get('manualreason', '')) else ''
        reason_value = self.pending_reason_values.get(idx, row_reason)
        self.reason_input.blockSignals(True)
        self.reason_input.setText(reason_value)
        self.reason_input.blockSignals(False)
        
        # Gene field
        self.gene_label.setText(self.format_occurrence_display(gene_col, gene_count))
        self.apply_field_match_style(self.gene_header_label, self.gene_label, 'Gene', gene_col, gene_found, gene_count)
        
        # P-value field
        self.pval_label.setText(self.format_occurrence_display(pval_col, pval_count))
        self.apply_field_match_style(self.pval_header_label, self.pval_label, 'P-value', pval_col, pval_found, pval_count)
        
        # Log FC field
        self.lfc_label.setText(self.format_occurrence_display(lfc_col, lfc_count))
        self.apply_field_match_style(self.lfc_header_label, self.lfc_label, 'Log FC', lfc_col, lfc_found, lfc_count)
        
        self.preview_header_label.setText(f'Preview (first 20 rows) of: {full_path}')
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
        self.pending_excl_values[self.current_index] = bool(self.excl_checkbox.isChecked())
        self.update_dirty_state()

    def on_reason_changed(self, value):
        """Track reason text edits for the current row."""
        self.pending_reason_values[self.current_index] = value.strip()
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
        current_reason = self.reason_input.text().strip()

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
        if current_reason != str(saved_current.get('manualreason', current_reason)):
            dirty = True

        for pending_map, field_name in (
            (self.pending_excl_values, 'excl'),
            (self.pending_gene_choices, 'gene'),
            (self.pending_pval_choices, 'pval'),
            (self.pending_lfc_choices, 'lfc'),
            (self.pending_reason_values, 'manualreason'),
        ):
            to_remove = []
            for idx, value in list(pending_map.items()):
                saved_raw = self.saved_row_values.get(idx, {}).get(field_name, '')
                if field_name == 'excl':
                    saved_value = bool(saved_raw)
                else:
                    saved_value = str(saved_raw)
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

    def adjust_preview_table_height(self):
        """Set preview table height from actual displayed rows and chrome sizes."""
        row_count = self.preview_table.rowCount()
        visible_rows = self.preview_visible_rows if row_count <= 0 else min(row_count, self.preview_visible_rows)

        default_row_height = self.preview_table.verticalHeader().defaultSectionSize()
        font_based_row_height = self.preview_table.fontMetrics().height() + 12
        row_unit_height = max(default_row_height, font_based_row_height, 24)
        rows_height = row_unit_height * visible_rows

        header = self.preview_table.horizontalHeader()
        header_height = header.height() if header is not None else 0

        scrollbar_height = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)

        frame_height = self.preview_table.frameWidth() * 2
        target_height = rows_height + header_height + frame_height + scrollbar_height + PREVIEW_EXTRA_PADDING_PX

        self.preview_table.setMinimumHeight(target_height)
        self.preview_table.setMaximumHeight(target_height)

    def adjust_initial_window_size(self):
        """Auto-size window at startup based on rendered layout and screen limits."""
        QApplication.processEvents()

        central = self.centralWidget()
        if central is None:
            return

        hint = central.sizeHint()
        target_width = max(1250, hint.width() + 60)
        target_height = max(980, hint.height() + 100)

        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(target_width, int(available.width() * 0.95))
            target_height = min(target_height, int(available.height() * 0.95))

        self.resize(target_width, target_height)

    def format_occurrence_display(self, value: str, count: int) -> str:
        """Return plain metadata value text for display."""
        return value if value else ''

    def apply_field_match_style(
        self,
        header_label: QLabel,
        value_label: QLabel,
        base_label: str,
        value: str,
        found_once: bool,
        count: int,
    ):
        """Apply status styling + warning text for metadata fields."""
        if value and found_once:
            header_label.setText(f'{base_label}:')
            header_label.setStyleSheet(FIELD_STYLE_OK)
            header_label.setToolTip('')
            value_label.setStyleSheet(FIELD_STYLE_OK)
            return

        if not value:
            reason_text = 'not specified'
            tooltip = f'{base_label} is blank in the tracking record.'
        elif count > 1:
            reason_text = f'occurs {count} times'
            tooltip = f'{base_label} was found multiple times in the selected header row.'
        else:
            reason_text = 'not found'
            tooltip = f'{base_label} was not found in the selected header row.'

        header_label.setText(f'⚠ {base_label} ({reason_text}):')
        header_label.setStyleSheet(FIELD_STYLE_WARN_LABEL)
        header_label.setToolTip(tooltip)
        value_label.setStyleSheet(FIELD_STYLE_ERR)

    def get_article_field(self, article: Dict[str, str], candidate_keys: Tuple[str, ...]) -> str:
        """Get article field value by case-insensitive key matching."""
        key_map = {str(key).strip().lower(): key for key in article.keys()}
        for candidate in candidate_keys:
            if candidate in key_map:
                return str(article.get(key_map[candidate], '')).strip()
        return ''

    def format_other_metadata(self, article: Dict[str, str]) -> str:
        """Format non-primary article metadata fields for display."""
        if not article:
            return '(other metadata not available)'

        excluded = {
            'pmid', 'pubmed_id', 'pubmedid', 'pubmed id',
            'title', 'abstract', 'summary',
            'exclude', 'excl', 'excluded'
        }
        lines = []
        for key, value in article.items():
            key_clean = str(key).strip()
            value_clean = str(value).strip()
            if not key_clean or not value_clean:
                continue
            key_lower = key_clean.lower()
            if key_lower in excluded:
                continue

            if key_lower == 'journal':
                display_key = 'Journal'
            elif key_lower == 'year':
                display_key = 'Year'
            elif key_lower == 'doi':
                display_key = 'DOI'
            else:
                display_key = key_clean

            lines.append(f'{display_key}: {value_clean}')

        return '\n'.join(lines) if lines else '(other metadata not available)'

    def format_abstract_preview(self, abstract_text: str) -> str:
        """Return truncated abstract preview with line/length limits."""
        if not abstract_text:
            return ''

        lines = abstract_text.splitlines()
        was_truncated = False
        if len(lines) > ABSTRACT_PREVIEW_MAX_LINES:
            lines = lines[:ABSTRACT_PREVIEW_MAX_LINES]
            was_truncated = True

        preview = '\n'.join(lines).strip()
        if len(preview) > ABSTRACT_PREVIEW_MAX_CHARS:
            preview = preview[:ABSTRACT_PREVIEW_MAX_CHARS].rstrip()
            was_truncated = True

        if was_truncated and preview:
            preview = f"{preview}..."

        return preview

    def refresh_article_abstract_display(self):
        """Refresh abstract text/height based on expanded/collapsed state."""
        if self.article_abstract_expanded:
            display_text = self.current_article_abstract_text.strip()
            self.article_abstract_preview.setMaximumHeight(ABSTRACT_EXPANDED_HEIGHT)
            self.toggle_abstract_button.setText('Show less')
            self.article_abstract_preview.setPlainText(display_text if display_text else '(abstract not available)')
        else:
            preview = self.format_abstract_preview(self.current_article_abstract_text)
            self.article_abstract_preview.setMaximumHeight(ABSTRACT_COLLAPSED_HEIGHT)
            self.toggle_abstract_button.setText('Show more')
            self.article_abstract_preview.setPlainText(preview if preview else '(abstract not available)')

    def on_toggle_abstract(self):
        """Toggle abstract panel between compact preview and expanded view."""
        self.article_abstract_expanded = not self.article_abstract_expanded
        self.refresh_article_abstract_display()
        save_ui_settings(self.settings_file, {
            'article_abstract_expanded': self.article_abstract_expanded
        })

    def update_article_metadata_display(self, row: pd.Series):
        """Update top article metadata panel for the selected row."""
        pmid_value = normalize_pmid(row.get('pmid', ''))
        self.article_pmid_value_label.setText(pmid_value)

        article = self.article_metadata_by_pmid.get(pmid_value, {})
        title_text = self.get_article_field(article, ('title',))
        abstract_text = self.get_article_field(article, ('abstract', 'summary'))
        self.current_article_abstract_text = abstract_text

        self.article_title_value_label.setText(title_text if title_text else '(title not available)')
        self.refresh_article_abstract_display()
        self.article_other_metadata_text.setPlainText(self.format_other_metadata(article))

        if self.article_metadata_status_message:
            self.article_metadata_status_label.setText(self.article_metadata_status_message)
        else:
            self.article_metadata_status_label.setText('')
    
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
            excl_checked = self.excl_checkbox.isChecked()
            self.tracking_df.loc[original_idx, 'skip'] = self.skip_spinbox.value()
            self.tracking_df.loc[original_idx, 'excl'] = excl_checked
            selected_gene = self.gene_choice_combo.currentText().strip()
            selected_pval = self.pval_choice_combo.currentText().strip()
            selected_lfc = self.lfc_choice_combo.currentText().strip()
            selected_reason = self.reason_input.text().strip()
            self.tracking_df.loc[original_idx, 'gene'] = selected_gene
            self.tracking_df.loc[original_idx, 'pval'] = selected_pval
            self.tracking_df.loc[original_idx, 'lfc'] = selected_lfc
            self.tracking_df.loc[original_idx, 'manualreason'] = selected_reason
            self.tracking_df.loc[original_idx, 'manual'] = bool(excl_checked)

            # Keep filtered copy in sync for in-session navigation
            self.filtered.loc[self.current_index, 'skip'] = self.skip_spinbox.value()
            self.filtered.loc[self.current_index, 'excl'] = self.excl_checkbox.isChecked()
            self.filtered.loc[self.current_index, 'gene'] = selected_gene
            self.filtered.loc[self.current_index, 'pval'] = selected_pval
            self.filtered.loc[self.current_index, 'lfc'] = selected_lfc
            self.filtered.loc[self.current_index, 'manualreason'] = selected_reason
            self.pending_gene_choices[self.current_index] = selected_gene
            self.pending_pval_choices[self.current_index] = selected_pval
            self.pending_lfc_choices[self.current_index] = selected_lfc
            self.pending_excl_values[self.current_index] = bool(excl_checked)
            self.pending_reason_values[self.current_index] = selected_reason

            self.saved_row_values[self.current_index] = {
                'skip': int(self.skip_spinbox.value()),
                'excl': bool(self.excl_checkbox.isChecked()),
                'gene': selected_gene,
                'pval': selected_pval,
                'lfc': selected_lfc,
                'manualreason': selected_reason
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
                    f'lfc={selected_lfc or "(blank)"}, '
                    f'exclude reason={selected_reason or "(blank)"}')
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
