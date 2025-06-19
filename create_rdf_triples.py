""" script to retrieve gene expression data from each csv dataset and convert to RDF triples, serialising to main_graph.nt"""
import csv
import rdflib
from rdflib import Namespace, URIRef, Literal
import sys
import os
from rdflib.namespace import XSD
import uuid
import json
import pandas as pd
from akg import GeneIdStore, AKGException
import argparse
from tracking import create_tracking, load_tracking, save_tracking, create_empty_tracking_store, add_to_tracking, tracking_entry

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


def create_base_graph():
    graph = rdflib.Graph()


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
    return graph

def process_metadata_csv(csv_file_path, graph):
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

    
def process_regular_csv(csv_file_path, matched_genes, unmatched_genes, graph):
    """processes the gene expression csv files (not the metadata file).
    Searches for relevant information, converts to triples while adding relevant prefixes.
    """
    filename = os.path.splitext(os.path.basename(csv_file_path))[0]
    pmid = os.path.basename(os.path.dirname(csv_file_path))
    
    dataset_uuid = get_or_create_uuid(filename)
    dataset_uri = URN[dataset_uuid]
    pmid_uri = PMC[pmid]
    
    graph.add((pmid_uri, EDAM.has_output, dataset_uri))
    graph.add((pmid_uri, RDF.type, DCT.identifier))
    
    #lists of data column headers to match, with most preferred match given first.
    possible_gene_names = ['ensembl', 'geneid', 'symbol', 'genesymbol', 'genename', 'entrez', 'ncbi', 'gene', 'tf', 'rna', 'feature']
    possible_log_names = ['log2', 'lf2', 'lfc2', 'logfold2', 'log2fc', 'logfoldchange', 'logfold', 'lf', 'logfc', 'foldchange', 'fc', 'lfc', 'fold', 'expression', 'enrichment', 'estimate']
    possible_pval_names = ['padj', 'adjp', 'pvalueadj', 'adjpvalue', 'pvaladj', 'adjpval', 'pvadj', 'adjpv', 'fdr', 'fdrpval', 'qvalue', 'pvalue', 'qval', 'pval', 'pv', 'qv']
    
    # cached gene_id.txt data for faster lookup
    mygids = GeneIdStore()

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
                if value and not gene_added and any(gene_name in column_lower for gene_name in possible_gene_names):
                    monarch_uri = mygids.get_gene_id(value)
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
                    if not log_added and any(name in column_lower for name in possible_log_names):
                        graph.add((row_uri, EDAM.data_3754, Literal(value)))
                        log_added = True
                    
                    # Check for p-values
                    elif not pval_added and any(name in column_lower for name in possible_pval_names):
                        graph.add((row_uri, EDAM.data_1669, Literal(value)))
                        pval_added = True
                    
                    # Add any other columns as generic predicates - removed for now to reduce graph size but can be readded for future use
                    else:
                        continue
#                        predicate = URIRef(f"rdf:predicate/{column}")
#                        graph.add((row_uri, predicate, Literal(value)))
    return matched_genes, unmatched_genes

def test_unicode_bug_1():
    """
    has been crashing after processing the given file
    """
    csv_file_path = "data\\supp_data\\37041460\\expdata_DEGSscommontoallsubtypes.csv"
    matched_genes=0
    unmatched_genes=0
    matched_genes, unmatched_genes = process_regular_csv(csv_file_path, matched_genes, unmatched_genes)
    


if __name__ == '__main__':

    # manage the command line options
    parser = argparse.ArgumentParser(description='Convert downloaded supplementary data to graph precursor')
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-f','--per_file', action='store_true', help="Create one graph per data file (default is one graph)")
    parser.add_argument('-p','--per_pmid', action='store_true', help="Create one graph per PMID (default is one graph). Overridden by per_file)")

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    # note that per_file is taken if oth are set true
    per_file = config['per_file']
    per_pmid = config['per_pmid']

    main_dir = config['input_dir']

    if not os.path.isdir(main_dir):
        raise AKGException(f"create_rdf_triples: data directory {main_dir} must exist")
    
    tracking_file = config['tracking_file']
    tracking_file = os.path.join(main_dir, tracking_file)

    if not os.path.exists(tracking_file):
        raise AKGException(f"create_rdf_triples: {tracking_file} must exist")

    supp_data_folder = os.path.join(main_dir,"supp_data")
    if not os.path.isdir(supp_data_folder):
        raise AKGException(f"create_rdf_triples: supplementary data directory {supp_data_folder} must exist")

    graph_folder = os.path.join(main_dir, "graph")
    os.makedirs(graph_folder, exist_ok=True)

    matched_genes = 0
    unmatched_genes = 0 
    total_files_processed = 0

    article_file_path = os.path.join(main_dir, 'asd_article_metadata.csv')
    if not os.path.isfile(article_file_path):
        print(f"Error: running create_rdf_triples.py but {article_file_path} does not exist: run processing.py first ")

    # earlier versions used this file to manage exclusion, replaced by the tracking file but still currently needed for metadata
    adf = pd.read_csv(article_file_path, encoding='unicode_escape')

    # the exclusion is now in the tracking file
    tdf = load_tracking(tracking_file)
    
    # used by the all-together approach
    global_graph = create_base_graph()

    if per_file:
        print('per file graph output chosen')
    elif per_pmid:
        print('per pmid not yet implemented')
    else:
        global_csv_count = 0
        global_matched_genes = 0
        global_unmatched_genes = 0

        print(f"Processing file: {article_file_path}")
        process_metadata_csv(article_file_path, global_graph)

    for index, row in tdf.iterrows():
        excl = row['excl']
        root = row['path']
        file = row['file']
        file_path = os.path.join(root, file)
        if excl:
            print(f"Excluding file: {file_path} manual: {row['manual']} : {row['manualreason']}")
        else:
            tdf.loc[index,'step'] = 3
            print(f"Processing file: {file_path}")
            if per_file:
                graph = create_base_graph()
                # add the metadata in to every graph, not big.
                print(f"Processing file: {article_file_path}")
                process_metadata_csv(article_file_path, graph)
                mg_before = matched_genes
                ug_before = unmatched_genes
                matched_genes, unmatched_genes = process_regular_csv(file_path, matched_genes, unmatched_genes, graph)
                print(f"Processing file: {file_path} complete")
                graph_file = os.path.join(graph_folder, f'graph_{file}.nt')
                graph.serialize(destination=graph_file, format='nt', encoding= "utf-8" )
                print(f"Combined graph has been serialized to {graph_file}")
                tdf.loc[index,'graphfile'] = graph_file
                tdf.loc[index, 'unmatched'] = (unmatched_genes-ug_before)
                tdf.loc[index, 'matched']   = (matched_genes-mg_before)
                # write out the updated information (should have the new files we just wrote out)
                save_tracking(tdf, tracking_file)

            elif per_pmid:
                print('per pmid not yet implemented')
            else:
                mg_before = matched_genes
                ug_before = unmatched_genes
                matched_genes, unmatched_genes = process_regular_csv(file_path, matched_genes, unmatched_genes, global_graph)
                global_matched_genes += matched_genes - mg_before
                global_unmatched_genes += unmatched_genes - ug_before
    
    # write out the updated information (should have the new files we just wrote out)
    save_tracking(tdf, tracking_file)

    if per_file:
        pass
    elif per_pmid:
        print('per pmid not yet implemented')
    else:
        print(f"Processing file: {file_path} complete")
        global_graph_file = os.path.join(graph_folder, 'main_graph.nt')
        global_graph.serialize(destination=global_graph_file, format='nt', encoding= "utf-8" )
        print(f"Combined graph has been serialized to {global_graph_file}")


# //////////////////////////
#     # only work on the entries that haven't been excluded
#     df = df[~df['exclude']]

#     pmids = df['pmid'].tolist()

#     for pmid in pmids:
#         pmid_csv_count = 0
#         pmid_matched_genes = 0
#         pmid_unmatched_genes = 0
#         pmid_folder = os.path.join(supp_data_folder, str(pmid))
#         print(f"\nProcessing {pmid_folder}:")

#         for dirpath, dirnames, filenames in os.walk(pmid_folder):
#             for filename in filenames:
#                 if filename.endswith('.csv'):
#                     pmid_csv_count += 1
#                     csv_file_path = os.path.join(dirpath, filename)

#                     if filename == 'asd_article_metadata.csv':
#                         print(f"Processing file: {csv_file_path}")
#                         process_metadata_csv(csv_file_path)
#                     elif filename.startswith('expdata'):
#                         print(f"Processing file: {csv_file_path}")
#                         sys.stdout.flush()
#                         mg_before = matched_genes
#                         ug_before = unmatched_genes
#                         matched_genes, unmatched_genes = process_regular_csv(csv_file_path, matched_genes, unmatched_genes)
#                         pmid_matched_genes += matched_genes - mg_before
#                         pmid_unmatched_genes += unmatched_genes - ug_before
#                     total_files_processed += 1
#         print(f"\nProcessing complete for pmid {pmid}. Summary:")
#         print(f"\tTotal CSV files processed: {pmid_csv_count}")
#         print(f"\tTotal matched genes: {pmid_matched_genes}")
#         print(f"\tTotal unmatched genes: {pmid_unmatched_genes}")
#         print(f"\tTotal genes processed: {pmid_matched_genes + pmid_unmatched_genes}")
#         graph.serialize(destination=f'graph.{pmid}.nt', format='nt', encoding= "utf-8" )
#         print(f'\tSerialized to graph.{pmid}.nt')
#         sys.stdout.flush()
#     print("\nProcessing complete. Summary:")
#     print(f"Total CSV files processed: {total_files_processed}")
#     print(f"Total matched genes: {matched_genes}")
#     print(f"Total unmatched genes: {unmatched_genes}")
#     print(f"Total genes processed: {matched_genes + unmatched_genes}")
#     graph.serialize(destination='main_graph.nt', format='nt', encoding= "utf-8" )
#     print("Combined graph has been serialized to main_graph.nt")

    #store all the uuid dataset allocated names
    with open('filename_uuid_map.json', 'w') as f:
        json.dump(filename_uuid_map, f)


