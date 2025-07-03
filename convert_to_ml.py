import os
import rdflib
import networkx as nx
import argparse
from akg import AKGException

def convert_file_to_ml(src_name:str, gml_name:str):
    print(f'Converting {src_name} to {gml_name}')
    g = rdflib.Graph()
    g.parse(src_name, format="nt")
    # note the following only allows a single edge between two nodes
    nx_g = nx.DiGraph()

    # Iterate over the triples in the RDF graph and add them to the networkx graph
    # The subject and object are nodes, the predicate is an edge attribute
    # Note that the subject and object are converted to strings, which is necessary for networkx
    # to handle them as nodes. This means that if the same node appears with different URIs,
    # they will be treated as different nodes.
    print(f'Number of triples in {src_name}: {len(g)}')
    for s, p, o in g:
        s_str = str(s)
        o_str = str(o)
        # add nodes. Duplicates will not be added if exactly the same, the storage is in a dict.
        nx_g.add_node(s_str)
        nx_g.add_node(o_str)
        # add edge with the predicate as an edge attribute
        nx_g.add_edge(s_str, o_str, predicate=str(p))

    # Set node attributes
    for edge in nx_g.edges():
        print(edge[0], edge[1])

    # Write GraphML
    nx.write_graphml(nx_g, gml_name)


def convert_to_ml(folder:str):
    """
    Read in all .nt files in the given folder. These hold the RDF triples for the akg.
    One by one, convert to a networkx directed graph (duplicate nodes not allowed)
    Write each out to a .graphml file. This is a format that can be read by cytoscape and Gephi.
    Note that the conversion of a relatively small 37369-triple file (34535545.nt) took several minutes, 
    and then several more minutes to load into cytoscape.
    """
    print(f'Converting all .nt files in {folder} to .ml')
    for dirpath, dirnames, filenames in os.walk(folder):
        for filename in filenames:
            if filename.endswith('.nt'):
                src_name = os.path.join(dirpath,filename)
                stub = src_name.rsplit( ".", 1 )[ 0 ]
                gml_name = f'{stub}.graphml'
                if os.path.exists(gml_name):
                    print(f'{gml_name} already exists, skipping')
                else:
                    convert_file_to_ml(src_name, gml_name)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert knowledge graph .nt files to graphml format for use in cytoscape or gephi.')

    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for data files.(input and output)')
    parser.add_argument('-g','--graph_dir', default='graph', help='Subdirectory for graph files')
    parser.add_argument('-n','--input', default='cleaned_main_graph.nt', help='Input file')
    parser.add_argument('-u','--output', default='cleaned_main_graph.nt.ml', help='Output file')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file resides in the top-level directory.')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    main_dir = config['input_dir']
    if not os.path.isdir(main_dir):
        raise AKGException(f"data_convert: data directory {main_dir} must exist")

    input_file = config['input']
    output_file = config['output']
    graph_dir = config['graph_dir']

    tracking_file = config['tracking_file']
    print(f'Processing directory {os.path.realpath(main_dir)}: using tracking file {tracking_file} here')
    tracking_file = os.path.join(main_dir, tracking_file)

    full_graph_path = os.path.join(main_dir,graph_dir,input_file)
    full_graph_output = os.path.join(main_dir,graph_dir,output_file)

    convert_file_to_ml(full_graph_path, full_graph_output)
