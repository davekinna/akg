from pathlib import Path
import json

import pytest

from bin_edam import bin_line, process_file, resolve_output_paths


def test_bin_line_rewrites_numeric_edam_literal():
    line = '<http://example.org/s> <http://edamontology.org/data_3754> "5.0" .'

    result = bin_line(line, v_min=0.0, v_range=10.0)

    assert result == '<http://example.org/s> <http://edamontology.org/data_3754> "bin_5" .'


def test_bin_line_preserves_non_numeric_lines():
    line = '<http://example.org/s> <http://example.org/p> <http://example.org/o> .'
    assert bin_line(line, v_min=0.0, v_range=10.0) == line


def test_resolve_output_paths_for_hdt_defaults_to_binned_name(tmp_path: Path):
    input_path = tmp_path / 'graph.nt'
    input_path.write_text('', encoding='utf-8')

    nt_path, hdt_path = resolve_output_paths(str(input_path), None, 'hdt')

    assert nt_path is None
    assert hdt_path == str(tmp_path / 'graph.binned.hdt')


def test_resolve_output_paths_for_both_uses_base_name(tmp_path: Path):
    input_path = tmp_path / 'graph.nt'
    input_path.write_text('', encoding='utf-8')

    nt_path, hdt_path = resolve_output_paths(str(input_path), str(tmp_path / 'out.nt'), 'both')

    assert nt_path == str(tmp_path / 'out.nt')
    assert hdt_path == str(tmp_path / 'out.hdt')


def test_process_file_writes_nt_and_metadata_sidecar(tmp_path: Path):
    input_path = tmp_path / 'graph.nt'
    output_path = tmp_path / 'graph_binned.nt'
    input_path.write_text(
        '\n'.join([
            '<http://example.org/s1> <http://edamontology.org/data_3754> "1.0" .',
            '<http://example.org/s2> <http://edamontology.org/data_3754> "3.0" .',
        ]) + '\n',
        encoding='utf-8',
    )

    process_file(str(input_path), output_path=str(output_path), output_format='nt')

    assert output_path.exists()
    metadata_path = tmp_path / 'graph_binned.nt.metadata.json'
    assert metadata_path.exists()

    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['data_min'] == 1.0
    assert metadata['data_max'] == 3.0
    assert metadata['data_range'] == 2.0
    assert metadata['binned_values_count'] == 2
    assert metadata['bin_count'] == 10