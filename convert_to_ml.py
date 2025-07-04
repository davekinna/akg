import json
import os
import rdflib
import networkx as nx
import argparse
from akg import AKGException, FilenameUUIDMap
from rdflib import URIRef, Namespace, Literal
from akg import BIOLINK, ENSEMBL, NCBIGENE, RDFS, RDF, SCHEMA, EDAM, DOI, DCT, PMC, OWL, MONARCH, URN

pmc_namespace_str = str(PMC) # "http://purl.org/pmc/id/"
edam_namespace_str = str(EDAM) # "http://edamontology.org/"
eho_str = str(EDAM['has_output']) # "http://edamontology.org/has_output"
# p == BIOLINK.Gene or p == ENSEMBL.id or p == NCBIGENE.id or p == BIOLINK.symbol:
blg_str = str(BIOLINK.Gene) # "https://w3id.org/biolink/vocab/Gene"
bls_str = str(BIOLINK.symbol) # "https://w3id.org/biolink/vocab/symbol"
ens_str = str(ENSEMBL.id) # "http://identifiers.org/ensembl/"
ncbi_str = str(NCBIGENE.id) # "http://identifiers.org/ncbigene/"
edam_3754_str = str(EDAM['data_3754']) # "http://edamontology.org/data_3754" - used to link a row to a p-Value
edam_1669_str = str(EDAM['data_1669']) # "http://edamontology.org/data_1669" - used to link a row to a log fold change

def convert_file_to_ml(src_name:str, gml_name:str, filename_uuid_map:FilenameUUIDMap=None):
    print(f'Converting {src_name} to {gml_name}')

    """    Convert a single .nt file to a .graphml file using networkx.
    
    :param src_name: The source .nt file to convert. Full path relative to the current working directory.
    :param gml_name: The destination .graphml file to create.

    :return: None
    :rtype: None
    :raises AKGException: If the source file does not exist or is not a valid RDF file.
    :description: Reads an RDF graph from a .nt file and converts it to a .graphml file using networkx.
    Uses <src_name>.row_uri_labels.json, if available, to label the rows in the graph
    The .graphml file can be used in visualization tools like Cytoscape or Gephi.
    """
    if not os.path.exists(src_name):
        raise AKGException(f"convert_to_ml: source file {src_name} does not exist")
    if not src_name.endswith('.nt'):
        raise AKGException(f"convert_to_ml: source file {src_name} must be a .nt file")
    try:
        rulfile = src_name + '.row_uri_labels.json'
        if os.path.exists(rulfile):
            print(f'Loading row_uri_labels from {rulfile}')
        with open(rulfile, 'r') as f:
            row_uri_labels = json.load(f)
            print(f'Loaded {len(row_uri_labels)} row labels from {rulfile}')
    except FileNotFoundError:
        row_uri_labels = {}


    g = rdflib.Graph()
    g.parse(src_name, format="nt")
    # note the following only allows a single edge between two nodes
    nx_g = nx.DiGraph()

    # Iterate over the triples in the RDF graph and add them to the networkx graph
    # The subject and object are nodes, the predicate is an edge attribute
    # Note that the subject and object are converted to strings, which is necessary for networkx
    # to handle them as nodes. This means that if the same node appears with different URIs,
    # they will be treated as different nodes.
    # create the graph first and post-process for labelling, may need to optimiize later
    print(f'Number of triples in {src_name}: {len(g)}')
    for s, p, o in g:
        s_str = str(s)
        p_str = str(p)
        o_str = str(o)
        # add nodes. Duplicates will not be added if exactly the same, the storage is in a dict.
        nx_g.add_node(s_str)
#        print(p_str)
        nx_g.add_node(o_str)
        # add edge with the predicate as an edge attribute
        nx_g.add_edge(s_str, o_str, predicate=p_str)

    # now add label texts to the graph, for use by Gephi or Cytoscape later
    for edge in nx_g.edges():
        s = nx_g.nodes[edge[0]] # Get the node references for the subject & object
        o = nx_g.nodes[edge[1]]
        s_str = str(edge[0]) # string representations used in all clauses below
        o_str = str(edge[1])
        # handle PMIDs and edges from them to datasets
        if edge[0].startswith(pmc_namespace_str): # the subject is a PubMed ID node
            # the subject is a PubMed ID, so we extract the PMID from the URI           
            s['PMID'] = s_str.split('/')[-1]  # Add the PMID as a node attribute
            if nx_g[s_str][o_str]['predicate'] == eho_str:  # the edge links a PMID to an output dataset
                # extract the dataset ID from the URI
                odid = o_str.split('/')[-1]
                odid = odid.split(':')[-1] # remove the uid:uuid: prefix
                uuid_filename = filename_uuid_map.get_filename_from_uuid(odid)
                s['dataset'] = uuid_filename  
        else:
            # the subject is not a PubMed ID, so for 'have_output' edges, the object is a row - so add the row label
            # (could also just add a row label for all nodes, but this is more efficient)
            p = nx_g[s_str][o_str]['predicate']  # get the predicate for the edge
            if p == eho_str:
                # the edge is a 'has_output' edge, add the row label to the object node
                if o_str in row_uri_labels:
                    o['row'] = row_uri_labels[o_str]
                else:
                    o['row'] = o_str
            elif p == blg_str or p == ens_str or p == ncbi_str or p == bls_str:
                o['gene'] = o_str.split('/')[-1]  # Add the gene ID as a node attribute, but remove the URI prefix
            elif p == edam_3754_str:
                    o['p-Value'] = o_str
            elif p == edam_1669_str:
                o['log fold change'] = o_str
            else:
                print(f'Unknown predicate {p} for edge {s_str} -> {o_str}, skipping label')

    # Write GraphML
    nx.write_graphml(nx_g, gml_name)


def convert_to_ml(folder:str, filename_uuid_map:FilenameUUIDMap=None):
    """
    Currently, this function is not used, but it is useful for converting all .nt files in a folder to .graphml files.
    
    :param folder: The folder containing the .nt files to convert.
    :return: None
    :rtype: None
    :raises AKGException: If the folder does not exist or is not a directory.
    :description:
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
                    convert_file_to_ml(src_name, gml_name, filename_uuid_map)

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

    filename_uuid_map = FilenameUUIDMap(os.path.join(main_dir, graph_dir, 'filename_uuid_map.json'))

    tracking_file = config['tracking_file']
    print(f'Processing directory {os.path.realpath(main_dir)}: using tracking file {tracking_file} here')
    tracking_file = os.path.join(main_dir, tracking_file)

    full_graph_path = os.path.join(main_dir,graph_dir,input_file)
    full_graph_output = os.path.join(main_dir,graph_dir,output_file)

    convert_file_to_ml(full_graph_path, full_graph_output, filename_uuid_map)
