#!/usr/bin/env python3
"""
Review Check - Qt GUI tool for reviewing tracking file entries
Displays files where step=1 and suitable=TRUE with associated metadata
"""

import os
import sys
import argparse
import json
import html
import shutil
import importlib
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import pandas as pd
import requests
from dotenv import load_dotenv
from pmid_utils import load_article_metadata_by_pmid, normalize_pmid
_genai: Any = None
_PdfReader: Any = None
try:
    _genai = importlib.import_module('google.generativeai')
except Exception:
    # Optional dependency: keep app startup working without google-generativeai.
    # PDF-AI controls are disabled later with a user-visible status message.
    pass

# Load environment variables from .env file (same pattern as genai_check.py)
load_dotenv()
try:
    _pypdf = importlib.import_module('pypdf')
    _PdfReader = getattr(_pypdf, 'PdfReader', None)
except Exception:
    # Optional dependency: keep app startup working without pypdf.
    # PDF-AI controls are disabled later with a user-visible status message.
    pass
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTextEdit, 
                             QLabel, QPushButton, QGridLayout, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QSpinBox, 
                             QCheckBox, QComboBox, QMessageBox, QStyle,
                             QFileDialog, QDialog, QTextBrowser, QTreeWidget,
                             QTreeWidgetItem, QAbstractItemView, QSizePolicy, QSplitter)
from PyQt5.QtCore import Qt, pyqtSignal, QPoint, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush


# Preview/table display
MAX_DISPLAY_CELL_CHARS = 20
DEFAULT_PREVIEW_VISIBLE_ROWS = 10
PREVIEW_EXTRA_PADDING_PX = 28

# Article panel display
ABSTRACT_BOX_HEIGHT = 260

# Persisted settings
SETTINGS_FILENAME = 'review_check_settings.json'
OA_PDF_CACHE_FILENAME = 'oa_pdf_cache.json'
OA_PDF_DIRNAME = 'publication_pdfs'
OA_HTTP_TIMEOUT_SECONDS = 20
PDF_AI_TEXT_MAX_CHARS = 120000
PDF_AI_MODEL_NAME = 'gemini-2.0-flash'
PDF_AI_QUESTION_HISTORY_MAX = 30
EXCLUDE_REASON_HISTORY_MAX = 40
EXCLUDE_REASON_COMMON_MAX = 20
LAST_REVIEW_POSITION_KEY = 'last_review_position'

# Field status styles
FIELD_STYLE_OK = 'color: green; font-weight: bold;'
FIELD_STYLE_ERR = 'color: red; font-weight: bold;'
FIELD_STYLE_WARN_LABEL = (
    'color: #B00020; font-weight: bold; '
    'background-color: #FDECEA; border: 1px solid #F5C2C7; '
    'border-radius: 4px; padding: 1px 6px;'
)

# PDF availability badge styles
PDF_BADGE_OK = (
    'color: #1E7D34; font-weight: bold; '
    'background-color: #E8F5E9; border: 1px solid #A5D6A7; '
    'border-radius: 10px; padding: 2px 8px;'
)
PDF_BADGE_WARN = (
    'color: #8A4B00; font-weight: bold; '
    'background-color: #FFF3E0; border: 1px solid #FFCC80; '
    'border-radius: 10px; padding: 2px 8px;'
)
PDF_BADGE_ERR = (
    'color: #B00020; font-weight: bold; '
    'background-color: #FDECEA; border: 1px solid #F5C2C7; '
    'border-radius: 10px; padding: 2px 8px;'
)
PDF_BADGE_NEUTRAL = (
    'color: #555; font-weight: bold; '
    'background-color: #F3F4F6; border: 1px solid #D1D5DB; '
    'border-radius: 10px; padding: 2px 8px;'
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


def load_oa_pdf_cache(cache_file: str) -> Dict[str, Dict[str, str]]:
    """Load cached OA-PDF status by PMID."""
    if not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"Warning: failed to load OA PDF cache from {cache_file}: {e}")
    return {}


def save_oa_pdf_cache(cache_file: str, cache: Dict[str, Dict[str, str]]):
    """Save OA-PDF cache by PMID."""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: failed to save OA PDF cache to {cache_file}: {e}")


def extract_common_exclude_reasons(tracking_df: pd.DataFrame, max_items: int = EXCLUDE_REASON_COMMON_MAX) -> list[str]:
    """Return most frequent non-empty manual exclude reasons from tracking data."""
    if 'manualreason' not in tracking_df.columns:
        return []

    reasons_series = tracking_df['manualreason'].fillna('').astype(str).str.strip()
    reasons = [reason for reason in reasons_series.tolist() if reason]
    if not reasons:
        return []

    counts = Counter(reasons)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    return [reason for reason, _ in ordered[:max_items]]


class ReviewCheckWindow(QMainWindow):
    """Main window for the review check application"""
    ai_query_result_signal = pyqtSignal(str, str)
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
    oa_pdf_cache_file: str
    oa_pdf_dir: str
    oa_pdf_cache: Dict[str, Dict[str, str]]
    pdf_text_cache: Dict[str, str]
    unpaywall_email: str
    google_api_key: str
    preview_visible_rows: int
    pdf_ai_question_history: list[str]
    exclude_reason_history: list[str]
    last_review_position: Dict[str, str]
    common_exclude_reasons: list[str]
    ai_answer_pmid: str
    review_position_labels: list[QLabel]
    current_article_abstract_text: str
    has_unsaved_changes: bool
    file_leaf_items_by_index: Dict[int, QTreeWidgetItem]
    display_order_indices: list[int]
    display_position_by_index: Dict[int, int]
    exclude_all_in_source_checkbox: QCheckBox
    exclude_all_in_publication_checkbox: QCheckBox
    highlighted_file_leaf_item: Optional[QTreeWidgetItem]
    highlighted_source_item: Optional[QTreeWidgetItem]
    tracking_file_button: QPushButton
    refresh_tracking_button: QPushButton
    
    def __init__(
        self,
        tracking_df: pd.DataFrame,
        tracking_file: str,
        input_dir: str = 'data',
        unpaywall_email: str = '',
    ):
        super().__init__()
        
        self.tracking_df = tracking_df
        self.tracking_file = tracking_file
        self.input_dir = input_dir
        self.ai_query_result_signal.connect(self.on_ai_query_result)
        self.unpaywall_email = unpaywall_email.strip() if unpaywall_email else os.environ.get('UNPAYWALL_EMAIL', '').strip()

        tracking_dir = os.path.dirname(os.path.abspath(tracking_file)) or '.'
        self.article_metadata_file = os.path.join(tracking_dir, 'asd_article_metadata.csv')
        self.settings_file = os.path.join(tracking_dir, SETTINGS_FILENAME)
        self.oa_pdf_cache_file = os.path.join(tracking_dir, OA_PDF_CACHE_FILENAME)
        self.oa_pdf_dir = os.path.join(tracking_dir, OA_PDF_DIRNAME)
        self.oa_pdf_cache = load_oa_pdf_cache(self.oa_pdf_cache_file)
        self.pdf_text_cache = {}
        self.ai_answer_pmid = ''
        self.article_metadata_by_pmid, self.article_metadata_status_message = load_article_metadata_by_pmid(self.article_metadata_file)
        self.google_api_key = os.environ.get('GOOGLE_API_KEY', '').strip()
        self.current_article_abstract_text = ''
        self.highlighted_file_leaf_item = None
        self.highlighted_source_item = None
        ui_settings = load_ui_settings(self.settings_file)
        preview_rows_raw = ui_settings.get('preview_visible_rows', DEFAULT_PREVIEW_VISIBLE_ROWS)
        raw_pdf_ai_history = ui_settings.get('pdf_ai_question_history', [])
        raw_reason_history = ui_settings.get('exclude_reason_history', [])
        raw_last_review_position = ui_settings.get(LAST_REVIEW_POSITION_KEY, {})
        self.pdf_ai_question_history = []
        self.exclude_reason_history = []
        self.last_review_position = raw_last_review_position if isinstance(raw_last_review_position, dict) else {}
        self.common_exclude_reasons = extract_common_exclude_reasons(self.tracking_df)
        if isinstance(raw_pdf_ai_history, list):
            seen_questions = set()
            for value in raw_pdf_ai_history:
                question = str(value).strip()
                if not question or question in seen_questions:
                    continue
                seen_questions.add(question)
                self.pdf_ai_question_history.append(question)
                if len(self.pdf_ai_question_history) >= PDF_AI_QUESTION_HISTORY_MAX:
                    break
        if isinstance(raw_reason_history, list):
            seen_reasons = set()
            for value in raw_reason_history:
                reason = str(value).strip()
                if not reason or reason in seen_reasons:
                    continue
                seen_reasons.add(reason)
                self.exclude_reason_history.append(reason)
                if len(self.exclude_reason_history) >= EXCLUDE_REASON_HISTORY_MAX:
                    break
        try:
            self.preview_visible_rows = int(preview_rows_raw)
        except (TypeError, ValueError):
            self.preview_visible_rows = DEFAULT_PREVIEW_VISIBLE_ROWS
        self.preview_visible_rows = max(3, min(50, self.preview_visible_rows))

        settings_updated = False
        if ui_settings.get('preview_visible_rows') != self.preview_visible_rows:
            ui_settings['preview_visible_rows'] = self.preview_visible_rows
            settings_updated = True
        if ui_settings.get('pdf_ai_question_history') != self.pdf_ai_question_history:
            ui_settings['pdf_ai_question_history'] = list(self.pdf_ai_question_history)
            settings_updated = True
        if ui_settings.get('exclude_reason_history') != self.exclude_reason_history:
            ui_settings['exclude_reason_history'] = list(self.exclude_reason_history)
            settings_updated = True
        if ui_settings.get(LAST_REVIEW_POSITION_KEY) != self.last_review_position:
            ui_settings[LAST_REVIEW_POSITION_KEY] = dict(self.last_review_position)
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
        self.review_position_labels = []
        self._post_show_height_fix_done = False
        self._startup_width_cap_active = False

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
        self.setGeometry(100, 100, 1200, 840)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(6, 6, 6, 6)
        
        # Title
        title_label = QLabel('Supplementary Table Review - Entries in tracking file with step=1, suitable=TRUE, excl=FALSE')
        title_font = title_label.font()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(title_label)
        
        # Data directory, tracking file, and total entries on one bordered line
        info_panel = QWidget()
        info_panel.setObjectName('infoLinePanel')
        info_panel.setStyleSheet(
            '#infoLinePanel {border: 1px solid #D1D5DB; border-radius: 6px;}'
        )
        info_layout = QHBoxLayout(info_panel)
        info_layout.setSpacing(10)
        info_layout.setContentsMargins(6, 4, 6, 4)
        dir_label = QLabel(f'Data directory: {self.input_dir}')
        dir_label.setContentsMargins(0, 0, 0, 0)
        info_layout.addWidget(dir_label)
        info_layout.addStretch()
        self.tracking_file_button = QPushButton(f'Tracking file: {os.path.basename(self.tracking_file)}')
        self.tracking_file_button.setFlat(True)
        self.tracking_file_button.setStyleSheet('text-align: left; border: none;')
        self.tracking_file_button.setToolTip('Click to refresh from tracking file')
        self.tracking_file_button.clicked.connect(self.on_refresh_clicked)
        info_layout.addWidget(self.tracking_file_button)
        self.refresh_tracking_button = QPushButton('Refresh')
        self.refresh_tracking_button.setToolTip('Reload tracking file and refresh review list')
        self.refresh_tracking_button.clicked.connect(self.on_refresh_clicked)
        info_layout.addWidget(self.refresh_tracking_button)
        info_layout.addStretch()
        self.total_label = QLabel(f'Total entries: {len(self.filtered)}')
        self.total_label.setContentsMargins(0, 0, 0, 0)
        info_layout.addWidget(self.total_label)
        main_layout.addWidget(info_panel)

        # Article metadata panel (for selected PMID)
        article_panel = QWidget()
        article_panel.setObjectName('articleLowerPanel')
        article_panel.setStyleSheet(
            '#articleLowerPanel {border: 1px solid #D1D5DB; border-radius: 6px;}'
        )
        article_layout = QGridLayout(article_panel)
        article_layout.setContentsMargins(6, 6, 6, 6)
        article_layout.setHorizontalSpacing(10)
        article_layout.setVerticalSpacing(4)

        article_layout.addWidget(QLabel('PMID:'), 0, 0)
        self.article_pmid_value_label = QLabel('')
        self.article_pmid_value_label.setWordWrap(False)
        article_layout.addWidget(self.article_pmid_value_label, 0, 1)

        article_layout.addWidget(QLabel('Text availability:'), 0, 2)
        self.article_pdf_status_label = QLabel('')
        self.article_pdf_status_label.setWordWrap(False)
        article_layout.addWidget(self.article_pdf_status_label, 0, 3, Qt.AlignmentFlag.AlignRight)

        self.browse_pdf_button = QPushButton('Browse PDF...')
        self.browse_pdf_button.clicked.connect(self.on_browse_pdf_for_current_pmid)
        article_layout.addWidget(self.browse_pdf_button, 0, 4, Qt.AlignmentFlag.AlignRight)

        article_layout.addWidget(QLabel('Title:'), 1, 0)
        self.article_title_value_label = QLabel('')
        self.article_title_value_label.setWordWrap(True)
        self.article_title_value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        article_layout.addWidget(self.article_title_value_label, 1, 1)

        article_layout.addWidget(QLabel('Abstract:'), 2, 0, Qt.AlignmentFlag.AlignTop)
        self.article_abstract_preview = QTextEdit()
        self.article_abstract_preview.setReadOnly(True)
        self.article_abstract_preview.setMinimumHeight(ABSTRACT_BOX_HEIGHT)
        self.article_abstract_preview.setMaximumHeight(ABSTRACT_BOX_HEIGHT)
        article_layout.addWidget(self.article_abstract_preview, 2, 1)

        article_layout.addWidget(QLabel('Other metadata:'), 3, 0, Qt.AlignmentFlag.AlignTop)
        self.article_other_metadata_text = QTextBrowser()
        self.article_other_metadata_text.setReadOnly(True)
        self.article_other_metadata_text.setOpenExternalLinks(True)
        self.article_other_metadata_text.setMaximumHeight(95)
        article_layout.addWidget(self.article_other_metadata_text, 3, 1)

        # RHS AI query interface (kept within existing panel height)
        article_layout.addWidget(QLabel('Question:'), 1, 2)
        self.pdf_ai_query_input = QComboBox()
        self.pdf_ai_query_input.setEditable(True)
        self.pdf_ai_query_input.setInsertPolicy(QComboBox.NoInsert)
        for question in self.pdf_ai_question_history:
            self.pdf_ai_query_input.addItem(question)
        question_line_edit = self.pdf_ai_query_input.lineEdit()
        if question_line_edit is not None:
            question_line_edit.setPlaceholderText('Ask a question about the selected PDF text...')
        article_layout.addWidget(self.pdf_ai_query_input, 1, 3)

        ai_question_actions = QWidget()
        ai_question_actions_layout = QHBoxLayout(ai_question_actions)
        ai_question_actions_layout.setContentsMargins(0, 0, 0, 0)
        ai_question_actions_layout.setSpacing(6)
        ai_question_actions_layout.addStretch()

        self.ask_pdf_ai_button = QPushButton('Ask AI')
        self.ask_pdf_ai_button.setStyleSheet('font-weight: bold;')
        self.ask_pdf_ai_button.clicked.connect(self.on_ask_pdf_ai)
        ai_question_actions_layout.addWidget(self.ask_pdf_ai_button)

        self.clear_pdf_ai_history_button = QPushButton('Clear history')
        self.clear_pdf_ai_history_button.clicked.connect(self.on_clear_pdf_ai_history)
        ai_question_actions_layout.addWidget(self.clear_pdf_ai_history_button)
        article_layout.addWidget(ai_question_actions, 1, 4, Qt.AlignmentFlag.AlignRight)

        article_layout.addWidget(QLabel('AI answer:'), 2, 2, Qt.AlignmentFlag.AlignTop)
        self.pdf_ai_answer_text = QTextEdit()
        self.pdf_ai_answer_text.setReadOnly(True)
        self.pdf_ai_answer_text.setMinimumHeight(ABSTRACT_BOX_HEIGHT)
        self.pdf_ai_answer_text.setMaximumHeight(ABSTRACT_BOX_HEIGHT)
        article_layout.addWidget(self.pdf_ai_answer_text, 2, 3, 1, 2)

        self.pdf_ai_status_label = QLabel('')
        self.pdf_ai_status_label.setWordWrap(True)

        lower_nav_widget = self.build_navigation_row_widget()
        lower_nav_container = QWidget()
        lower_nav_layout = QVBoxLayout(lower_nav_container)
        lower_nav_layout.setContentsMargins(0, 0, 0, 0)
        lower_nav_layout.setSpacing(4)

        lower_nav_layout.addWidget(self.pdf_ai_status_label)

        lower_nav_row_layout = QHBoxLayout()
        lower_nav_row_layout.setContentsMargins(0, 0, 0, 0)
        lower_nav_row_layout.setSpacing(0)
        lower_nav_row_layout.addStretch()
        lower_nav_row_layout.addWidget(lower_nav_widget)
        lower_nav_layout.addLayout(lower_nav_row_layout)

        article_layout.addWidget(lower_nav_container, 3, 2, 1, 3)

        self.article_metadata_status_label = QLabel('')
        self.article_metadata_status_label.setStyleSheet('color: #b00020;')
        self.article_metadata_status_label.setWordWrap(True)
        article_layout.addWidget(self.article_metadata_status_label, 5, 0, 1, 2)

        if self.article_metadata_status_message:
            self.article_metadata_status_label.setText(self.article_metadata_status_message)

        article_layout.setColumnStretch(1, 6)
        article_layout.setColumnStretch(3, 6)
        article_layout.setColumnStretch(4, 0)

        # Main content area: draggable splitter between left hierarchy and right review panel
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setChildrenCollapsible(False)
        
        # Left side: file list widget
        left_widget = QWidget()
        left_widget.setObjectName('leftReviewPanel')
        left_widget.setStyleSheet(
            '#leftReviewPanel {border: 1px solid #D1D5DB; border-radius: 6px;}'
        )
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(6)
        left_layout.addWidget(QLabel('Supplementary files to review:'))
        left_widget.setMinimumWidth(480)
        
        self.file_list = QTreeWidget()
        self.file_list.setHeaderLabels(['PMID', 'Supplementary file', 'Individual table file', 'RowIndex'])
        self.file_list.setRootIsDecorated(True)
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setUniformRowHeights(True)
        self.file_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.file_list.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.file_list.setAllColumnsShowFocus(False)
        self.file_list.setStyleSheet(
            'QTreeWidget::item:selected { background-color: transparent; color: palette(text); }'
        )
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        self.file_list.setMinimumHeight(500)  # Show at least ~25 rows
        self.rebuild_file_tree_from_filtered()
        
        left_layout.addWidget(self.file_list)
        content_splitter.addWidget(left_widget)

        # Right side: bordered panel for table characteristics + preview
        right_widget = QWidget()
        right_widget.setObjectName('rightReviewPanel')
        right_widget.setStyleSheet(
            '#rightReviewPanel {border: 1px solid #D1D5DB; border-radius: 6px;}'
        )
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)
        
        # Top-right: metadata widget
        metadata_widget = QWidget()
        metadata_widget_layout = QVBoxLayout(metadata_widget)
        metadata_widget_layout.setContentsMargins(0, 0, 0, 0)
        metadata_widget_layout.setSpacing(6)
        metadata_header_layout = QHBoxLayout()
        metadata_header_layout.setContentsMargins(0, 0, 0, 0)
        metadata_header_layout.setSpacing(6)
        metadata_header_layout.addWidget(QLabel('Review and edit table characteristics for this file (starting values come from genai_check.py):'))
        metadata_header_layout.addStretch()
        self.suitablereason_button = QPushButton('Rationale...')
        self.suitablereason_button.clicked.connect(self.on_show_suitablereason)
        metadata_header_layout.addWidget(self.suitablereason_button)
        metadata_widget_layout.addLayout(metadata_header_layout)

        has_suitablereason_column = 'suitablereason' in self.filtered.columns
        self.suitablereason_button.setEnabled(has_suitablereason_column)
        if not has_suitablereason_column:
            self.suitablereason_button.setToolTip('Tracking file has no suitablereason column.')
        
        metadata_layout = QGridLayout()
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setVerticalSpacing(6)
        
        # Skip field (editable with spinbox)
        skip_header_label = QLabel('Rows to skip:')
        metadata_layout.addWidget(skip_header_label, 0, 0)
        self.skip_spinbox = QSpinBox()
        self.skip_spinbox.setMinimum(0)
        self.skip_spinbox.setMaximum(10000)
        self.skip_spinbox.valueChanged.connect(self.on_skip_changed)
        metadata_layout.addWidget(self.skip_spinbox, 0, 1)
        
        self.gene_header_label = QLabel('Gene column:')
        metadata_layout.addWidget(self.gene_header_label, 1, 0)
        self.gene_label = QLabel('')
        metadata_layout.addWidget(self.gene_label, 1, 1)

        self.gene_choice_header_label = QLabel('Gene column:')
        metadata_layout.addWidget(self.gene_choice_header_label, 1, 3)
        self.gene_choice_combo = QComboBox()
        self.gene_choice_combo.currentIndexChanged.connect(self.on_gene_choice_changed)
        metadata_layout.addWidget(self.gene_choice_combo, 1, 4)

        self.pval_header_label = QLabel('P-value column:')
        metadata_layout.addWidget(self.pval_header_label, 2, 0)
        self.pval_label = QLabel('')
        metadata_layout.addWidget(self.pval_label, 2, 1)

        self.pval_choice_header_label = QLabel('P-value column:')
        metadata_layout.addWidget(self.pval_choice_header_label, 2, 3)
        self.pval_choice_combo = QComboBox()
        self.pval_choice_combo.currentIndexChanged.connect(self.on_pval_choice_changed)
        metadata_layout.addWidget(self.pval_choice_combo, 2, 4)
        
        self.lfc_header_label = QLabel('Log FC column:')
        metadata_layout.addWidget(self.lfc_header_label, 3, 0)
        self.lfc_label = QLabel('')
        metadata_layout.addWidget(self.lfc_label, 3, 1)

        dynamic_header_labels = [
            self.gene_header_label,
            self.pval_header_label,
            self.lfc_header_label,
        ]
        header_width_samples = [
            '⚠ Gene column (not specified):',
            '⚠ Gene column (not found):',
            '⚠ Gene column (occurs 999 times):',
            '⚠ P-value column (not specified):',
            '⚠ P-value column (not found):',
            '⚠ P-value column (occurs 999 times):',
            '⚠ Log FC column (not specified):',
            '⚠ Log FC column (not found):',
            '⚠ Log FC column (occurs 999 times):',
        ]
        header_metrics = self.fontMetrics()
        header_fixed_width = max(header_metrics.horizontalAdvance(text) for text in header_width_samples) + 8
        for dynamic_header in dynamic_header_labels:
            dynamic_header.setMinimumWidth(header_fixed_width)
            dynamic_header.setMaximumWidth(header_fixed_width)

        self.lfc_choice_header_label = QLabel('Log FC column:')
        metadata_layout.addWidget(self.lfc_choice_header_label, 3, 3)
        self.lfc_choice_combo = QComboBox()
        self.lfc_choice_combo.currentIndexChanged.connect(self.on_lfc_choice_changed)
        metadata_layout.addWidget(self.lfc_choice_combo, 3, 4)

        # Bottom row controls
        self.excl_checkbox = QCheckBox('Exclude this file')
        self.excl_checkbox.stateChanged.connect(self.on_excl_changed)
        metadata_layout.addWidget(self.excl_checkbox, 4, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)

        self.exclude_all_in_source_checkbox = QCheckBox('Exclude all tables in this supplementary file')
        self.exclude_all_in_source_checkbox.stateChanged.connect(self.on_exclude_all_in_source_changed)
        metadata_layout.addWidget(self.exclude_all_in_source_checkbox, 5, 0, 1, 4, Qt.AlignmentFlag.AlignLeft)

        self.exclude_all_in_publication_checkbox = QCheckBox('Exclude all tables in this publication')
        self.exclude_all_in_publication_checkbox.stateChanged.connect(self.on_exclude_all_in_publication_changed)
        metadata_layout.addWidget(self.exclude_all_in_publication_checkbox, 7, 0, 1, 5, Qt.AlignmentFlag.AlignLeft)

        self.reason_header_label = QLabel('Exclude reason:')
        metadata_layout.addWidget(self.reason_header_label, 4, 3)
        self.reason_input = QComboBox()
        self.reason_input.setEditable(True)
        self.reason_input.setInsertPolicy(QComboBox.NoInsert)
        self.refresh_exclude_reason_dropdown()
        self.reason_input.editTextChanged.connect(self.on_reason_changed)
        reason_line_edit = self.reason_input.lineEdit()
        if reason_line_edit is not None:
            reason_line_edit.setPlaceholderText('Choose or type an exclude reason...')
        metadata_layout.addWidget(self.reason_input, 4, 4)

        quick_navigation_widget = QWidget()
        quick_navigation_layout = QHBoxLayout(quick_navigation_widget)
        quick_navigation_layout.setContentsMargins(0, 0, 0, 0)
        quick_navigation_layout.setSpacing(6)

        self.reason_prev_button = QPushButton('Previous')
        self.reason_prev_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reason_prev_button.clicked.connect(self.on_previous)
        quick_navigation_layout.addWidget(self.reason_prev_button)

        self.reason_next_button = QPushButton('Next')
        self.reason_next_button.clicked.connect(self.on_next)
        quick_navigation_layout.addWidget(self.reason_next_button)

        self.quick_not_de_next_button = QPushButton('Flag as not DE -> Next')
        self.quick_not_de_next_button.setToolTip("Set reason to 'not differential expression data', exclude this file, then go to next")
        self.quick_not_de_next_button.clicked.connect(self.on_quick_exclude_not_de_next)
        quick_navigation_layout.addWidget(self.quick_not_de_next_button)
        metadata_layout.addWidget(quick_navigation_widget, 5, 3, 1, 2)

        metadata_layout.setHorizontalSpacing(14)
        
        metadata_widget_layout.addLayout(metadata_layout)
        right_layout.addWidget(metadata_widget)

        # Bottom-right: preview widget
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        
        # Preview section
        self.preview_header_label = QLabel('Preview (first 20 rows) of:')
        self.preview_header_label.setWordWrap(False)
        # Allow this label to shrink so long file paths do not expand window minimum width.
        self.preview_header_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.preview_header_label.setMinimumWidth(0)
        preview_layout.addWidget(self.preview_header_label)
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Read-only
        self.preview_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Allow layouts to shrink table width even when content-driven size hints are large.
        self.preview_table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        preview_header = self.preview_table.horizontalHeader()
        if isinstance(preview_header, QHeaderView):
            preview_header.setStretchLastSection(True)
        self.preview_table.setAlternatingRowColors(True)
        preview_layout.addWidget(self.preview_table)
        right_layout.addWidget(preview_widget)
        right_layout.setStretch(0, 0)
        right_layout.setStretch(1, 1)

        right_container = QWidget()
        right_container_layout = QVBoxLayout(right_container)
        right_container_layout.setContentsMargins(0, 0, 0, 0)
        right_container_layout.setSpacing(10)

        # Duplicate navigation row above the right panel
        top_nav_widget = self.build_navigation_row_widget()
        right_container_layout.addWidget(top_nav_widget)
        right_container_layout.addWidget(right_widget)
        right_container_layout.setStretch(0, 0)
        right_container_layout.setStretch(1, 1)

        content_splitter.addWidget(right_container)
        content_splitter.setStretchFactor(0, 4)
        content_splitter.setStretchFactor(1, 6)
        content_splitter.setSizes([680, 980])

        main_layout.addWidget(content_splitter)
        main_layout.addWidget(article_panel)
        self.configure_button_tab_order()
        
        # Load initial display
        initial_idx = self.resolve_initial_review_index()
        self.update_display(initial_idx)
        self.select_file_row(initial_idx)
        self.adjust_initial_window_size()
        QTimer.singleShot(0, lambda: self.reason_next_button.setFocus())
        QTimer.singleShot(0, self.adjust_preview_table_height)
        self.start_oa_pdf_prefetch()
    
    def update_display(self, idx: int, use_spinbox_value: bool = False):
        """Update all display fields for the given index"""
        self.current_index = idx
        self.update_review_position_status()
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
        self.reason_input.setCurrentText(reason_value)
        self.reason_input.blockSignals(False)
        
        # Gene field
        self.gene_label.setText(self.format_occurrence_display(gene_col, gene_count))
        self.apply_field_match_style(self.gene_header_label, self.gene_label, 'Gene column', gene_col, gene_found, gene_count)
        
        # P-value field
        self.pval_label.setText(self.format_occurrence_display(pval_col, pval_count))
        self.apply_field_match_style(self.pval_header_label, self.pval_label, 'P-value column', pval_col, pval_found, pval_count)
        
        # Log FC field
        self.lfc_label.setText(self.format_occurrence_display(lfc_col, lfc_count))
        self.apply_field_match_style(self.lfc_header_label, self.lfc_label, 'Log FC column', lfc_col, lfc_found, lfc_count)
        
        self.preview_header_label.setText(f'Preview (first 20 rows) of: {full_path}')
        self.persist_review_position(idx)
        self.update_dirty_state()

    def update_review_position_status(self):
        """Update bottom status text with current review position."""
        current_position = self.display_position_by_index.get(self.current_index, self.current_index)
        current_one_based = current_position + 1
        total_files = len(self.filtered)
        status_text = f'Reviewing file {current_one_based} out of {total_files}'
        for label in self.review_position_labels:
            label.setText(status_text)

    def get_review_position_identity(self, idx: Optional[int] = None) -> Dict[str, str]:
        """Return a stable identity for the current or given filtered row."""
        target_idx = self.current_index if idx is None else idx
        if target_idx < 0 or target_idx >= len(self.filtered):
            return {}
        row = self.filtered.iloc[target_idx]
        return {
            'path': str(row.get('path', '')).strip(),
            'file': str(row.get('file', '')).strip(),
        }

    def find_filtered_index_by_identity(self, identity: Dict[str, str]) -> Optional[int]:
        """Locate a filtered row index by stored path/file identity."""
        path_value = str(identity.get('path', '')).strip()
        file_value = str(identity.get('file', '')).strip()
        if not path_value or not file_value:
            return None

        matches = self.filtered[
            (self.filtered['path'].astype(str) == path_value) &
            (self.filtered['file'].astype(str) == file_value)
        ]
        if matches.empty:
            return None
        return int(matches.index[0])

    def resolve_initial_review_index(self) -> int:
        """Resolve the row index to show at startup from saved review position."""
        saved_identity = self.last_review_position if isinstance(self.last_review_position, dict) else {}
        restored_idx = self.find_filtered_index_by_identity(saved_identity)
        if restored_idx is not None:
            return restored_idx
        return self.display_order_indices[0] if self.display_order_indices else 0

    def persist_review_position(self, idx: Optional[int] = None):
        """Persist the current review position so it can be restored next session."""
        identity = self.get_review_position_identity(idx)
        if not identity:
            return
        if identity == self.__dict__.get('last_review_position', {}):
            return
        self.last_review_position = identity
        if 'settings_file' in self.__dict__:
            self.update_ui_settings({LAST_REVIEW_POSITION_KEY: dict(self.last_review_position)})

    def build_navigation_row_widget(self) -> QWidget:
        """Create a navigation controls row widget (status + nav/save/close buttons)."""
        nav_widget = QWidget()
        nav_widget.setObjectName('navigationRowPanel')
        nav_widget.setStyleSheet(
            '#navigationRowPanel {border: 1px solid #D1D5DB; border-radius: 6px;}'
        )
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setContentsMargins(6, 4, 6, 4)
        nav_layout.setSpacing(6)
        nav_layout.addStretch()

        status_label = QLabel('')
        total_files = len(self.filtered)
        max_status_text = f'Reviewing file {total_files} out of {total_files}'
        status_width = status_label.fontMetrics().horizontalAdvance(max_status_text) + 16
        status_label.setMinimumWidth(status_width)
        status_label.setMaximumWidth(status_width)
        self.review_position_labels.append(status_label)
        nav_layout.addWidget(status_label)

        self.top_prev_button = QPushButton('Previous')
        self.top_prev_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.top_prev_button.clicked.connect(self.on_previous)
        nav_layout.addWidget(self.top_prev_button)

        self.top_next_button = QPushButton('Next')
        self.top_next_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.top_next_button.clicked.connect(self.on_next)
        nav_layout.addWidget(self.top_next_button)

        reset_button = QPushButton('Reset Fields')
        reset_button.clicked.connect(self.on_reset_fields)
        nav_layout.addWidget(reset_button)

        self.save_button = QPushButton('Save Changes')
        self.save_button.clicked.connect(self.on_save_clicked)
        self.save_button.setStyleSheet('background-color: #4CAF50; color: white; font-weight: bold;')
        nav_layout.addWidget(self.save_button)

        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.on_close_clicked)
        nav_layout.addWidget(self.close_button)

        return nav_widget

    def configure_button_tab_order(self):
        """Set keyboard focus order for the most-used primary action buttons."""
        if not all(
            hasattr(self, attr)
            for attr in (
                'reason_next_button',
                'quick_not_de_next_button',
                'save_button',
                'close_button',
            )
        ):
            return

        self.setTabOrder(self.reason_next_button, self.quick_not_de_next_button)
        self.setTabOrder(self.quick_not_de_next_button, self.save_button)
        self.setTabOrder(self.save_button, self.close_button)
        self.setTabOrder(self.close_button, self.reason_next_button)
    
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
        if not self.excl_checkbox.isChecked() and self.exclude_all_in_source_checkbox.isChecked():
            self.exclude_all_in_source_checkbox.blockSignals(True)
            self.exclude_all_in_source_checkbox.setChecked(False)
            self.exclude_all_in_source_checkbox.blockSignals(False)
        if not self.excl_checkbox.isChecked() and self.exclude_all_in_publication_checkbox.isChecked():
            self.exclude_all_in_publication_checkbox.blockSignals(True)
            self.exclude_all_in_publication_checkbox.setChecked(False)
            self.exclude_all_in_publication_checkbox.blockSignals(False)
        self.pending_excl_values[self.current_index] = bool(self.excl_checkbox.isChecked())
        self.update_dirty_state()

    def on_exclude_all_in_source_changed(self, _state):
        """Require per-file exclusion when bulk supplementary-file exclusion is selected."""
        if self.exclude_all_in_source_checkbox.isChecked() and not self.excl_checkbox.isChecked():
            self.excl_checkbox.setChecked(True)

    def on_exclude_all_in_publication_changed(self, _state):
        """Require per-file exclusion when bulk publication exclusion is selected."""
        if self.exclude_all_in_publication_checkbox.isChecked() and not self.excl_checkbox.isChecked():
            self.excl_checkbox.setChecked(True)

    def on_reason_changed(self, value):
        """Track reason text edits for the current row."""
        reason_text = value.strip()
        if reason_text and not self.excl_checkbox.isChecked():
            self.excl_checkbox.setChecked(True)
        self.pending_reason_values[self.current_index] = reason_text
        self.update_dirty_state()

    def on_quick_exclude_not_de_next(self):
        """One-click shortcut: set common exclude reason, exclude file, and advance."""
        common_reason = 'not differential expression data'
        self.reason_input.setCurrentText(common_reason)
        if not self.excl_checkbox.isChecked():
            self.excl_checkbox.setChecked(True)
        self.on_next()

    def persist_current_reason_to_history(self):
        """Capture current reason text into saved suggestions before navigation."""
        self.add_exclude_reason_to_history(self.get_reason_input_text())

    def get_reason_input_text(self) -> str:
        """Return reason text from either QComboBox or simple test doubles."""
        reason_input = self.__dict__.get('reason_input', None)
        if reason_input is None:
            return ''
        if hasattr(reason_input, 'currentText'):
            return str(reason_input.currentText()).strip()
        if hasattr(reason_input, 'text'):
            return str(reason_input.text()).strip()
        return ''

    def refresh_exclude_reason_dropdown(self):
        """Refresh exclude-reason dropdown options from history + common reasons."""
        reason_input = self.__dict__.get('reason_input', None)
        if reason_input is None:
            return
        if not hasattr(reason_input, 'clear') or not hasattr(reason_input, 'addItem'):
            return

        current_text = self.get_reason_input_text()
        suggestions = []
        seen = set()
        history = list(self.__dict__.get('exclude_reason_history', []))
        common = list(self.__dict__.get('common_exclude_reasons', []))
        for reason in history + common:
            safe_reason = str(reason).strip()
            if not safe_reason or safe_reason in seen:
                continue
            seen.add(safe_reason)
            suggestions.append(safe_reason)

        if hasattr(reason_input, 'blockSignals'):
            reason_input.blockSignals(True)
        reason_input.clear()
        for reason in suggestions:
            reason_input.addItem(reason)
        if hasattr(reason_input, 'setCurrentText'):
            reason_input.setCurrentText(current_text)
        if hasattr(reason_input, 'blockSignals'):
            reason_input.blockSignals(False)

    def add_exclude_reason_to_history(self, reason: str):
        """Persist recent exclude reasons and keep dropdown suggestions in sync."""
        safe_reason = reason.strip()
        if not safe_reason:
            return

        existing_history = list(self.__dict__.get('exclude_reason_history', []))
        history = [item for item in existing_history if item != safe_reason]
        history.insert(0, safe_reason)
        self.exclude_reason_history = history[:EXCLUDE_REASON_HISTORY_MAX]
        self.refresh_exclude_reason_dropdown()
        if 'settings_file' in self.__dict__:
            self.update_ui_settings({'exclude_reason_history': list(self.exclude_reason_history)})

    def on_show_suitablereason(self):
        """Show the suitablereason text for the currently selected supplementary file."""
        popup = getattr(self, '_suitablereason_popup', None)
        if popup is not None and popup.isVisible():
            popup.close()
            self._suitablereason_popup = None
            return

        reason_text = ''
        if 0 <= self.current_index < len(self.filtered):
            row = self.filtered.iloc[self.current_index]
            if 'suitablereason' in self.filtered.columns:
                raw_reason = row.get('suitablereason', '')
                if pd.notna(raw_reason):
                    reason_text = str(raw_reason).strip()

        if not reason_text:
            reason_text = '(No suitablereason text available for this file.)'

        dialog = QDialog(self, flags=Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        dialog.setObjectName('suitablereasonPopup')
        dialog.setStyleSheet(
            '#suitablereasonPopup {background: #FFFBEB; border: 1px solid #D1D5DB; border-radius: 6px;}'
        )

        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(8, 8, 8, 8)
        dialog_layout.setSpacing(6)

        title_label = QLabel('Table characteristics rationale (from genai_check.py)')
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        dialog_layout.addWidget(title_label)

        reason_view = QTextEdit()
        reason_view.setReadOnly(True)
        reason_view.setPlainText(reason_text)
        reason_view.setMinimumSize(480, 200)
        reason_view.setMaximumSize(620, 300)
        reason_view.setStyleSheet('border: none; background: transparent;')
        dialog_layout.addWidget(reason_view)

        anchor_point = self.suitablereason_button.mapToGlobal(
            QPoint(0, self.suitablereason_button.height() + 4)
        )
        dialog.move(anchor_point)
        dialog.show()
        self._suitablereason_popup = dialog

    def update_dirty_state(self):
        """Recompute dirty state from current values vs last saved values."""
        dirty = False

        saved_current = self.saved_row_values.get(self.current_index, {})
        current_skip = int(self.skip_spinbox.value())
        current_excl = bool(self.excl_checkbox.isChecked())
        current_gene = self.gene_choice_combo.currentText().strip()
        current_pval = self.pval_choice_combo.currentText().strip()
        current_lfc = self.lfc_choice_combo.currentText().strip()
        current_reason = self.get_reason_input_text()

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
        if row_count > 0:
            rows_height = sum(self.preview_table.rowHeight(i) for i in range(visible_rows))
        else:
            rows_height = row_unit_height * visible_rows

        header = self.preview_table.horizontalHeader()
        header_height = header.height() if header is not None else 0

        horizontal_scrollbar = self.preview_table.horizontalScrollBar()
        scrollbar_hint_height = horizontal_scrollbar.sizeHint().height() if horizontal_scrollbar is not None else 0
        scrollbar_metric_height = self.preview_table.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        scrollbar_height = max(scrollbar_hint_height, scrollbar_metric_height) + 4

        frame_height = self.preview_table.frameWidth() * 2
        target_height = rows_height + header_height + frame_height + scrollbar_height + PREVIEW_EXTRA_PADDING_PX

        self.preview_table.setMinimumHeight(target_height)
        self.preview_table.setMaximumHeight(target_height)

    def finalize_startup_layout(self):
        """Run one startup-only layout pass after initial paint for accurate table chrome sizing."""
        self.adjust_preview_table_height()
        QApplication.processEvents()
        self.adjust_initial_window_size()
        QApplication.processEvents()

        required_preview_height = self.preview_table.minimumHeight()
        actual_preview_height = self.preview_table.height()
        preview_height_deficit = required_preview_height - actual_preview_height
        if preview_height_deficit > 0:
            max_height = self.get_startup_max_height()
            target_height = min(self.height() + preview_height_deficit + 6, max_height)
            if target_height > self.height():
                self.resize(self.width(), target_height)
                QApplication.processEvents()
                self.adjust_preview_table_height()

        self.ensure_preview_scrollbar_visible_on_startup()
        self.release_startup_width_cap()
        self.clamp_window_to_screen()
        self.focus_primary_action_button()

    def focus_primary_action_button(self):
        """Place keyboard focus on the lower Next button used for rapid review."""
        if hasattr(self, 'reason_next_button'):
            self.reason_next_button.setFocus()

    def apply_startup_width_cap(self, width_cap: int):
        """Temporarily force startup width to avoid oversized layout minimum-width hints."""
        safe_cap = max(900, int(width_cap))
        self.setFixedWidth(safe_cap)
        self._startup_width_cap_active = True

    def release_startup_width_cap(self):
        """Release temporary startup width lock once initial layout settles."""
        if not self._startup_width_cap_active:
            return
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self._startup_width_cap_active = False

    def ensure_preview_scrollbar_visible_on_startup(self):
        """Grow window just enough so preview horizontal scrollbar is not clipped at startup."""
        central = self.centralWidget()
        if central is None:
            return

        max_height = self.get_startup_max_height()
        for _ in range(3):
            QApplication.processEvents()
            horizontal_scrollbar = self.preview_table.horizontalScrollBar()
            scrollbar_bottom = horizontal_scrollbar.mapTo(central, QPoint(0, horizontal_scrollbar.height())).y()
            central_bottom = central.height()
            deficit = scrollbar_bottom - central_bottom
            if deficit <= 0:
                break

            target_height = min(self.height() + deficit + 8, max_height)
            if target_height <= self.height():
                break
            self.resize(self.width(), target_height)
            self.clamp_window_to_screen()

    def showEvent(self, event):
        """Run one post-show sizing pass so startup table chrome is fully accounted for."""
        super().showEvent(event)
        if self._post_show_height_fix_done:
            return
        self._post_show_height_fix_done = True
        QTimer.singleShot(100, self.finalize_startup_layout)
        QTimer.singleShot(180, self.focus_primary_action_button)

    def adjust_initial_window_size(self):
        """Auto-size window at startup based on rendered layout and screen limits."""
        QApplication.processEvents()

        central = self.centralWidget()
        if central is None:
            return

        hint = central.sizeHint()
        target_width = max(1250, hint.width() + 60)
        target_height = max(900, hint.height() + 100)
        target_height += 8

        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(target_width, int(available.width() * 0.95))
            target_height = min(target_height, available.height())
            self.apply_startup_width_cap(target_width)

        target_height = min(target_height, self.get_startup_max_height())

        self.resize(target_width, target_height)
        self.clamp_window_to_screen()

    def clamp_window_to_screen(self):
        """Keep the window fully inside the primary screen's available geometry."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        frame = self.frameGeometry()

        target_x = frame.x()
        target_y = frame.y()

        if frame.width() > available.width():
            self.resize(available.width(), self.height())
            frame = self.frameGeometry()
        if frame.height() > available.height():
            self.resize(self.width(), available.height())
            frame = self.frameGeometry()

        if frame.left() < available.left():
            target_x = available.left()
        elif frame.right() > available.right():
            target_x = available.right() - frame.width() + 1

        if frame.top() < available.top():
            target_y = available.top()
        elif frame.bottom() > available.bottom():
            target_y = available.bottom() - frame.height() + 1

        self.move(target_x, target_y)

    def get_startup_max_height(self) -> int:
        """Return startup window height cap based on available screen height."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return self.height()
        return screen.availableGeometry().height()

    def start_oa_pdf_prefetch(self):
        """Start background OA PDF availability check/download for PMIDs in review list."""
        worker = threading.Thread(target=self.run_oa_pdf_prefetch, daemon=True)
        worker.start()

    def run_oa_pdf_prefetch(self):
        """Background worker: resolve OA PDF URLs and download available PDFs."""
        os.makedirs(self.oa_pdf_dir, exist_ok=True)

        cache = load_oa_pdf_cache(self.oa_pdf_cache_file)
        self.oa_pdf_cache = cache
        unpaywall_email = self.unpaywall_email
        checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

        if not unpaywall_email:
            print('OA PDF prefetch skipped: provide -e/--email or set UNPAYWALL_EMAIL to enable Unpaywall checks.')
            return

        pmid_to_doi: Dict[str, str] = {}
        for _, row in self.filtered.iterrows():
            pmid = normalize_pmid(row.get('pmid', ''))
            if not pmid or pmid in pmid_to_doi:
                continue
            article = self.article_metadata_by_pmid.get(pmid, {})
            doi = self.get_article_field(article, ('doi',))
            pmid_to_doi[pmid] = doi

        downloaded_count = 0
        checked_count = 0

        for pmid, doi in pmid_to_doi.items():
            checked_count += 1
            cached = cache.get(pmid, {})
            cached_path = str(cached.get('pdf_path', '')).strip()
            if str(cached.get('status', '')) == 'downloaded' and cached_path and os.path.exists(cached_path):
                continue

            if not doi:
                cache[pmid] = {
                    'pmid': pmid,
                    'doi': '',
                    'status': 'no_doi',
                    'pdf_url': '',
                    'pdf_path': '',
                    'checked_at': checked_at,
                    'error': ''
                }
                self.oa_pdf_cache[pmid] = cache[pmid]
                continue

            pdf_url, error = self.fetch_oa_pdf_url_from_unpaywall(doi, unpaywall_email)
            if not pdf_url:
                cache[pmid] = {
                    'pmid': pmid,
                    'doi': doi,
                    'status': 'no_oa_pdf',
                    'pdf_url': '',
                    'pdf_path': '',
                    'checked_at': checked_at,
                    'error': error
                }
                self.oa_pdf_cache[pmid] = cache[pmid]
                continue

            output_path = os.path.join(self.oa_pdf_dir, f'{pmid}.pdf')
            ok, download_error = self.download_pdf_file(pdf_url, output_path)
            cache[pmid] = {
                'pmid': pmid,
                'doi': doi,
                'status': 'downloaded' if ok else 'download_failed',
                'pdf_url': pdf_url,
                'pdf_path': output_path if ok else '',
                'checked_at': checked_at,
                'error': download_error
            }
            self.oa_pdf_cache[pmid] = cache[pmid]
            if ok:
                downloaded_count += 1

        save_oa_pdf_cache(self.oa_pdf_cache_file, cache)
        print(
            f'OA PDF prefetch complete: checked {checked_count} PMIDs, '
            f'downloaded {downloaded_count} PDFs into {self.oa_pdf_dir}'
        )

    def fetch_oa_pdf_url_from_unpaywall(self, doi: str, email: str) -> Tuple[str, str]:
        """Resolve best OA PDF URL for DOI via Unpaywall."""
        safe_doi = doi.strip()
        if not safe_doi:
            return '', 'missing DOI'

        endpoint = f'https://api.unpaywall.org/v2/{safe_doi}'
        try:
            response = requests.get(
                endpoint,
                params={'email': email},
                timeout=OA_HTTP_TIMEOUT_SECONDS,
                headers={'User-Agent': 'akg-review-check/1.0'}
            )
        except Exception as e:
            return '', f'unpaywall request failed: {e}'

        if response.status_code != 200:
            return '', f'unpaywall status {response.status_code}'

        try:
            data = response.json()
        except Exception:
            return '', 'unpaywall invalid JSON response'

        best_location = data.get('best_oa_location') or {}
        best_url = str(best_location.get('url_for_pdf') or '').strip()
        if best_url:
            return best_url, ''

        for location in data.get('oa_locations', []) or []:
            candidate = str((location or {}).get('url_for_pdf') or '').strip()
            if candidate:
                return candidate, ''

        return '', 'no OA PDF URL in Unpaywall record'

    def download_pdf_file(self, pdf_url: str, output_path: str) -> Tuple[bool, str]:
        """Download PDF from URL and validate basic PDF signature."""
        try:
            response = requests.get(
                pdf_url,
                timeout=OA_HTTP_TIMEOUT_SECONDS,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
        except Exception as e:
            return False, f'download request failed: {e}'

        if response.status_code != 200:
            return False, f'download status {response.status_code}'

        content = response.content
        if not content.startswith(b'%PDF'):
            return False, 'downloaded content is not a PDF'

        try:
            with open(output_path, 'wb') as f:
                f.write(content)
        except Exception as e:
            return False, f'failed to write PDF: {e}'

        return True, ''

    def format_occurrence_display(self, value: str, count: int) -> str:
        """Return plain metadata value text for display."""
        return value if value else ''

    def get_pdf_availability_status(self, pmid: str) -> Tuple[str, str]:
        """Return display text and style for PDF availability status."""
        cached = self.oa_pdf_cache.get(pmid, {}) if pmid else {}
        status = str(cached.get('status', '')).strip()
        pdf_path = str(cached.get('pdf_path', '')).strip()

        if status == 'downloaded' and pdf_path and os.path.exists(pdf_path):
            return 'Available (downloaded)', PDF_BADGE_OK
        if status == 'downloaded' and (not pdf_path or not os.path.exists(pdf_path)):
            return 'Marked downloaded (file missing)', PDF_BADGE_WARN
        if status == 'no_oa_pdf':
            return 'Not available (no open access PDF)', PDF_BADGE_ERR
        if status == 'no_doi':
            return 'Not checked (no DOI)', PDF_BADGE_WARN
        if status == 'download_failed':
            return 'Download failed', PDF_BADGE_ERR

        if self.unpaywall_email:
            return 'Checking in background...', PDF_BADGE_NEUTRAL
        return 'Not checked (provide -e/--email)', PDF_BADGE_NEUTRAL

    def get_cached_pdf_path_for_pmid(self, pmid: str) -> str:
        """Return local cached/downloaded PDF path for PMID when available."""
        cached = self.oa_pdf_cache.get(pmid, {}) if pmid else {}
        if str(cached.get('status', '')).strip() != 'downloaded':
            return ''
        pdf_path = str(cached.get('pdf_path', '')).strip()
        if pdf_path and os.path.exists(pdf_path):
            return pdf_path
        return ''

    def update_pdf_ai_controls(self, pmid: str):
        """Enable/disable AI query controls based on availability and configuration."""
        pdf_path = self.get_cached_pdf_path_for_pmid(pmid)
        has_pdf = bool(pdf_path)
        has_genai = _genai is not None
        has_pypdf = _PdfReader is not None
        has_key = bool(self.google_api_key)

        enabled = has_pdf and has_genai and has_pypdf and has_key
        self.pdf_ai_query_input.setEnabled(enabled)
        self.ask_pdf_ai_button.setEnabled(enabled)

        if enabled:
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('')
            if self.ai_answer_pmid != pmid:
                self.pdf_ai_answer_text.setPlainText('')
                self.ai_answer_pmid = ''
        elif not has_pdf:
            message = 'AI query unavailable: no cached PDF for this PMID.'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''
        elif not has_pypdf:
            message = 'AI query unavailable: install pypdf to extract PDF text.'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''
        elif not has_genai:
            message = 'AI query unavailable: install google-generativeai.'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''
        elif not has_key:
            message = 'AI query unavailable: set GOOGLE_API_KEY.'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''

    def on_ask_pdf_ai(self):
        """Run AI query against selected PMID PDF text in background."""
        pmid = self.article_pmid_value_label.text().strip()
        question = self.pdf_ai_query_input.currentText().strip()
        pdf_path = self.get_cached_pdf_path_for_pmid(pmid)

        if not pmid:
            message = 'No PMID selected.'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''
            return
        if not pdf_path:
            message = 'No cached PDF found for this PMID.'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''
            return
        if not question:
            message = 'Please enter a question.'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''
            return

        self.add_pdf_ai_question_to_history(question)

        self.ask_pdf_ai_button.setEnabled(False)
        self.pdf_ai_answer_text.setStyleSheet('')
        self.pdf_ai_answer_text.setPlainText('')
        self.pdf_ai_status_label.setText('Querying AI...')

        worker = threading.Thread(
            target=self.run_pdf_ai_query,
            args=(pmid, pdf_path, question),
            daemon=True,
        )
        worker.start()

    def run_pdf_ai_query(self, pmid: str, pdf_path: str, question: str):
        """Background AI query runner; posts UI updates via queued callback."""
        error = ''
        answer = ''
        try:
            if _PdfReader is None:
                raise RuntimeError('pypdf is not installed')
            if _genai is None:
                raise RuntimeError('google-generativeai is not installed')
            if not self.google_api_key:
                raise RuntimeError('GOOGLE_API_KEY is not configured')

            doc_text = self.pdf_text_cache.get(pmid, '')
            if not doc_text:
                reader = _PdfReader(pdf_path)
                parts = []
                for page in reader.pages:
                    parts.append(page.extract_text() or '')
                doc_text = '\n'.join(parts).strip()
                if not doc_text:
                    raise RuntimeError('No extractable text found in PDF')
                if len(doc_text) > PDF_AI_TEXT_MAX_CHARS:
                    doc_text = doc_text[:PDF_AI_TEXT_MAX_CHARS]
                self.pdf_text_cache[pmid] = doc_text

            _genai.configure(api_key=self.google_api_key)
            model = _genai.GenerativeModel(PDF_AI_MODEL_NAME)
            prompt = (
                'You are answering a question about a scientific paper PDF. '
                'Use only the provided extracted text. If the answer is not present, say so clearly.\n\n'
                f'Question: {question}\n\n'
                'Paper text:\n'
                f'{doc_text}'
            )
            response = model.generate_content(prompt)
            answer = str(getattr(response, 'text', '') or '').strip()
            if not answer:
                answer = 'No answer returned by model.'
        except Exception as e:
            error = str(e)
        self.ai_query_result_signal.emit(answer, error)

    def on_ai_query_result(self, answer: str, error: str):
        """Handle AI query completion on UI thread."""
        self.ask_pdf_ai_button.setEnabled(True)
        if error:
            message = f'AI query failed: {error}'
            self.pdf_ai_status_label.setText('')
            self.pdf_ai_answer_text.setStyleSheet('color: #B00020;')
            self.pdf_ai_answer_text.setPlainText(message)
            self.ai_answer_pmid = ''
        else:
            self.pdf_ai_status_label.setText('AI response ready.')
            self.pdf_ai_answer_text.setStyleSheet('')
            self.pdf_ai_answer_text.setPlainText(answer)
            self.ai_answer_pmid = self.article_pmid_value_label.text().strip()

    def on_browse_pdf_for_current_pmid(self):
        """Let user choose a local PDF for current PMID and cache it as available."""
        pmid = self.article_pmid_value_label.text().strip()
        if not pmid:
            QMessageBox.warning(self, 'No PMID', 'No PMID is currently selected.')
            return

        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            'Select PDF for current PMID',
            '',
            'PDF Files (*.pdf);;All Files (*)'
        )
        if not selected_path:
            return

        try:
            os.makedirs(self.oa_pdf_dir, exist_ok=True)
            target_path = os.path.join(self.oa_pdf_dir, f'{pmid}.pdf')

            if os.path.abspath(selected_path) != os.path.abspath(target_path):
                shutil.copyfile(selected_path, target_path)

            checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            existing = self.oa_pdf_cache.get(pmid, {})
            doi = str(existing.get('doi', '')).strip()

            self.oa_pdf_cache[pmid] = {
                'pmid': pmid,
                'doi': doi,
                'status': 'downloaded',
                'pdf_url': 'local-file-selected',
                'pdf_path': target_path,
                'checked_at': checked_at,
                'error': ''
            }
            save_oa_pdf_cache(self.oa_pdf_cache_file, self.oa_pdf_cache)

            current_row = self.filtered.iloc[self.current_index]
            self.update_article_metadata_display(current_row)
            QMessageBox.information(self, 'PDF cached', f'PDF saved for PMID {pmid}.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to cache selected PDF: {e}')

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
            return '<i>(other metadata not available)</i>'

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

            if key_lower == 'doi':
                doi_url = value_clean
                if not doi_url.lower().startswith(('http://', 'https://')):
                    doi_url = f'https://doi.org/{value_clean}'
                value_html = (
                    f'<a href="{html.escape(doi_url, quote=True)}">'
                    f'{html.escape(value_clean)}</a>'
                )
            else:
                value_html = html.escape(value_clean)

            lines.append(f'<b>{html.escape(display_key)}:</b> {value_html}')

        return '<br>'.join(lines) if lines else '<i>(other metadata not available)</i>'

    def refresh_article_abstract_display(self):
        """Refresh abstract text in a fixed-size box."""
        display_text = self.current_article_abstract_text.strip()
        self.article_abstract_preview.setPlainText(display_text if display_text else '(abstract not available)')

    def update_ui_settings(self, updates: Dict[str, Any]):
        """Merge updates into persisted UI settings without dropping existing keys."""
        settings = load_ui_settings(self.settings_file)
        settings.update(updates)
        save_ui_settings(self.settings_file, settings)

    def add_pdf_ai_question_to_history(self, question: str):
        """Persist PDF-AI question history and keep dropdown options in sync."""
        safe_question = question.strip()
        if not safe_question:
            return

        history = [item for item in self.pdf_ai_question_history if item != safe_question]
        history.insert(0, safe_question)
        self.pdf_ai_question_history = history[:PDF_AI_QUESTION_HISTORY_MAX]

        current_text = self.pdf_ai_query_input.currentText().strip()
        self.pdf_ai_query_input.blockSignals(True)
        self.pdf_ai_query_input.clear()
        for item in self.pdf_ai_question_history:
            self.pdf_ai_query_input.addItem(item)
        self.pdf_ai_query_input.setCurrentText(current_text or safe_question)
        self.pdf_ai_query_input.blockSignals(False)

        self.update_ui_settings({'pdf_ai_question_history': list(self.pdf_ai_question_history)})

    def on_clear_pdf_ai_history(self):
        """Clear persisted PDF-AI question history and dropdown entries."""
        if not self.pdf_ai_question_history and self.pdf_ai_query_input.count() == 0:
            self.pdf_ai_status_label.setText('Question history is already empty.')
            return

        confirm = QMessageBox.question(
            self,
            'Clear question history',
            'Clear all saved PDF question history?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.pdf_ai_question_history = []
        self.pdf_ai_query_input.blockSignals(True)
        self.pdf_ai_query_input.clear()
        self.pdf_ai_query_input.setCurrentText('')
        self.pdf_ai_query_input.blockSignals(False)

        question_line_edit = self.pdf_ai_query_input.lineEdit()
        if question_line_edit is not None:
            question_line_edit.setPlaceholderText('Ask a question about the selected PDF text...')

        self.update_ui_settings({'pdf_ai_question_history': []})
        self.pdf_ai_status_label.setText('Question history cleared.')

    def update_article_metadata_display(self, row: pd.Series):
        """Update top article metadata panel for the selected row."""
        pmid_value = normalize_pmid(row.get('pmid', ''))
        self.article_pmid_value_label.setText(pmid_value)

        pdf_text, pdf_style = self.get_pdf_availability_status(pmid_value)
        self.article_pdf_status_label.setText(pdf_text)
        self.article_pdf_status_label.setStyleSheet(pdf_style)
        self.update_pdf_ai_controls(pmid_value)

        article = self.article_metadata_by_pmid.get(pmid_value, {})
        title_text = self.get_article_field(article, ('title',))
        abstract_text = self.get_article_field(article, ('abstract', 'summary'))
        self.current_article_abstract_text = abstract_text

        self.article_title_value_label.setText(title_text if title_text else '(title not available)')
        self.refresh_article_abstract_display()
        self.article_other_metadata_text.setHtml(self.format_other_metadata(article))

        if self.article_metadata_status_message:
            self.article_metadata_status_label.setText(self.article_metadata_status_message)
        else:
            self.article_metadata_status_label.setText('')
    
    def on_file_selected(self):
        """Handle file list selection"""
        self.persist_current_reason_to_history()
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            self.update_file_tree_highlight(None)
            return

        has_selected_leaf = any(item.childCount() == 0 for item in selected_items)
        selected_item = selected_items[0]
        if selected_item.childCount() > 0:
            parent_item = selected_item.parent()
            is_supplementary_node = parent_item is not None and parent_item.parent() is None
            if is_supplementary_node and not has_selected_leaf and selected_item.childCount() > 0:
                first_table_item = selected_item.child(0)
                if first_table_item is not None:
                    self.file_list.setCurrentItem(first_table_item, 2)
                    self.file_list.scrollToItem(first_table_item)
                    return
            self.update_file_tree_highlight(None)
            return

        current_item = selected_item.text(3)
        try:
            idx = int(str(current_item))
        except (TypeError, ValueError):
            self.update_file_tree_highlight(None)
            return

        if 0 <= idx < len(self.filtered):
            self.exclude_all_in_source_checkbox.blockSignals(True)
            self.exclude_all_in_source_checkbox.setChecked(False)
            self.exclude_all_in_source_checkbox.blockSignals(False)
            self.exclude_all_in_publication_checkbox.blockSignals(True)
            self.exclude_all_in_publication_checkbox.setChecked(False)
            self.exclude_all_in_publication_checkbox.blockSignals(False)
            self.update_file_tree_highlight(selected_item)
            self.update_display(idx)

    def rebuild_file_tree_from_filtered(self):
        """Rebuild left file tree from current filtered dataframe."""
        self.file_leaf_items_by_index = {}
        self.display_order_indices = []
        self.display_position_by_index = {}
        self.file_list.clear()
        self.update_file_tree_highlight(None)

        sorted_tree_rows: list[Tuple[int, str, str, str]] = []
        for filtered_idx, (_, row) in enumerate(self.filtered.iterrows()):
            pmid_text = normalize_pmid(row.get('pmid', ''))
            raw_source_text = str(row.get('source', '')).strip() if pd.notna(row.get('source', '')) else ''
            normalized_source_text = raw_source_text.replace('\\', '/')
            source_text = os.path.basename(normalized_source_text) if normalized_source_text else ''
            file_text = str(row.get('file', '')).strip()
            sorted_tree_rows.append((filtered_idx, pmid_text, source_text, file_text))

        sorted_tree_rows.sort(
            key=lambda row_data: (
                str(row_data[1]).lower(),
                str(row_data[2]).lower(),
                str(row_data[3]).lower(),
            )
        )

        pmid_parent_items: dict[str, QTreeWidgetItem] = {}
        source_parent_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        for row_data in sorted_tree_rows:
            filtered_idx = int(row_data[0])
            pmid_text = str(row_data[1])
            source_text = str(row_data[2])
            file_text = str(row_data[3])

            parent_item = pmid_parent_items.get(pmid_text)
            if parent_item is None:
                parent_item = QTreeWidgetItem([pmid_text, '', '', ''])
                self.file_list.addTopLevelItem(parent_item)
                pmid_parent_items[pmid_text] = parent_item

            source_key = (pmid_text, source_text)
            source_item = source_parent_items.get(source_key)
            if source_item is None:
                source_item = QTreeWidgetItem(['', source_text, '', ''])
                parent_item.addChild(source_item)
                source_parent_items[source_key] = source_item

            child_item = QTreeWidgetItem(['', '', file_text, str(filtered_idx)])
            source_item.addChild(child_item)
            self.file_leaf_items_by_index[filtered_idx] = child_item
            self.display_position_by_index[filtered_idx] = len(self.display_order_indices)
            self.display_order_indices.append(filtered_idx)

        self.file_list.expandAll()
        self.file_list.resizeColumnToContents(0)
        self.file_list.resizeColumnToContents(1)
        self.file_list.resizeColumnToContents(2)
        self.file_list.setColumnWidth(1, max(1, int(self.file_list.columnWidth(1))))
        self.file_list.setColumnWidth(2, max(1, int(self.file_list.columnWidth(2) * 0.8)))
        self.file_list.setColumnHidden(3, True)

    def refresh_from_tracking_file(self, preserve_selection: bool = True, show_success_dialog: bool = False) -> bool:
        """Reload tracking file from disk and refresh filtered view/tree."""
        selection_key: Optional[Tuple[str, str]] = None
        if preserve_selection and 0 <= self.current_index < len(self.filtered):
            selected_row = self.filtered.iloc[self.current_index]
            selection_key = (str(selected_row.get('path', '')), str(selected_row.get('file', '')))

        try:
            refreshed_df = load_tracking_file(self.tracking_file)
        except Exception as e:
            QMessageBox.critical(self, 'Refresh failed', f'Failed to reload tracking file: {e}')
            return False

        if 'manualreason' not in refreshed_df.columns:
            refreshed_df['manualreason'] = ''
        if 'manual' not in refreshed_df.columns:
            refreshed_df['manual'] = False

        refreshed_filtered = refreshed_df[
            (refreshed_df['step'] == 1) &
            (refreshed_df['suitable'] == True) &
            (refreshed_df['excl'] == False)
        ].reset_index(drop=True)

        self.tracking_df = refreshed_df
        self.filtered = refreshed_filtered
        self.pending_gene_choices = {}
        self.pending_pval_choices = {}
        self.pending_lfc_choices = {}
        self.pending_excl_values = {}
        self.pending_reason_values = {}
        self.initial_row_values = {}
        self.saved_row_values = {}
        self.has_unsaved_changes = False
        self.common_exclude_reasons = extract_common_exclude_reasons(self.tracking_df)
        self.refresh_exclude_reason_dropdown()

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

        self.total_label.setText(f'Total entries: {len(self.filtered)}')
        self.rebuild_file_tree_from_filtered()

        if len(self.filtered) == 0:
            self.current_index = 0
            self.preview_header_label.setText('Preview: no entries available after refresh.')
            self.preview_table.clear()
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            self.update_review_position_status()
            if show_success_dialog:
                QMessageBox.information(self, 'Refreshed', 'Tracking file refreshed. No entries currently match step=1, suitable=TRUE, excl=FALSE.')
            return True

        target_idx = 0
        if selection_key is not None:
            path_value, file_value = selection_key
            matches = self.filtered[
                (self.filtered['path'].astype(str) == path_value) &
                (self.filtered['file'].astype(str) == file_value)
            ]
            if not matches.empty:
                target_idx = int(matches.index[0])

        self.select_file_row(target_idx)
        if self.file_list.currentItem() is None:
            self.update_display(target_idx)

        if show_success_dialog:
            QMessageBox.information(self, 'Refreshed', 'Tracking file reloaded and display refreshed.')
        return True

    def on_refresh_clicked(self):
        """Handle tracking-file refresh action from top-row controls."""
        self.refresh_from_tracking_file(preserve_selection=True, show_success_dialog=True)

    def select_file_row(self, idx: int):
        """Select row in the left tree widget by filtered index."""
        item = self.file_leaf_items_by_index.get(idx)
        if item is not None:
            self.file_list.setCurrentItem(item, 2)
            self.file_list.scrollToItem(item)

    def clear_file_tree_highlight(self, item: Optional[QTreeWidgetItem], column: int):
        """Clear a custom background highlight from one tree cell."""
        if item is None:
            return
        item.setBackground(column, QBrush())
        item.setForeground(column, QBrush())
        item_font = item.font(column)
        item_font.setBold(False)
        item_font.setUnderline(False)
        item.setFont(column, item_font)

    def update_file_tree_highlight(self, selected_leaf_item: Optional[QTreeWidgetItem]):
        """Highlight the selected table file cell and its parent supplementary file cell."""
        self.clear_file_tree_highlight(self.highlighted_file_leaf_item, 2)
        self.clear_file_tree_highlight(self.highlighted_source_item, 1)
        self.highlighted_file_leaf_item = None
        self.highlighted_source_item = None

        if selected_leaf_item is None:
            return

        source_item = selected_leaf_item.parent()
        self.highlighted_file_leaf_item = selected_leaf_item
        self.highlighted_source_item = source_item
        highlight_bg = QBrush(QColor(196, 224, 255))
        highlight_fg = QBrush(QColor(0, 45, 110))
        selected_leaf_item.setBackground(2, highlight_bg)
        selected_leaf_item.setForeground(2, highlight_fg)
        leaf_font = selected_leaf_item.font(2)
        leaf_font.setBold(True)
        leaf_font.setUnderline(False)
        selected_leaf_item.setFont(2, leaf_font)
        if source_item is not None:
            source_item.setBackground(1, highlight_bg)
            source_item.setForeground(1, highlight_fg)
            source_font = source_item.font(1)
            source_font.setBold(True)
            source_font.setUnderline(False)
            source_item.setFont(1, source_font)
    
    def on_save(self, show_success_dialog: bool = True) -> bool:
        """Save the modified values back to the tracking file."""
        try:
            # Get the original index in the unfiltered dataframe
            current_row = self.filtered.iloc[self.current_index]
            excl_checked = self.excl_checkbox.isChecked()
            exclude_all_in_source = self.exclude_all_in_source_checkbox.isChecked()
            exclude_all_in_publication = self.exclude_all_in_publication_checkbox.isChecked()
            selected_gene = self.gene_choice_combo.currentText().strip()
            selected_pval = self.pval_choice_combo.currentText().strip()
            selected_lfc = self.lfc_choice_combo.currentText().strip()
            selected_reason = self.get_reason_input_text()
            selected_source = str(current_row.get('source', '')).strip() if pd.notna(current_row.get('source', '')) else ''
            selected_pmid = normalize_pmid(current_row.get('pmid', ''))

            self.add_exclude_reason_to_history(selected_reason)

            if exclude_all_in_source and not selected_source:
                raise ValueError('Cannot bulk exclude because the selected row has no supplementary file source')
            if exclude_all_in_publication and not selected_pmid:
                raise ValueError('Cannot bulk exclude because the selected row has no PMID/publication')

            # Collect exclusion/reason updates from all pending rows.
            excl_reason_updates: Dict[int, Tuple[bool, str]] = {}
            pending_rows = set(self.pending_excl_values.keys()) | set(self.pending_reason_values.keys())
            for idx in pending_rows:
                if idx < 0 or idx >= len(self.filtered):
                    continue
                saved_row = self.saved_row_values.get(idx, {})
                row = self.filtered.iloc[idx]
                row_excl_default = bool(saved_row.get('excl', bool(row.get('excl', False))))
                row_reason_default = str(saved_row.get('manualreason', row.get('manualreason', '') or '')).strip()
                row_excl = bool(self.pending_excl_values.get(idx, row_excl_default))
                row_reason = str(self.pending_reason_values.get(idx, row_reason_default)).strip()
                excl_reason_updates[idx] = (row_excl, row_reason)

            # Always include current row UI state.
            excl_reason_updates[self.current_index] = (bool(excl_checked), selected_reason)

            # Collect table-column choice updates from all pending rows.
            column_choice_updates: Dict[int, Tuple[str, str, str]] = {}
            pending_choice_rows = (
                set(self.pending_gene_choices.keys()) |
                set(self.pending_pval_choices.keys()) |
                set(self.pending_lfc_choices.keys())
            )
            for idx in pending_choice_rows:
                if idx < 0 or idx >= len(self.filtered):
                    continue
                saved_row = self.saved_row_values.get(idx, {})
                row = self.filtered.iloc[idx]
                row_gene_default = str(saved_row.get('gene', row.get('gene', '') or '')).strip()
                row_pval_default = str(saved_row.get('pval', row.get('pval', '') or '')).strip()
                row_lfc_default = str(saved_row.get('lfc', row.get('lfc', '') or '')).strip()
                row_gene = str(self.pending_gene_choices.get(idx, row_gene_default)).strip()
                row_pval = str(self.pending_pval_choices.get(idx, row_pval_default)).strip()
                row_lfc = str(self.pending_lfc_choices.get(idx, row_lfc_default)).strip()
                column_choice_updates[idx] = (row_gene, row_pval, row_lfc)

            # Always include current row UI state for table-column choices.
            column_choice_updates[self.current_index] = (selected_gene, selected_pval, selected_lfc)

            # Bulk override for all rows in the same supplementary source.
            if exclude_all_in_source:
                filtered_source_series = self.filtered['source'].fillna('').astype(str).str.strip()
                bulk_indices = self.filtered.index[filtered_source_series == selected_source].tolist()
                for idx in bulk_indices:
                    excl_reason_updates[int(idx)] = (bool(excl_checked), selected_reason)

            if exclude_all_in_publication:
                filtered_pmid_series = self.filtered['pmid'].map(normalize_pmid)
                bulk_pub_indices = self.filtered.index[filtered_pmid_series == selected_pmid].tolist()
                for idx in bulk_pub_indices:
                    excl_reason_updates[int(idx)] = (bool(excl_checked), selected_reason)

            if not excl_reason_updates:
                raise ValueError('No pending exclusion/reason changes to save')

            # Apply exclusion/reason updates to tracking dataframe.
            affected_original_indices: set[int] = set()
            for filtered_idx, (row_excl, row_reason) in excl_reason_updates.items():
                row = self.filtered.iloc[filtered_idx]
                row_mask = (
                    (self.tracking_df['path'] == row['path']) &
                    (self.tracking_df['file'] == row['file'])
                )
                row_original_indices = self.tracking_df.index[row_mask].tolist()
                if not row_original_indices:
                    continue
                self.tracking_df.loc[row_original_indices, 'excl'] = bool(row_excl)
                self.tracking_df.loc[row_original_indices, 'manualreason'] = row_reason
                self.tracking_df.loc[row_original_indices, 'manual'] = bool(row_excl)
                affected_original_indices.update(int(i) for i in row_original_indices)

            if not affected_original_indices:
                raise ValueError('No tracking rows matched pending exclusion/reason updates')

            current_original_indices = self.tracking_df.index[
                (self.tracking_df['path'] == current_row['path']) &
                (self.tracking_df['file'] == current_row['file'])
            ].tolist()
            if not current_original_indices:
                raise ValueError('The selected file could not be found in the tracking dataframe')

            # Apply pending table-column choices to all edited rows.
            for filtered_idx, (row_gene, row_pval, row_lfc) in column_choice_updates.items():
                row = self.filtered.iloc[filtered_idx]
                row_mask = (
                    (self.tracking_df['path'] == row['path']) &
                    (self.tracking_df['file'] == row['file'])
                )
                row_original_indices = self.tracking_df.index[row_mask].tolist()
                if not row_original_indices:
                    continue
                self.tracking_df.loc[row_original_indices, 'gene'] = row_gene
                self.tracking_df.loc[row_original_indices, 'pval'] = row_pval
                self.tracking_df.loc[row_original_indices, 'lfc'] = row_lfc

            # Skip value is controlled only by the active row spinbox.
            self.tracking_df.loc[current_original_indices, 'skip'] = self.skip_spinbox.value()

            # Keep filtered copy in sync for in-session navigation.
            affected_filtered_indices = list(excl_reason_updates.keys())

            current_filtered_indices = [self.current_index]

            for filtered_idx in affected_filtered_indices:
                row_excl, row_reason = excl_reason_updates[filtered_idx]
                self.filtered.loc[filtered_idx, 'excl'] = bool(row_excl)
                self.filtered.loc[filtered_idx, 'manualreason'] = row_reason
                self.pending_excl_values[filtered_idx] = bool(row_excl)
                self.pending_reason_values[filtered_idx] = row_reason

                saved_row = dict(self.saved_row_values.get(filtered_idx, {}))
                saved_row['excl'] = bool(row_excl)
                saved_row['manualreason'] = row_reason
                self.saved_row_values[filtered_idx] = saved_row

            for filtered_idx, (row_gene, row_pval, row_lfc) in column_choice_updates.items():
                self.filtered.loc[filtered_idx, 'gene'] = row_gene
                self.filtered.loc[filtered_idx, 'pval'] = row_pval
                self.filtered.loc[filtered_idx, 'lfc'] = row_lfc
                self.pending_gene_choices[filtered_idx] = row_gene
                self.pending_pval_choices[filtered_idx] = row_pval
                self.pending_lfc_choices[filtered_idx] = row_lfc

                saved_row = dict(self.saved_row_values.get(filtered_idx, {}))
                saved_row['gene'] = row_gene
                saved_row['pval'] = row_pval
                saved_row['lfc'] = row_lfc
                self.saved_row_values[filtered_idx] = saved_row

            for filtered_idx in current_filtered_indices:
                self.filtered.loc[filtered_idx, 'skip'] = self.skip_spinbox.value()
                saved_row = dict(self.saved_row_values.get(filtered_idx, {}))
                saved_row['skip'] = int(self.skip_spinbox.value())
                self.saved_row_values[filtered_idx] = saved_row
            
            # Save the tracking file
            if self.tracking_file.endswith('.xlsx'):
                with pd.ExcelWriter(self.tracking_file) as writer:
                    self.tracking_df.sort_values(by=['step','pmid','file']).to_excel(
                        writer, index=False, sheet_name='akg tracking')
            else:  # CSV
                self.tracking_df.sort_values(by=['step','pmid','file']).to_csv(
                    self.tracking_file, index=False)

            self.refresh_from_tracking_file(preserve_selection=True, show_success_dialog=False)
            
            # Show confirmation
            excl_status = 'EXCLUDED' if self.excl_checkbox.isChecked() else 'included'
            if show_success_dialog:
                affected_count = len(affected_original_indices)
                if exclude_all_in_publication:
                    scope_text = 'all tables in the publication (plus any other pending excludes)'
                elif exclude_all_in_source:
                    scope_text = 'all tables in the supplementary file (plus any other pending excludes)'
                elif len(excl_reason_updates) > 1:
                    scope_text = 'all pending excluded files'
                else:
                    scope_text = 'current file'
                QMessageBox.information(self, 'Success', 
                    f'Saved ({scope_text}, {affected_count} row(s)): skip={self.skip_spinbox.value()}, excl={excl_status}, '
                    f'gene={selected_gene or "(blank)"}, pval={selected_pval or "(blank)"}, '
                    f'lfc={selected_lfc or "(blank)"}, '
                    f'exclude reason={selected_reason or "(blank)"}')
            self.exclude_all_in_source_checkbox.blockSignals(True)
            self.exclude_all_in_source_checkbox.setChecked(False)
            self.exclude_all_in_source_checkbox.blockSignals(False)
            self.exclude_all_in_publication_checkbox.blockSignals(True)
            self.exclude_all_in_publication_checkbox.setChecked(False)
            self.exclude_all_in_publication_checkbox.blockSignals(False)
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
        self.persist_current_reason_to_history()
        if not self.display_order_indices:
            return
        current_pos = self.display_position_by_index.get(self.current_index, 0)
        next_pos = (current_pos + 1) % len(self.display_order_indices)
        idx = self.display_order_indices[next_pos]
        self.select_file_row(idx)
    
    def on_previous(self):
        """Navigate to previous entry"""
        self.persist_current_reason_to_history()
        if not self.display_order_indices:
            return
        current_pos = self.display_position_by_index.get(self.current_index, 0)
        prev_pos = (current_pos - 1) % len(self.display_order_indices)
        idx = self.display_order_indices[prev_pos]
        self.select_file_row(idx)


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
    parser.add_argument(
        '-e', '--email',
        default=None,
        help='Email for Unpaywall API (overrides UNPAYWALL_EMAIL if provided)'
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
        if args.email:
            print(f"Using Unpaywall email from -e/--email: {args.email}")
        
        # Create Qt application and window
        app = QApplication(sys.argv)
        window = ReviewCheckWindow(df, tracking_file, args.input_dir, args.email or '')
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
