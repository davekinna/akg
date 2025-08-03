import json
import os
import argparse
from rdflib import Graph, Namespace, URIRef, Literal, query
from akg import AKGException, FilenameUUIDMap, load_graph
# from akg import BIOLINK, ENSEMBL, NCBIGENE, RDFS, RDF, SCHEMA, EDAM, DOI, DCT, PMC, OWL, MONARCH, URN


def main():
    """
    function for extracting info from one of our graph files
    """
    parser = argparse.ArgumentParser(description="Load an RDF graph and extract information.")
    parser.add_argument("filename", type=str, help="Path to the RDF graph file in NT format")
    parser.add_argument("-t", "--triples", action="store_true", help="Count the number of triples in the graph")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed output (all triples in graph)")
    # the summary argument defaults to True
    parser.add_argument("-s", "--summary", action="store_false", help="Suppress summary output")
    parser.add_argument('-n',"--hgnc", action='store_true', help="List all distinct HGNC genes")
    parser.add_argument('-g',"--genes", action='store_true', help="List all distinct genes (any category)")
    parser.add_argument("-c", "--count", action="store_true", help="Output counts only for the gene categories")
    parser.add_argument('-p', "--pmid", action='store_true', help="List all distinct PubMed IDs")
    parser.add_argument('-d', "--datasets", action='store_true', help="List all distinct datasets and row counts")
    args = parser.parse_args()

    if not os.path.exists(args.filename):
        raise AKGException(f"File {args.filename} does not exist.")
    else:
        # check whether filename_uuid_map.json exists in the same directory
        filename_uuid_map_path = os.path.join(os.path.dirname(args.filename), "filename_uuid_map.json")
        if not os.path.exists(filename_uuid_map_path):
            print(f"Warning: {filename_uuid_map_path} does not exist in the same directory. UUIDs to filename check will not be available.")
        else:
            filename_uuid_map = FilenameUUIDMap(filename=filename_uuid_map_path)
    
    graph = load_graph(args.filename)

    if args.summary:
        print(f"Graph loaded from: {args.filename}")
        print(f"Triples: {len(graph)}")
        # calculate the number of distinct subjects, predicates, and objects
        subjects = set()
        predicates = set()
        objects = set() 
        for s, p, o in graph:
            subjects.add(s)
            predicates.add(p)
            objects.add(o)
        print(f"Subjects: {len(subjects)}")
        print(f"Predicates: {len(predicates)}")
        print(f"Objects: {len(objects)}")

    if args.pmid:
        # Listing all distinct PubMed IDs
        # note the edam url is not https.
        pmid_query = """
        PREFIX EDAM: <http://edamontology.org/>
        PREFIX PMC: <https://pubmed.ncbi.nlm.nih.gov/>
        SELECT DISTINCT ?pmid
        WHERE {
            ?subject EDAM:has_output ?object
            FILTER(STRSTARTS(STR(?subject), "https://pubmed.ncbi.nlm.nih.gov/"))
            BIND(REPLACE(STR(?subject), "https://pubmed.ncbi.nlm.nih.gov/", "") AS ?pmid)
        }
    """

        # Execute the SPARQL query to find distinct PubMed IDs
        results = graph.query(pmid_query)
        for row in results:
            print(f"PubMed ID: {row.pmid}")

    if args.triples:
        print(f"Triples: {len(graph)}")

    if args.hgnc:
        gene_query = """
        PREFIX BIOLINK: <https://w3id.org/biolink/vocab/>
        SELECT DISTINCT ?object
        WHERE {
            ?s BIOLINK:Gene ?object
        }
        order by ?object
        """

        # Execute the SPARQL query to find distinct genes
        results = graph.query(gene_query)
        print(f'HGNC count: {len(results)} ')
        if not args.count:
            for row in results:
                print(f"HGNC: {row.object}")

    if args.genes:
        gene_query = """
        PREFIX BIOLINK: <https://w3id.org/biolink/vocab/>
        SELECT DISTINCT ?object
        WHERE {
            ?s BIOLINK:Gene ?object
        }
        order by ?object
        """

        # Execute the SPARQL query to find distinct HGNC
        resultsHGNC = graph.query(gene_query)
        print(f'HGNC count: {len(resultsHGNC)} ')
        if not args.count:
            for row in resultsHGNC:
                print(f"HGNC: {row.object}")

        gene_query = """
        PREFIX ENSEMBL: <http://identifiers.org/ensembl/>
        SELECT DISTINCT ?object
        WHERE {
            ?s ENSEMBL:id ?object
        }
        order by ?object
        """
        resultsENS = graph.query(gene_query)
        print(f'Ensembl count: {len(resultsENS)} ')
        if not args.count:
            for row in resultsENS:
                print(f"Ensembl: {row.object}")

        gene_query = """
        PREFIX NCBIGENE: <http://identifiers.org/ncbigene/>
        SELECT DISTINCT ?object
        WHERE {
            ?s NCBIGENE:id ?object
        }
        order by ?object
        """
        resultsNCBI = graph.query(gene_query)
        print(f'NCBI count: {len(resultsNCBI)} ')
        if not args.count:
            for row in resultsNCBI:
                print(f"NCBI: {row.object}")

        gene_query = """
        PREFIX BIOLINK: <https://w3id.org/biolink/vocab/>
        SELECT DISTINCT ?object
        WHERE {
            ?s BIOLINK:symbol ?object
        }
        order by ?object
        """
        resultsSYM = graph.query(gene_query)
        print(f'Symbol only gene count: {len(resultsSYM)} ')
        if not args.count:
            for row in resultsSYM:
                print(f"Symbol: {row.object}")

        print(f"Total distinct genes: {len(resultsHGNC) + len(resultsENS) + len(resultsNCBI) + len(resultsSYM)}")


    if args.datasets:
        # Listing all distinct datasets
        dataset_query = """
        PREFIX EDAM: <http://edamontology.org/>
        SELECT DISTINCT ?dataset
        WHERE {
            ?subject EDAM:has_output ?dataset .
            FILTER(STRSTARTS(STR(?subject), "https://pubmed.ncbi.nlm.nih.gov/"))
        }
        GROUP BY ?dataset
        ORDER BY ?dataset
        """

        # Execute the SPARQL query to find distinct datasets and their row counts
        results = graph.query(dataset_query)
        dataset_uuid = ""
        dataset_uuid_trim = ""
        for row in results:
            # the uuids are prefaced with urn:uuid:,. remove this prefix
            dataset_uuid = str(row.dataset)
            dataset_uuid_trim = dataset_uuid.replace("urn:uuid:", "")
            fromuuid = filename_uuid_map.get_filename_from_uuid(dataset_uuid_trim)
            if fromuuid is None:
                print(f"Dataset: {row.dataset}, no corresponding file found in filename_uuid_map.json")
            else:
                print(f"Dataset: {row.dataset}, filename from uuid: {fromuuid}")

            # Listing all distinct rows for this dataset
            # note the edam url is not https. The rows are the objects for which the subject is NOT a PMID
            row_query = f"""
            PREFIX EDAM: <http://edamontology.org/>
            PREFIX PMC: <https://pubmed.ncbi.nlm.nih.gov/>
            PREFIX URN: <urn:uuid:>
            SELECT DISTINCT ?data_row
            WHERE {{
                URN:{dataset_uuid_trim} EDAM:has_output ?object
                BIND(?object AS ?data_row)
            }}
            """

            # Execute the SPARQL query to find distinct rows
            row_results = graph.query(row_query)
            if len(row_results) == 0:
                print("No distinct rows found.")
            else:
                print(f"Distinct rows found: {len(row_results)}")
                if not args.count:
                    # we found some, it's worth loading the row labels
                    try:
                        rulfile = args.filename + '.row_uri_labels.json'
                        if os.path.exists(rulfile):
                            print(f'Loading row_uri_labels from {rulfile}')
                            with open(rulfile, 'r') as f:
                                row_uri_labels = json.load(f)
                                print(f'Loaded {len(row_uri_labels)} row labels from {rulfile}')
                        else:
                            print(f'File {rulfile} does not exist in the same directory. Row labels not available.')
                            row_uri_labels = {}
                    except FileNotFoundError:
                        row_uri_labels = {}

                    for row in row_results:
                        # the uuids are prefaced with urn:uuid:,. remove this prefix
                        if str(row.data_row) in row_uri_labels:
                            data_row_uuid = row_uri_labels[str(row.data_row)]
                        else:
                            data_row_uuid = "none found"
                        print(f"Data row: {row.data_row}, label: {data_row_uuid}")

    if args.verbose:
        query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o
        }
        """
        results = graph.query(query)
        for row in results:
            print(f"Subject: {row.s}, Predicate: {row.p}, Object: {row.o}")

if __name__ == "__main__":
    main()