
import re
import argparse
import os
import logging
import sys
from akg import AKGException,akg_logging_config

def process_nt_file(input_file:str, output_file:str):
    """Add extra data cleaning to the file graph file - ensures any values are given correct datatype (double or data), 
    and that any blank values are removed.

    """
    decimal_pattern = re.compile(r'"(-?\d+(\.\d+)?([eE][-+]?\d+)?)"')
    empty_literal_pattern = re.compile(r'\s+"(\s*|-)"(\^\^<[^>]+>)?\s*\.$')
    date_pattern = re.compile(r'<http://purl.org/dc/terms/date>\s+"(\d+)"\s+\.$')

    with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
        for line in infile:
            if line.strip() == '' or empty_literal_pattern.search(line):
                continue

            #find any date predicate, label datatype of the object as a date
            if 'http://purl.org/dc/terms/date' in line:
                modified_line = date_pattern.sub(r'<http://purl.org/dc/terms/date> "\1"^^<http://www.w3.org/2001/XMLSchema#gYear> .', line)
                outfile.write(modified_line)
            else:
                #find any decimal value, label datatype of the object as a double
                match = decimal_pattern.search(line)
                if match:
                    modified_line = decimal_pattern.sub(r'"\1"^^<http://www.w3.org/2001/XMLSchema#double>', line)
                    outfile.write(modified_line)
                else:
                    outfile.write(line)


if __name__ == '__main__':
    """
    Main entry point for graph_cleanup.
    No tracking file, this is to clean up existing graphs, this should really be implemented at the time of graph creation.
    The standard logging is not used here.
    TODO: #31 change create_rdf_triples to implement the formatting given in graph_cleanup.py

    """

    command_line_str = ' '.join(sys.argv)
    parser = argparse.ArgumentParser(description='Cleanup knowledge graph .nt files and apply conventions')

    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for data files.(input and output)')
    parser.add_argument('-g','--graph_dir', default='graph', help='Subdirectory for graph files')
    parser.add_argument('-n','--input', default='main_graph.nt', help='Input file')
    parser.add_argument('-u','--output', default='cleaned_main_graph.nt', help='Output file')
    parser.add_argument('-l','--log', default='graph_cleanup.log', help='Log file name. This file is created in the top-level directory.')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    main_dir = config['input_dir']
    if not os.path.isdir(main_dir):
        raise AKGException(f"data_convert: data directory {main_dir} must exist")
    # set up logging
    akg_logging_config( os.path.join(main_dir, config['log']))
    logging.info(f"Program executed with command: {command_line_str}")

    input_file = config['input']
    output_file = config['output']
    graph_dir = config['graph_dir']

    full_graph_path = os.path.join(main_dir,graph_dir,input_file)
    full_graph_output = os.path.join(main_dir,graph_dir,output_file)

    process_nt_file(full_graph_path, full_graph_output)
    logging.info(f"Graph file {full_graph_path} cleaned and written to {full_graph_output}")