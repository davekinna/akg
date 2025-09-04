"""combine_graphs
Combines graphs into a single graph
reads the graphs into rdflib Graph object, adds them together, then serializes them into a single graph
This not strictly necessary: the current .nt triple file format for the graphs can be simply concatenated (using unix 'cat') 
for example. However, a utility for this allows us to use alternative, faster-loading formats, and to log the combinations made

"""
from rdflib import Graph
from akg import load_graph, AKGException, akg_logging_config
import argparse
import logging
import os
import sys

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
        # if a pmid is given, we look for all the files in the supp_data folder for that pmid
        supp_data_folder = os.path.join(main_dir, "supp_data")
        if not os.path.isdir(supp_data_folder):
            raise AKGException(f"create_rdf_triples: supplementary data directory {supp_data_folder} must exist")
        files = [] # i.e., pmid takes precedence over whatever was supplied on the command line
        pmid_folder = os.path.join(supp_data_folder, pmid)
        # loop over all *.nt files in pmid_folder
        logging.info(f"Using ALL .nt files in: {pmid_folder}")
        for root, dirs, walk_files in os.walk(pmid_folder):
            for filename in walk_files:
                if filename.endswith(".nt"):
                    nt_file = os.path.join(root, filename)
                    logging.info(f"Found .nt file: {nt_file}")
                    files.append(nt_file)
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
    logging.info(f"{of_path} complete with {len(combined_graph)} triples.")

if __name__ == "__main__":
    main()
