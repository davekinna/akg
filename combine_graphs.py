"""combine_graphs
Combines graphs into a single graph
reads the graphs into rdflib Graph object, adds them together, then serializes them into a single graph
This not strictly necessary: the current .nt triple file format for the graphs can be simply concatenated (using unix 'cat') 
for example. However, a utility for this allows us to use alternative, faster-loading formats, and to log the combinations made

"""
from rdflib import Graph
from akg import load_graph, AKGException, akg_logging_config
import argparse
import json
import logging
import os
import re
import sys


def resolve_pmid_graph_input_dirs(main_dir: str, pmid: str) -> list[str]:
    """Return candidate directories containing per-file graphs for a PMID."""
    return [
        os.path.join(main_dir, "graph", str(pmid)),
        os.path.join(main_dir, "supp_data", str(pmid)),
    ]


def _extract_row_index(label: str) -> str:
    match = re.search(r"row\s+(\d+)", str(label), re.IGNORECASE)
    return match.group(1) if match else str(label)


def build_combined_row_context(files: list[str]) -> dict[str, dict[str, str]]:
    """Merge per-file row label sidecars into a single combined-graph sidecar payload."""
    merged: dict[str, dict[str, str]] = {}

    for nt_file in files:
        sidecar_path = nt_file + ".row_uri_labels.json"
        if not os.path.exists(sidecar_path):
            continue
        try:
            with open(sidecar_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            continue

        if not isinstance(payload, dict):
            continue

        source_filename = os.path.basename(nt_file)
        for urn_key, label in payload.items():
            if not isinstance(urn_key, str):
                continue
            merged[urn_key] = {
                "filename": source_filename,
                "row_label": str(label),
                "row_index": _extract_row_index(str(label)),
            }

    return merged


def write_combined_row_context(output_graph_path: str, files: list[str]) -> None:
    payload = build_combined_row_context(files)
    if not payload:
        return

    sidecar_path = output_graph_path + ".row_uri_labels.json"
    with open(sidecar_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)

def main():
    command_line_str = ' '.join(sys.argv)    
    # manage the command line options
    parser = argparse.ArgumentParser(description='Combine graph files into a single file')
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-l','--log', default='combine_graphs.log', help='Log file name. This file is created in the top-level directory.')
    parser.add_argument('-p','--pmid', default=None, help="Combine the graphs that have been created for the given PMID")
    parser.add_argument('-o','--output_file', default='combined.nt', help='Output file name. This file is created in the graphs directory.')
    parser.add_argument('files',metavar='FILE',nargs='*',  help='Zero or more files to process. Filenames must be *relative to input_dir*')

    # argparse populates an object using parse_args
    args = parser.parse_args()

    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(args)

    # print(config['files'])
    files = config['files']
    output_file = config['output_file']

    pmid = config['pmid']

    main_dir = config['input_dir']

    if not os.path.isdir(main_dir):
        raise AKGException(f"data_convert: data directory '{main_dir}' must exist")

    # this is where all combined graphs go    
    graph_folder = os.path.join(main_dir, "graph")
    os.makedirs(graph_folder, exist_ok=True)

    # set up logging
    akg_logging_config( os.path.join(main_dir, config['log']))
    logging.info(f"Program executed with command: {command_line_str}")

    tracking_file = config['tracking_file']
    tracking_file = os.path.join(main_dir, tracking_file)
    logging.info(f"Tracking file configured but not currently used in combine_graphs")

    # the tracking file must exist because it tells us which files to process
    if not os.path.exists(tracking_file):
        raise AKGException(f"Combining: {tracking_file} must exist")

    if pmid:
        logging.info(f"Combining graphs for PMID: {pmid}")
        files = [] # i.e., pmid takes precedence over whatever was supplied on the command line
        candidate_dirs = resolve_pmid_graph_input_dirs(main_dir, pmid)
        selected_dir = ""
        for candidate_dir in candidate_dirs:
            if not os.path.isdir(candidate_dir):
                continue
            candidate_files = []
            for root, dirs, walk_files in os.walk(candidate_dir):
                for filename in walk_files:
                    if filename.endswith(".nt"):
                        candidate_files.append(os.path.join(root, filename))
            if candidate_files:
                selected_dir = candidate_dir
                files = sorted(candidate_files)
                break

        if not files:
            searched = ", ".join(candidate_dirs)
            raise AKGException(f"No per-file graphs found for PMID {pmid}. Checked: {searched}")

        logging.info(f"Using ALL .nt files in: {selected_dir}")
        for nt_file in files:
            logging.info(f"Found .nt file: {nt_file}")
        output_file = f"combined_{pmid}.nt"
        logging.info(f"-pmid option selected: output file name will be: {output_file}")
    else:
        # prepend the input_dir to each file
        files = [os.path.join(main_dir, f) for f in files if f.endswith('.nt')]
        logging.info(f"Combining the following files: {files}")
        
    combined_graph = Graph()

    if not files:
        logging.error("No files provided to combine. Please provide at least one .nt file.")
        raise AKGException("No files to combine. Please provide at least one .nt file.")
    for nt_file in files:
        logging.info(f"Loading graph from: {nt_file}")
        graph = load_graph(nt_file)
        logging.info(f"Graph loaded with {len(graph)} triples.")
        combined_graph += graph

    # Serialize the combined graph to the output file
    of_path = os.path.join(graph_folder, output_file)
    logging.info(f"Serializing combined graph to: {of_path}")
    if os.path.exists(of_path):
        logging.warning(f"Output file {of_path} already exists. It will be overwritten.")
    combined_graph.serialize(destination=of_path, format='nt', encoding="utf-8")
    write_combined_row_context(of_path, files)
    logging.info(f"{of_path} complete with {len(combined_graph)} triples.")

if __name__ == "__main__":
    main()
