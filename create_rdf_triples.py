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
from akg import GeneIdStore, AKGException, FilenameUUIDMap, akg_logging_config, possible_lfc_names, possible_gene_names, possible_pval_names, find_first_match
import argparse
from tracking import check_tracking_writeable, create_tracking, load_tracking, save_tracking, create_empty_tracking_store, add_to_tracking, tracking_entry
import logging
from akg import BIOLINK, ENSEMBL, NCBIGENE, RDFS, RDF, SCHEMA, EDAM, DOI, DCT, PMC, OWL, MONARCH, URN

# Create a global instance of FilenameUUIDMap to manage UUIDs for filenames
# actually set this up in the main function, so that it can be configured from the command line
g_filename_uuid_map = None

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


def process_regular_csv(csv_file_path:str, matched_genes, unmatched_genes, graph, graph_file:str, gene_name:str='', pval_name:str='', lfc_name:str='')-> (int,int):
    """processes the gene expression csv files (not the metadata file).
    Searches for relevant information, converts to triples while adding relevant prefixes.
    Parameters:
    - csv_file_path: Path to the CSV file to process
    - matched_genes: count of genes that have been matched so far
    - unmatched_genes: count of genes that have not been matched so far
    - graph: RDF graph to add triples to
    - graph_file: Path to the graph file
    - gene_name: Name of the gene column
    - pval_name: Name of the p-value column
    - lfc_name: Name of the log fold change column
    Returns:
    - A tuple containing the updated counts of matched and unmatched genes
    """
    filename = os.path.splitext(os.path.basename(csv_file_path))[0]
    pmid = os.path.basename(os.path.dirname(csv_file_path))

    dataset_uuid = g_filename_uuid_map.get_uuid(filename)
    dataset_uri = URN[dataset_uuid]
    pmid_uri = PMC[pmid]
    
    graph.add((pmid_uri, EDAM.has_output, dataset_uri))
    #todo: #29 understand why this is needed, but it is in the original code
    graph.add((pmid_uri, RDF.type, DCT.identifier))
    
    # cached gene_id.txt data for faster lookup
    mygids = GeneIdStore()

    # record the row uris/uuids that have been identified for this file, with their numeric index, so that we can identify them in metadata
    row_uri_labels = {}
    filename_row_uri_labels = f"{filename}_row_uri_labels.json"

    total_rows = sum(1 for _ in open(csv_file_path, 'r'))
    logging.info(f"Processing {total_rows} rows in {csv_file_path}")
    report_interval = max(1, total_rows // 10)  # Report every 10% of the rows
    # switching to raw file reading, DictReader and pandas didn't handle all files correctly
    # Open the file with 'utf-8-sig' encoding to handle potential BOM characters
    with open(csv_file_path, mode='r', newline='', encoding='utf-8-sig') as csvfile:
        # Read the raw header line
        header_line = csvfile.readline()
        if not header_line:
            raise ValueError("File appears to be empty.")
        # data_convert writes out with lines quoted
        header_line = header_line.strip().strip('"')

        # Manually split the header by commas
        # .strip() removes whitespace/newlines from the ends
        header_fields = [h.strip().lower() for h in header_line.strip().split(',')]

        logging.info(f"Header processed. Found {len(header_fields)} columns.")

        lfc_found = False
        gene_found = False
        pval_found = False

        gene_index = lfc_index = pval_index = 0
        # Find the index of the 'gene' column
        if not gene_name:
            gene_name = find_first_match(possible_gene_names, header_fields)
            if not gene_name:
                logging.warning(f"No gene column found in {csv_file_path}. Checked for: {possible_gene_names}")
        if gene_name:
            try:
                gene_index = header_fields.index(gene_name)
                logging.info(f"{gene_name} column successfully found at index: {gene_index}")
                gene_found = True
            except ValueError:
                logging.error(f"{gene_name} was not found in the header.")
                logging.info(f"found these headers: {header_fields}")

        # Find the index of the 'pval' column
        # spell these out one by one for debugging, should be shrunk into a single shared code block later
        if not pval_name:
            pval_name = find_first_match(possible_pval_names, header_fields)
            if not pval_name:
                logging.warning(f"No pval column found in {csv_file_path}. Checked for: {possible_pval_names}")
        if pval_name:
            try:
                pval_index = header_fields.index(pval_name)
                logging.info(f"{pval_name} column successfully found at index: {pval_index}")
                pval_found = True
            except ValueError:
                logging.error(f"{pval_name} was not found in the header.")
                logging.info(f"found these headers: {header_fields}")

        # Find the index of the 'lfc' column
        if not lfc_name:
            lfc_name = find_first_match(possible_lfc_names, header_fields)
            if not lfc_name:
                logging.warning(f"No lfc column found in {csv_file_path}. Checked for: {possible_lfc_names}")
        if lfc_name:
            try:
                lfc_index = header_fields.index(lfc_name)
                logging.info(f"{lfc_name} column successfully found at index: {lfc_index}")
                lfc_found = True
            except ValueError:
                logging.error(f"{lfc_name} was not found in the header.")
                logging.info(f"found these headers: {header_fields}")

        if not gene_found and not pval_found and not lfc_found:
            logging.warning(f"No relevant columns found in {csv_file_path}.")
            return matched_genes, unmatched_genes

        # Loop through the rest of the file to process data rows
        rowIndex = 0
        for i, line in enumerate(csvfile):
            data_fields = line.strip().strip('"').split(',')
            
            # Ensure the row has enough columns before we try to access our index
            n_fields = len(data_fields)
            m_index = max(gene_index, pval_index, lfc_index)
            if n_fields > m_index:
                if gene_name:
                    gene_symbol = data_fields[gene_index]
                if pval_name:
                    pval_symbol = data_fields[pval_index]
                if lfc_name:
                    lfc_symbol = data_fields[lfc_index]
            else:
                logging.warning(f"Skipping malformed row #{i + 2} (has {n_fields} columns) which is less than {m_index + 1}")
                continue

            if rowIndex % report_interval == 0:
                logging.info(f"Processing row {rowIndex} of {total_rows}")
            row_uuid = str(uuid.uuid4())
            row_uri = URN[row_uuid]
            graph.add((dataset_uri, EDAM.has_output, row_uri))
            # retain the row number: because this is to be used as a label, create as text now
            row_uri_labels[row_uri] = f'row {rowIndex}'

            # add the gene
            if gene_name:
                row_gene = gene_symbol
                if row_gene:
                    monarch_uri = mygids.get_gene_id(row_gene)
                    if monarch_uri:
                        full_monarch_uri = MONARCH[monarch_uri]
                        graph.add((row_uri, BIOLINK.Gene, full_monarch_uri))
                        logging.debug(f"Added gene information for {row_gene}: {full_monarch_uri}")
                        matched_genes += 1
                    else:
                        if 'ensembl' in row_gene.lower():
                            graph.add((row_uri, ENSEMBL.id, Literal(row_gene)))
                        elif 'entrez' in row_gene.lower() or 'ncbi' in row_gene.lower():
                            graph.add((row_uri, NCBIGENE.id, Literal(row_gene)))
                        else:
                            graph.add((row_uri, BIOLINK.symbol, Literal(row_gene)))
                        unmatched_genes += 1

            # add the p-value
            if pval_name:
                row_pval = pval_symbol
                if row_pval:
                    logging.debug(f"Adding pval information for {row_pval}")
                    graph.add((row_uri, EDAM.data_1669, Literal(row_pval)))

            # add the log fold change
            if lfc_name:
                row_lfc = lfc_symbol
                if row_lfc:
                    logging.debug(f"Adding lfc information for {row_lfc}")
                    graph.add((row_uri, EDAM.data_3754, Literal(row_lfc)))

#                     # Add any other columns as generic predicates - removed for now to reduce graph size but can be readded for future use
# #                        predicate = URIRef(f"rdf:predicate/{column}")
# #                        graph.add((row_uri, predicate, Literal(value)))
            rowIndex += 1
    logging.info(f"Finished processing {rowIndex} rows in {csv_file_path}")

    # Save the row URI labels to a file for later reference
    logging.info(f"Saving graph file ...")
    if graph_file:
        graph.serialize(destination=graph_file, format='nt', encoding= "utf-8" )
        filename_row_uri_labels_path = graph_file + '.row_uri_labels.json'
        row_uri_labels = {str(k): v for k, v in row_uri_labels.items()}  # Convert keys to strings for JSON serialization
        with open(filename_row_uri_labels_path, 'w') as f:
            json.dump(row_uri_labels, f)
    else:
        logging.warning(f"Warning: graph_folder not provided, row_uri_labels not saved to {filename_row_uri_labels_path}")

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
    command_line_str = ' '.join(sys.argv)

    # manage the command line options
    parser = argparse.ArgumentParser(description='Convert downloaded supplementary data to graph precursor')
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-f','--per_file', action='store_true', help="Create one graph per data file (default is one graph)")
    parser.add_argument('-p','--per_pmid', action='store_true', help="Create one graph per PMID (default is one graph). Overridden by per_file)")
    parser.add_argument('-m','--metadata', action='store_true', help="Process the article metadata file (default is to process all data files)")
    parser.add_argument('-l','--log', default='create_rdf_triples.log', help='Log file name. This file is created in the top-level directory.')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    # note that per_file is taken if oth are set true
    per_file = config['per_file']
    per_pmid = config['per_pmid']
    metadata = config['metadata']

    main_dir = config['input_dir']


    if not os.path.isdir(main_dir):
        raise AKGException(f"create_rdf_triples: data directory {main_dir} must exist")

    # set up logging
    akg_logging_config( os.path.join(main_dir, config['log']))
    logging.info(f"Program executed with command: {command_line_str}")
    
    tracking_file = config['tracking_file']
    tracking_file = os.path.join(main_dir, tracking_file)

    if not os.path.exists(tracking_file):
        raise AKGException(f"create_rdf_triples: {tracking_file} must exist")

    if not check_tracking_writeable(tracking_file):
        raise AKGException(f"create_rdf_triples: {tracking_file} must be writable: close it in Excel and try again")

    supp_data_folder = os.path.join(main_dir,"supp_data")
    if not os.path.isdir(supp_data_folder):
        raise AKGException(f"create_rdf_triples: supplementary data directory {supp_data_folder} must exist")

    graph_folder = os.path.join(main_dir, "graph")
    os.makedirs(graph_folder, exist_ok=True)

    # set up the persistent storage for filename to UUID mapping
    file_to_uuid = 'filename_uuid_map.json'
    file_to_uuid_path = os.path.join(graph_folder, file_to_uuid)
    if not os.path.isfile(file_to_uuid_path):
        logging.info(f"Creating a new {file_to_uuid_path} file.")
    g_filename_uuid_map = FilenameUUIDMap(file_to_uuid_path)

    matched_genes = 0
    unmatched_genes = 0 
    total_files_processed = 0

    article_file_path = os.path.join(main_dir, 'asd_article_metadata.csv')
    if not os.path.isfile(article_file_path):
        logging.error(f"Error: running create_rdf_triples.py but {article_file_path} does not exist: run processing.py first ")
    else:
        # earlier versions used this file to manage exclusion, to be replaced by the tracking file but still currently needed for metadata
        # TODO: resolve usage of article_file_path
        adf = pd.read_csv(article_file_path, encoding='unicode_escape')

    # the exclusion is now in the tracking file
    tdf = load_tracking(tracking_file)
    
    # create a local DataFrame to hold the tracking information for this run
    local_tdf = create_empty_tracking_store()

    # used by the all-together approach
    global_graph = create_base_graph()

    # per file means separate graphs for each csv file, to be combined by combine_graphs
    if per_file:
        logging.info('per file graph output chosen')
    elif per_pmid:
        logging.info('per pmid not yet implemented')
    else:
        global_csv_count = 0
        global_matched_genes = 0
        global_unmatched_genes = 0

        logging.info(f"Processing file: {article_file_path}")
        process_metadata_csv(article_file_path, global_graph)

    for index, row in tdf.iterrows():
        # only handle the output of csv_data_cleaning (step 3)
        if row['step'] == 3:
            excl = row['excl']
            root = row['path']
            file = row['file']
            pmid = row['pmid']
            gene_name = row['gene']
            pval_name = row['pval']
            lfc_name  = row['lfc']
            file_path = os.path.join(root, file)
            if excl:
                logging.info(f"Excluding file: {file_path} manual: {row['manual']} : {row['manualreason']}")
            else:
                logging.info(f"Processing file: {file_path}")
                if per_file:
                    graph = create_base_graph()
                    # add the metadata in to every graph, not big, if requested
                    if metadata:
                        logging.info(f"Processing file: {article_file_path}")
                        process_metadata_csv(article_file_path, graph)
                    else:
                        logging.info(f"Skipping metadata processing for file: {article_file_path}")

                    mg_before = matched_genes
                    ug_before = unmatched_genes
                    graph_file_name = f"graph_{file}.nt"
                    graph_file = os.path.join(root, graph_file_name)

                    matched_genes, unmatched_genes = process_regular_csv(file_path, matched_genes, unmatched_genes, graph, graph_file, gene_name, pval_name, lfc_name)
                    logging.info(f"Processing file: {file_path} complete")
                    logging.info(f"Combined graph has been serialized to {graph_file}")
                    tdf.loc[index,'graphfile'] = graph_file
                    tdf.loc[index,'unmatched'] = (unmatched_genes-ug_before)
                    tdf.loc[index,'matched']   = (matched_genes-mg_before)
                    # write out the updated information for the source dataset (will have the new files we just wrote out)
                    # do this inside the loop so that we can keep track of the progress of an aborted run
                    save_tracking(tdf, tracking_file)
                    # Add the new file to the local tracking DataFrame
                    new_entry = tracking_entry(4, root, pmid, graph_file_name, False, True, file_path, False, False, '', 0, '', '', '', graph_file_name, 0, 0, False, '')

                    local_tdf = add_to_tracking(local_tdf, new_entry)

                elif per_pmid:
                    logging.info('per pmid not yet implemented')
                else:
                    mg_before = matched_genes
                    ug_before = unmatched_genes
                    matched_genes, unmatched_genes = process_regular_csv(file_path, matched_genes, unmatched_genes, global_graph)
                    global_matched_genes += matched_genes - mg_before
                    global_unmatched_genes += unmatched_genes - ug_before
    
    # add the new entries
    tdf = add_to_tracking(tdf, local_tdf)
    
    # write out the updated information (should have the new files we just wrote out)
    save_tracking(tdf, tracking_file)

    if per_file:
        pass
    elif per_pmid:
        logging.info('per pmid not yet implemented')
    else:
        logging.info(f"Processing file: {file_path} complete")
        global_graph_file = os.path.join(graph_folder, 'main_graph.nt')
        global_graph.serialize(destination=global_graph_file, format='nt', encoding= "utf-8" )
        logging.info(f"Combined graph has been serialized to {global_graph_file}")


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


