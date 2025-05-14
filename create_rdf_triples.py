""" script to retrieve gene expression data from each csv dataset and convert to RDF triples, serialising to main_graph.nt"""
import csv
import rdflib
from rdflib import Namespace, URIRef, Literal
import os
from rdflib.namespace import XSD
import requests
import uuid
import json

try:
    with open('filename_uuid_map.json', 'r') as f:
        filename_uuid_map = json.load(f)
except FileNotFoundError:
    filename_uuid_map = {}

# store persistent UUIDs for filenames
filename_uuid_map = {}

def get_or_create_uuid(key):
    """Creates a UUID for each separate dataset
    """
    if key not in filename_uuid_map:
        filename_uuid_map[key] = str(uuid.uuid4())
    return filename_uuid_map[key]

graph = rdflib.Graph()

# Define namespaces and bind to prefixes
BIOLINK = Namespace("https://w3id.org/biolink/vocab/")
ENSEMBL = Namespace("http://identifiers.org/ensembl/")
NCBIGENE = Namespace("http://identifiers.org/ncbigene/")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
SCHEMA = Namespace("https://schema.org/")
EDAM = Namespace("http://edamontology.org/")
DOI = Namespace("https://doi.org/")
DCT = Namespace("http://purl.org/dc/terms/")
PMC = Namespace("https://pubmed.ncbi.nlm.nih.gov/")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
MONARCH = Namespace("https://monarchinitiative.org/")
URN = Namespace("urn:uuid:")

graph.bind("biolink", BIOLINK)
graph.bind("ensembl", ENSEMBL)
graph.bind("ncbigene", NCBIGENE)
graph.bind("rdfs", RDFS)
graph.bind("rdf", RDF)
graph.bind("schema", SCHEMA)
graph.bind("edam", EDAM)
graph.bind("doi", DOI)
graph.bind("dct", DCT)
graph.bind("pmc", PMC)
graph.bind("owl", OWL)
graph.bind("monarch", MONARCH)
graph.bind("urn", URN)


def process_metadata_csv(csv_file_path):
    """Retrieves data from the article metadata file and converts to triples
    """
    with open(csv_file_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            if 'pmid' in row and row['pmid']:
                pmid_uri = PMC[row['pmid']]
                
                for column, value in row.items():
                    if column == 'doi' and value:
                        graph.add((pmid_uri, DCT.identifier, DOI[value]))
                for column, value in row.items():
                    if column == 'title' and value:
                        graph.add((pmid_uri, DCT.title, Literal(value)))
                for column, value in row.items():
                    if column == 'year' and value:
                        graph.add((pmid_uri, DCT.date, Literal(value)))
                for column, value in row.items():
                    if column == 'journal' and value:
                        graph.add((pmid_uri, DCT.publisher, Literal(value)))


def get_gene_id(gene_name) -> None:
    """retrieves relevant HGNC gene if from file gene_ids.txt.
    Currently removes extra transcript info for simplicity - can be added back in in future trials
    """
    # Remove 'hp_' and variant info to help matching process
    if gene_name.startswith('hp_'):
        gene_name = gene_name[3:]
    if '_' in gene_name[-5:]:
        gene_name = gene_name[:gene_name.rfind('_', len(gene_name) - 5)]    
    if '.' in gene_name:
        gene_name = gene_name.split('.')[0]
    genefile = 'gene_ids.txt'
    #print(f"Searching for gene: {gene_name}")
    with open(genefile, 'r') as file:
        next(file)  
        for line in file:
            if gene_name.upper() in line.upper():
                #print(f"{gene_name} HGNC ID found")
                return line.split('\t')[0]
    #print(f"HGNC ID not found for {gene_name}")
    return None
    
    
def process_regular_csv(csv_file_path, matched_genes, unmatched_genes):
    """processes the gene expression csv files (not the metatdata file).
    Searches for relevant information, converts wto triples while adding relevant prefixes.
    """
    filename = os.path.splitext(os.path.basename(csv_file_path))[0]
    pmid = os.path.basename(os.path.dirname(csv_file_path))
    
    dataset_uuid = get_or_create_uuid(filename)
    dataset_uri = URN[dataset_uuid]
    pmid_uri = PMC[pmid]
    
    graph.add((pmid_uri, EDAM.has_output, dataset_uri))
    graph.add((pmid_uri, RDF.type, DCT.identifier))
    
    #lists of data column headers to match, with most preffered match given first.
    possible_gene_names = ['ensembl', 'geneid', 'symbol', 'genesymbol', 'genename', 'entrez', 'ncbi', 'gene', 'tf', 'rna', 'feature']
    possible_log_names = ['log2', 'lf2', 'lfc2', 'logfold2', 'log2fc', 'logfoldchange', 'logfold', 'lf', 'logfc', 'foldchange', 'fc', 'lfc', 'fold', 'expression', 'enrichment', 'estimate']
    possible_pval_names = ['padj', 'adjp', 'pvalueadj', 'adjpvalue', 'pvaladj', 'adjpval', 'pvadj', 'adjpv', 'fdr', 'fdrpval', 'qvalue', 'pvalue', 'qval', 'pval', 'pv', 'qv']
    
    with open(csv_file_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            row_uuid = str(uuid.uuid4())
            row_uri = URN[row_uuid]
            graph.add((dataset_uri, EDAM.has_output, row_uri))
            
            gene_added = log_added = pval_added = False
            
            # Try to find and process gene information, once match made, will add triple and continue
            for column, value in row.items():
                column_lower = column.lower()
                if any(gene_name in column_lower for gene_name in possible_gene_names) and value and not gene_added:
                    monarch_uri = get_gene_id(value)
                    if monarch_uri:
                        full_monarch_uri = MONARCH[monarch_uri]
                        graph.add((row_uri, BIOLINK.Gene, full_monarch_uri))
                        gene_added = True
                        matched_genes += 1
                    else:
                        if 'ensembl' in column_lower:
                            graph.add((row_uri, ENSEMBL.id, Literal(value)))
                        elif 'entrez' in column_lower or 'ncbi' in column_lower:
                            graph.add((row_uri, NCBIGENE.id, Literal(value)))
                        else:
                            graph.add((row_uri, BIOLINK.symbol, Literal(value)))
                        gene_added = True
                        unmatched_genes += 1
                    break
            
            # Then process the rest of the columns
            for column, value in row.items():
                if value: 
                    column_lower = column.lower()
                    
                    # Check for log fold change
                    if any(name in column_lower for name in possible_log_names) and not log_added:
                        graph.add((row_uri, EDAM.data_3754, Literal(value)))
                        log_added = True
                    
                    # Check for p-values
                    elif any(name in column_lower for name in possible_pval_names) and not pval_added:
                        graph.add((row_uri, EDAM.data_1669, Literal(value)))
                        pval_added = True
                    
                    # Add any other columns as generic predicates - removed for now to reduce graph size but can be readded for future use
                    else:
                        continue
#                        predicate = URIRef(f"rdf:predicate/{column}")
#                        graph.add((row_uri, predicate, Literal(value)))
    return matched_genes, unmatched_genes

# Root directory to search for CSV files, and tracker for number of genes HGNC IDs found
root_dir = "C:\\Users\\tamjh\\CodeProjects\\ASDProject\\data"
matched_genes = 0
unmatched_genes = 0 
total_files_processed = 0

for dirpath, dirnames, filenames in os.walk(root_dir):
    for filename in filenames:
        if filename.endswith('.csv'):
            csv_file_path = os.path.join(dirpath, filename)

            if filename == 'asd_article_metadata.csv':
                print(f"Processing file: {csv_file_path}")
                process_metadata_csv(csv_file_path)
            elif filename.startswith('expdata'):
                print(f"Processing file: {csv_file_path}")
                matched_genes, unmatched_genes = process_regular_csv(csv_file_path, matched_genes, unmatched_genes)
            total_files_processed += 1

print("\nProcessing complete. Summary:")
print(f"Total CSV files processed: {total_files_processed}")
print(f"Total matched genes: {matched_genes}")
print(f"Total unmatched genes: {unmatched_genes}")
print(f"Total genes processed: {matched_genes + unmatched_genes}")
graph.serialize(destination='main_graph.nt', format='nt', encoding= "utf-8" )
print("Combined graph has been serialized to main_graph.nt")

#store all the uuid dataset allocated names
with open('filename_uuid_map.json', 'w') as f:
    json.dump(filename_uuid_map, f)

