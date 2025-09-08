#
# query_graph.py
# Query a graph file using a SPARQL query
# For usage, type "python query_graph.py --help
# an example is
# python query_graph.py -i data -q query.sparql -o query_results.csv graph_file.nt
# where graph_file.nt is a file in the data/graph subdirectory
# query.sparql is a SPARQL query file in the data directory
# query_results.csv is the output file in the data directory
# 
# if no query file is specified, the program enters interactive mode
# The user can then type in two filenames: a query file and an output file
# If both filenames are provided, the query is executed and results saved
# If either filename is missing, we loop back to the prompt
#
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
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files. Graphs in subdirectory graph')
    parser.add_argument('-l','--log', default='query_graph.log', help='Log file name. This file is created in the top-level directory')
    parser.add_argument('-q','--query_file',  help='SPARQL query file name. Relative to the input_dir.')
    parser.add_argument('-o','--output_file', help='Output file name. Relative to the input_dir.')
    # positional argument defining the graph file to be queried
    parser.add_argument('graph_file', metavar='GRAPH_FILE', help='Graph file to be queried. Relative to the input_dir/graph subdirectory')
    # argparse populates an object using parse_args
    args = parser.parse_args()
    # set up the logging
    config = vars(args)
    main_dir = config['input_dir']

    if not os.path.isdir(main_dir):
        raise AKGException(f"query_graph: data directory '{main_dir}' must exist")

    akg_logging_config( os.path.join(main_dir, config['log']))
    logging.info(f"Program executed with command: {command_line_str}")

    graph_folder = os.path.join(main_dir, "graph")
    graph_file = os.path.join(graph_folder, config['graph_file'])
    if not os.path.exists(graph_file):
        raise AKGException(f"query_graph: graph file '{graph_file}' must exist")

    # defaults if no query file or output file is given
    cl_query = False
    query_file = None
    if config['query_file']:
        query_file = os.path.join(main_dir, config['query_file']) 
        cl_query = os.path.exists(query_file)
        if not cl_query:
            raise AKGException(f"query_graph: query file '{query_file}' must exist")
     
    if cl_query and config['output_file']:
        logging.info(f"Using query file from command line: {query_file}")   
        output_file = os.path.join(main_dir, config['output_file'])
    else:
        logging.info(f"No query file specified on command line, entering interactive mode")
        query_file = None
        output_file = None

    logging.info(f"Loading graph from file: {graph_file}")
    g = load_graph(graph_file)
    logging.info(f"Graph loaded successfully, {len(g)} triples")

    if cl_query and config['output_file']:
        with open(query_file,'r', encoding='utf-8') as f:
            query_str = f.read()
        logging.info(f"Read query from {query_file}")

        logging.info(f"Executing query, output file: {output_file}")
        results = g.query(query_str)
        logging.info(f"Query executed successfully, saving results to {output_file}")
        results.serialize(destination=output_file, format='csv')
        logging.info(f"Wrote {len(results)} results to {output_file}")
    else:
        # entering interactive mode, a loop for which the user 
        # types in two filenames: a query file and an output file
        # if both filenames are provided, the query is executed and results saved
        # if either filename is missing, we loop back to the prompt
        print("Entering interactive mode. Type 'exit', 'quit' or 'q' to exit.")
        while True:
            try:
                print(">> ", end="")
                sys.stdout.flush()
                line = sys.stdin.readline().strip()
                if line.lower() in ('exit','quit','q'):
                    print("Exiting interactive mode.")
                    break
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 2:
                    print("Please provide two filenames: <query_file> <output_file>")
                    continue
                query_file, output_file = parts
                query_file = os.path.join(main_dir, query_file)
                output_file = os.path.join(main_dir, output_file) 
                if not os.path.exists(query_file):
                    print(f"Query file '{query_file}' does not exist.")
                    continue
                with open(query_file,'r', encoding='utf-8') as f:
                    query_str = f.read()
                print(f"Executing query from {query_file}, output file: {output_file}")
                logging.info(f"Executing query from {query_file}, output file: {output_file}")

                # the query happens here
                results = g.query(query_str)

                logging.info(f"Query executed successfully, saving results to {output_file}")
                results.serialize(destination=output_file, format='csv')

                print(f"Wrote {len(results)} results to {output_file}")
                logging.info(f"Wrote {len(results)} results to {output_file}")
            except KeyboardInterrupt:
                print("\nExiting interactive mode.")
                logging.info(f"Exiting interactive mode.")
                # actually put in an exit() here, it was hanging.
                sys.exit(0)
            except Exception as e:
                logging.error(f"Error executing query: {e}")
    return 

if __name__ == "__main__":

    main()