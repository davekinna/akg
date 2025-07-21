import argparse
from rdflib import Graph, Namespace, URIRef, Literal, query
from akg import AKGException
# from akg import BIOLINK, ENSEMBL, NCBIGENE, RDFS, RDF, SCHEMA, EDAM, DOI, DCT, PMC, OWL, MONARCH, URN

def load_graph(filename: str) -> Graph:
    """
    Load a knowledge graph from an nt format file
    :param filename: Path to the RDF graph file in NT format
    :return: An rdflib Graph object containing the loaded RDF data
    """
    # Create a new RDF graph
    g = Graph()
    with open(filename, "rb") as f:
        g.parse(f, format="nt")
    return g

def main():
    """
    function for extracting info from one of our graph files
    """
    parser = argparse.ArgumentParser(description="Load an RDF graph and perform SPARQL queries.")
    parser.add_argument("filename", type=str, help="Path to the RDF graph file in NT format")
    parser.add_argument("-t", "--triples", action="store_true", help="Count the number of triples in the graph")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed output (all triples in graph)")
    # the summary argument defaults to True
    parser.add_argument("-s", "--summary", action="store_false", help="Suppress summary output")
    parser.add_argument('-n',"--hgnc", action='store_true', help="List all distinct HGNC genes")
    parser.add_argument('-g',"--genes", action='store_true', help="List all distinct genes (any category)")
    parser.add_argument("-c", "--count", action="store_true", help="Output counts only for the gene categories")
    parser.add_argument('-p', "--pmid", action='store_true', help="List all distinct PubMed IDs")
    args = parser.parse_args()

    graph = load_graph(args.filename)

    if args.summary:
        print(f"Graph loaded from {args.filename} with {len(graph)} triples.")
        # calculate the number of distinct subjects, predicates, and objects
        subjects = set()
        predicates = set()
        objects = set() 
        for s, p, o in graph:
            subjects.add(s)
            predicates.add(p)
            objects.add(o)
        print(f"Distinct subjects: {len(subjects)}, predicates: {len(predicates)}, objects: {len(objects)}")

    if args.triples:
        print(f"Number of triples in the graph: {len(graph)}")

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

    if args.pmid:
        print('Listing all distinct PubMed IDs:')
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