"""takes excel, csv, tsv or txt files retrieved from pubmed, checks if they contain a column re. log fold changes, and saves sheet as csv file"""

from fileinput import filename
import logging
import pandas as pd
import os
from openpyxl import load_workbook
import xlrd
import csv
import re
import argparse
from akg import AKGException, akg_logging_config
from tracking import create_tracking, load_tracking, save_tracking, create_empty_tracking_store, add_to_tracking, tracking_entry
import sys


def process_csv_file(file_path:str, skip_rows:int=0, pval_name:str='', gene_name:str='', lfc_name:str='')->pd.DataFrame:
    """loads csv, tsc or txt files and prepares them to be inputs to the AKG

        Parameters:
            file_path:str   The file to process
            skip_rows:      The number of lines at the top of the file to skip past
            pval_name:      The name at the head of the pval column
            gene_name:      The name at the head of the gene column
            lfc_name:       The name at the head of the lfc column
        Returns:
            Information about the added output files (if any) in a form suitable for adding to the tracking data (a DataFrame)
    """
    # The processing creates files that need to be added to the tracking, which can't be done inside the loop.
# this is the pattern for adding some:
#    added_files = pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in tracking_col_names.items()})
#    df = pd.concat([df,added_files],ignore_index=True)

    # tracking DataFrame
    tdf = create_empty_tracking_store()

    output_dir = os.path.dirname(file_path)
    file_name = os.path.splitext(os.path.basename(file_path))[0]
    # Try reading with different settings
    for encoding in ['utf-8', 'iso-8859-1', 'latin1']:
        for delim in ['\t', ',', ';']:  # prioritize tab
            try:
                # this is the only point where the skip at the start of the file is made
                # after this stage, the column headers are assumed to be on the first line.
                df = pd.read_csv(file_path, delimiter=delim, encoding=encoding, on_bad_lines='warn', skiprows=skip_rows)
                if not df.empty:
                    new_file = process_dataframe(df, file_name, output_dir, file_path, input_delimiter=delim, skip_rows=skip_rows, pval_name=pval_name, gene_name=gene_name, lfc_name=lfc_name)
                    return add_to_tracking(tdf, new_file)
            except Exception as e:
                logging.error(f"Failed to read {file_path} with delimiter '{delim}' and encoding '{encoding}': {str(e)}")

    # If all attempts fail, try reading as plain text
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        logging.info(f"File {file_path} couldn't be processed as CSV. Content preview:")
        logging.info(content[:100])  # Print first 100 characters
    except Exception as e:
        logging.error(f"Failed to read {file_path} as text: {str(e)}")

    return tdf

def test_lfc_search():
    """Debug test snippet from process_dataframe, to confirm that some odd LFC columns are being chosen
    because of the compression of the column name (see the reg expression)
    """
    col = "Relevance of circQTLs to ASD"
    log_fold_col = ''
    if any(phrase in re.sub(r'[_\s-]', '', col.lower()) for phrase in ['logfoldchange', 'logfold', 'logfold2', 'lf', 
                                                                        'expression', 'enrichment', 'logfc', 'foldchange', 'fc', 
                                                                        'log2', 'lf2', 'lfc', 'log2fc', 'log', 'fold']):
        log_fold_col = col

    sqcol = re.sub(r'[_\s-]', '', col.lower())
    print(sqcol)
    for phrase in ['logfoldchange', 'logfold', 'logfold2', 'lf', 
                   'expression', 'enrichment', 'logfc', 'foldchange', 'fc', 
                   'log2', 'lf2', 'lfc', 'log2fc', 'log', 'fold']:
        print(f'{phrase}:{sqcol.find(phrase)}\n')
    assert log_fold_col
    print(f'log_fold_col:{log_fold_col}')


def process_dataframe(df:pd.DataFrame, sheet_name:str, output_dir:str, file_path:str, input_delimiter:str='\t', skip_rows:int=0, pval_name:str='', gene_name:str='', lfc_name:str='')->pd.DataFrame:
    """processes dataframes to assess if the data relates to gene expression - looks for "log fold change" or similar
    in column titles
    """
    # tracking DataFrame. There should be a maximum of one entry in the returned value because this function works on a single dataframe
    tdf = create_empty_tracking_store()

    df.columns = df.columns.astype(str)
    log_fold_col = None
    for col in df.columns:
        if any(phrase in re.sub(r'[_\s-]', '', col.lower()) for phrase in ['logfoldchange', 'logfold', 'logfold2', 'lf', 
                                                                           'expression', 'enrichment', 'logfc', 'foldchange', 'fc', 
                                                                           'log2', 'lf2', 'lfc', 'log2fc', 'log', 'fold']):
            log_fold_col = col
            break
    # save the file as .csv but ONLY if a log fold column is found or nominated through the input 
    if log_fold_col or lfc_name:
        if lfc_name:
            logging.info(f'Using lfc_name from tracking file: {lfc_name}')
            log_fold_col = lfc_name
        else:
            logging.info(f'Using log_fold_col from simple string match implemented in process_dataframe')
        logging.info(f'log fold column is {log_fold_col}')
        # try to fix some odd characters
#        sheet_name = sheet_name.encode(encoding="ascii",errors="backslashreplace")
        # remove characters not appropriate for filenames
        replacement_chars  = {" " : "",
                              "<" : "lessthan",
                              ">" : "morethan",
                              "." : "",
                              ":" : "",
                              "/" : "",
                              "?" : "",
                              "*" : "",
                              "&" : "" }
        for old, new in replacement_chars.items():
            sheet_name = sheet_name.replace(old, new)
        if sheet_name.startswith('split_'):
            start_index = len('split_')
            new_filestub = f'expdata_{sheet_name[start_index:]}'
        else:
            new_filestub = f'expdata_{sheet_name}'
        new_filename = new_filestub+'.csv'
        output_file = os.path.join(output_dir, new_filename)

        if os.path.exists(output_file):
            original_filename = os.path.splitext(os.path.basename(file_path))[0]
            new_filename = f"{new_filestub}_{original_filename}.csv"
            output_file = os.path.join(output_dir, new_filename)

        if input_delimiter == '\t':
            df.to_csv(output_file, index=False, sep=',')
        else:
            df.to_csv(output_file, index=False)
        logging.info(f"Saved {sheet_name} as CSV: {output_file}")

        # assume the pmid is the last component of the output dir
        pmid = os.path.basename(output_dir)
        # create a new tracking entry
        new_entry = tracking_entry(2,output_dir,pmid,new_filename, False, True, file_path, False, False, '', skip_rows, pval_name, gene_name, log_fold_col,'', 0, 0,False,'')
        tdf = add_to_tracking(tdf, new_entry)
    else:
        logging.info(f"Skipped {sheet_name} in {file_path}: No 'log fold change' column found")

    return tdf

def process_supp_data_folder(data_folder:str, tracking_file_path:str):
    """ 
    function process_supp_data_folder

    Walks through all files listed in the tracking file
    If they are the output of data_split (step=1) and not excluded, process them.
    That means, check for whether they are useful to us and, if so, create a copy called expdata_filename with step=2 in the tracking file.

    Parameters:
        data_folder:str
        article_file_path:str   # must be a full path
        check_only:bool         # check LFC column and record its name in the tracking file under lfc.

    Returns:
        None

    Raises:
        No direct exception handling/raising in this code    

    """
    df = load_tracking(tracking_file_path)

# The processing creates files that need to be added to the tracking, which can't be done inside the loop.
    tdf  = create_empty_tracking_store()
    local_tdf = create_empty_tracking_store()
# TODO: remove loop iteration, do sthg more pythonic
    for index, row in df.iterrows():
        # data_convert only works on step 1 files, the raw data that was downloaded and then split
        if row['step'] == 1 and not row['excl']:
            root = row['path']
            filename = row['file']
            file_path = os.path.join(root, filename)
            # never process files that we wrote out on a previous iteration
            logging.info(f"Processing file: {file_path}")
            if filename.lower().endswith(('.csv')):
                local_tdf = process_csv_file(file_path, skip_rows=row['skip'], pval_name=row['pval'], gene_name=row['gene'], lfc_name=row['lfc'])
            else:
                logging.info(f'Skipping file: {file_path}, should be a .csv file ')
                continue
            tdf = add_to_tracking(tdf,local_tdf)
    logging.info(f'Finished processing files in {data_folder}, found {len(tdf)} new files to add to tracking')

    # now the loop has finished add the accumulated tracking info into the main one
    df = add_to_tracking(df, tdf)

    # write out the updated information (should have the new files we just wrote out)
    save_tracking(df, tracking_file_path)


if __name__ == '__main__':

    command_line_str = ' '.join(sys.argv)

    # manage the command line options
    parser = argparse.ArgumentParser(description='Convert downloaded supplementary data to graph precursor')
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-l', '--log', default='data_convert.log', help='Log file name. This file is created in the top-level directory.')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    main_dir = config['input_dir']

    check_only = config['check_only']

    if not os.path.isdir(main_dir):
        raise AKGException(f"data_convert: data directory {main_dir} must exist") 

    akg_logging_config(os.path.join(main_dir, config['log']))
    logging.info(f'Starting data_convert in {main_dir}')
    logging.info(f"Program executed with command: {command_line_str}")

    # create the tracking file    
    tracking_file = config['tracking_file']
    if not os.path.exists(tracking_file):
        raise AKGException(f"create_rdf_triples: {tracking_file} must exist")

    logging.info(f'Processing directory {os.path.realpath(main_dir)}')
    tracking_file = os.path.join(main_dir, tracking_file)

    log_file = config['log']
    log_file = os.path.join(main_dir, log_file)

    supp_data_folder = os.path.join(main_dir,"supp_data")
    process_supp_data_folder(supp_data_folder, tracking_file)

    # save_filenames(supp_data_folder, article_file_path)