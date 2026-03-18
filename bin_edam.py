import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import json
from typing import Iterable, Optional

# Regex to capture Subject, Predicate, and Object from N-Triples
# It handles both <URIs> and "Literals"
TRIPLE_REGEX = re.compile(r'^<(?P<s1>[^>]+)>\s+<(?P<p1>[^>]+)>\s+(?:<(?P<o_uri>[^>]+)>|"(?P<o_lit>[^"]+)")\s+\.$')

def get_numeric_value(line):
    """Extracts the numeric value if the predicate is a 'data_' type."""
    match = TRIPLE_REGEX.match(line.strip())
    if match:
        pred = match.group('p1')
        # We target predicates containing 'edamontology.org/data_'
        if "edamontology.org/data_" in pred:
            val_str = match.group('o_lit')
            try:
                return float(val_str)
            except (ValueError, TypeError):
                return None
    return None


def compute_value_range(input_path: str) -> tuple[float, float, float]:
    values = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            val = get_numeric_value(line)
            if val is not None:
                values.append(val)

    if not values:
        raise ValueError("No numeric data found for binning.")

    v_min, v_max = min(values), max(values)
    return v_min, v_max, v_max - v_min


def write_binning_metadata(base_path: str, v_min: float, v_max: float, v_range: float, value_count: int) -> None:
    """Write binning parameters and statistics to a JSON metadata file."""
    metadata_path = base_path + '.metadata.json'
    metadata = {
        'data_min': v_min,
        'data_max': v_max,
        'data_range': v_range,
        'binned_values_count': value_count,
        'bin_count': 10,
    }
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)


def bin_line(line: str, v_min: float, v_range: float) -> str:
    val = get_numeric_value(line)
    if val is None:
        return line.strip()

    if v_range == 0:
        bin_idx = 0
    else:
        bin_idx = int(((val - v_min) / v_range) * 10)
        if bin_idx > 9:
            bin_idx = 9

    match = TRIPLE_REGEX.match(line.strip())
    if match is None:
        return line.strip()

    s, p = match.group('s1'), match.group('p1')
    return f'<{s}> <{p}> "bin_{bin_idx}" .'


def iter_binned_lines(input_path: str) -> Iterable[str]:
    v_min, _, v_range = compute_value_range(input_path)

    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            yield bin_line(line, v_min, v_range)


def default_output_base(input_path: str) -> str:
    root, _ = os.path.splitext(input_path)
    return root + '.binned'


def resolve_output_paths(input_path: str, output_path: Optional[str], output_format: str) -> tuple[Optional[str], Optional[str]]:
    if output_format == 'nt':
        return output_path, None

    base_path = output_path if output_path else default_output_base(input_path)
    root, ext = os.path.splitext(base_path)
    if ext.lower() in ('.nt', '.hdt'):
        base_path = root

    nt_output = base_path + '.nt' if output_format == 'both' else None
    hdt_output = base_path + '.hdt'
    return nt_output, hdt_output


def write_nt_file(lines: Iterable[str], output_path: str) -> None:
    with open(output_path, 'w', encoding='utf-8', newline='\n') as handle:
        for line in lines:
            handle.write(line)
            handle.write('\n')


def convert_nt_to_hdt(nt_path: str, hdt_path: str, rdf2hdt_command: str = 'rdf2hdt') -> None:
    executable = shutil.which(rdf2hdt_command) if os.path.basename(rdf2hdt_command) == rdf2hdt_command else rdf2hdt_command
    if not executable or not os.path.exists(executable) and os.path.basename(rdf2hdt_command) != rdf2hdt_command:
        raise FileNotFoundError(
            f"HDT output requires the rdf2hdt executable. Install it and retry, or pass --rdf2hdt-command explicitly. Missing: {rdf2hdt_command}"
        )

    result = subprocess.run(
        [executable, nt_path, hdt_path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"rdf2hdt conversion failed: {detail}")


def _collect_value_stats(input_path: str) -> tuple[float, float, float, int]:
    """Collect binning statistics used for metadata."""
    v_min, v_max, v_range = compute_value_range(input_path)
    values = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            val = get_numeric_value(line)
            if val is not None:
                values.append(val)
    return v_min, v_max, v_range, len(values)


def process_file(input_path: str, output_path: Optional[str] = None, output_format: str = 'nt', rdf2hdt_command: str = 'rdf2hdt'):
    if output_format == 'nt' and not output_path:
        for line in iter_binned_lines(input_path):
            print(line)
        return

    nt_output, hdt_output = resolve_output_paths(input_path, output_path, output_format)

    if output_format == 'nt':
        assert output_path is not None
        write_nt_file(iter_binned_lines(input_path), output_path)
        # Write metadata alongside output
        v_min, v_max, v_range, value_count = _collect_value_stats(input_path)
        write_binning_metadata(output_path, v_min, v_max, v_range, value_count)
        return

    if output_format == 'both':
        assert nt_output is not None and hdt_output is not None
        write_nt_file(iter_binned_lines(input_path), nt_output)
        # Write metadata alongside outputs
        v_min, v_max, v_range, value_count = _collect_value_stats(input_path)
        base_path = nt_output[:-3] if nt_output.endswith('.nt') else nt_output
        write_binning_metadata(base_path, v_min, v_max, v_range, value_count)
        convert_nt_to_hdt(nt_output, hdt_output, rdf2hdt_command=rdf2hdt_command)
        return

    assert hdt_output is not None
    with tempfile.NamedTemporaryFile(mode='w', suffix='.nt', delete=False, encoding='utf-8', newline='\n') as tmp_handle:
        temp_nt_path = tmp_handle.name
        for line in iter_binned_lines(input_path):
            tmp_handle.write(line)
            tmp_handle.write('\n')

    try:
        # Write metadata alongside hdt output
        v_min, v_max, v_range, value_count = _collect_value_stats(input_path)
        base_path = hdt_output[:-4] if hdt_output.endswith('.hdt') else hdt_output
        write_binning_metadata(base_path, v_min, v_max, v_range, value_count)
        convert_nt_to_hdt(temp_nt_path, hdt_output, rdf2hdt_command=rdf2hdt_command)
    finally:
        if os.path.exists(temp_nt_path):
            os.remove(temp_nt_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Bin numeric EDAM data values in an N-Triples file.')
    parser.add_argument('input_path', help='Path to the input .nt file')
    parser.add_argument('-o', '--output', default=None, help='Output path. For hdt/both this is treated as the output base name.')
    parser.add_argument('--output-format', choices=['nt', 'hdt', 'both'], default='nt', help='Output format to generate')
    parser.add_argument('--rdf2hdt-command', default='rdf2hdt', help='Path to the rdf2hdt executable for HDT conversion')
    args = parser.parse_args()

    try:
        process_file(args.input_path, output_path=args.output, output_format=args.output_format, rdf2hdt_command=args.rdf2hdt_command)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
