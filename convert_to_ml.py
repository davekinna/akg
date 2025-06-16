import os
import rdflib
import networkx as nx

def convert_file_to_ml(src_name:str, gml_name:str):
    print(f'Converting {src_name}')
    g = rdflib.Graph()
    g.parse(src_name, format="nt")
    # note the following only allows a single edge between two nodes
    nx_g = nx.DiGraph()

    for s, p, o in g:
        s_str = str(s)
        o_str = str(o)
        # add nodes. Duplicates will not be added if exactly the same, the storage is in a dict.
        nx_g.add_node(s_str)
        nx_g.add_node(o_str)
        # add edge with the predicate as an edge attribute
        nx_g.add_edge(s_str, o_str, predicate=str(p))

    # 3) Write GraphML
    nx.write_graphml(nx_g, gml_name)


def convert_to_ml(folder:str):
    """
    Read in all .nt files in the given folder. These hold the RDF triples for the akg.
    One by one, convert to a networkx directed graph (duplicate nodes not allowed)
    Write each out to a .graphml file. This is a format that can be read by cytoscape.
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
    convert_file_to_ml('d2025-06-10\\graph\\graph_expdata_TableS2A.csv.nt','clean_graph_expdata_TableS2A.csv.graphml' )
