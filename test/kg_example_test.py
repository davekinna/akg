from rdflib import Graph, Namespace, URIRef, Literal
def create_graph() -> Graph:
    # Create a new RDF graph
    graph = Graph()
    graph.add((Literal('a'), Literal('pred'), Literal('b')))
    graph.add((Literal('a'), Literal('pred'), Literal('c')))
    graph.add((Literal('b'), Literal('pred'), Literal('d')))

    return graph

def query_graph(graph: Graph, query: str):
    # Execute a SPARQL query on the graph
    results = graph.query(query)
    return results

def main():
    graph = create_graph()
    print(f'Graph created with {len(graph)} triples.')
    print(f'Graph created with {graph} triples.')
    
    print("Graph created with the following triples:")
    for s, p, o in graph:
        print(f"Subject: {s}, Predicate: {p}, Object: {o}")

    print("Now querying the graph with SPARQL...")
    query = """
    SELECT ?s ?p ?o
    WHERE {
        ?s ?p ?o
    }
    """

    results = query_graph(graph, query)
    for row in results:
        print(f"Subject: {row.s}, Predicate: {row.p}, Object: {row.o}")

if __name__ == "__main__":
    main()

def test_graph():
    graph = create_graph()
    assert len(graph) == 3
    assert (Literal('a'), Literal('pred'), Literal('b')) in graph
    assert (Literal('a'), Literal('pred'), Literal('c')) in graph
    assert (Literal('b'), Literal('pred'), Literal('d')) in graph

def test_query():
    graph = create_graph()
    query = """
    SELECT ?s ?p ?o
    WHERE {
        ?s ?p ?o
    }
    """
    results = query_graph(graph, query)
    assert len(results) == 3
    assert all((row.s, row.p, row.o) in results for row in results) 