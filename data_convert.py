"""takes excel, csv, tsv or txt files retrieved from pubmed, checks if they contain a column re. log fold changes, and saves sheet as csv file"""

import pandas as pd
import os
from openpyxl import load_workbook
import xlrd
import csv
import re
import argparse
from akg import AKGException
from tracking import create_tracking, load_tracking, save_tracking, create_empty_tracking_store, add_to_tracking, tracking_entry

def process_excel_file(file_path)->pd.DataFrame:
    """loads excel files into dataframes
    """
    # tracking DataFrame
    tdf = create_empty_tracking_store()

    try:
        wb = load_workbook(filename=file_path, read_only=True)
        output_dir = os.path.dirname(file_path)
        
        for sheet_name in wb.sheetnames:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
            new_file = process_dataframe(df, sheet_name, output_dir, file_path)
            tdf = add_to_tracking(tdf, new_file)

    except Exception as e:
        print(f"Failed to process excel file: {file_path}: {str(e)}")

    return tdf

def process_old_file(file_path)->pd.DataFrame:
    """loads older-style excel files (.xls) into dataframes
    """
    # tracking DataFrame
    tdf = create_empty_tracking_store()

    try:
        wb = xlrd.open_workbook(file_path)
        output_dir = os.path.dirname(file_path)
        for sheet in wb.sheets():
            print(f"Processing sheet: {sheet.name}")
            headers = [sheet.cell_value(0, col) for col in range(sheet.ncols)]
            data = [
                [sheet.cell_value(row, col) for col in range(sheet.ncols)]
                for row in range(1, sheet.nrows)
            ]
            df = pd.DataFrame(data, columns=headers)
            
            new_file = process_dataframe(df, sheet.name, output_dir, file_path)
            tdf = add_to_tracking(tdf, new_file)

    except Exception as e:
        print(f"Failed to process 'old' file: {file_path}: {str(e)}")

    return tdf

def process_csv_file(file_path:str)->pd.DataFrame:
    """loads csv, tsc or txt files and prepares them to be inputs to the AKG

        Parameters:
            file_path:str   The file to process
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
                df = pd.read_csv(file_path, delimiter=delim, encoding=encoding, on_bad_lines='warn')
                if not df.empty:
                    new_file = process_dataframe(df, file_name, output_dir, file_path, input_delimiter=delim)
                    return add_to_tracking(tdf, new_file)
            except Exception as e:
                print(f"Failed to read {file_path} with delimiter '{delim}' and encoding '{encoding}': {str(e)}")
    
    # If all attempts fail, try reading as plain text
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        print(f"File {file_path} couldn't be processed as CSV. Content preview:")
        print(content[:100])  # Print first 100 characters
    except Exception as e:
        print(f"Failed to read {file_path} as text: {str(e)}")

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


def process_dataframe(df, sheet_name, output_dir, file_path, input_delimiter='\t')->pd.DataFrame:
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
    
    # If matching column is found, save sheet as CSV
    if log_fold_col:
        print(f'log fold column is {log_fold_col}')
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
        print(f"Saved {sheet_name} as CSV: {output_file}")

        # assume the pmid is the last component of the output dir
        pmid = os.path.basename(output_dir)
        tdf = add_to_tracking(tdf, tracking_entry(1,output_dir, pmid, new_filename, False, True, file_path, False, False, '', log_fold_col, '', 0, 0))
    else:
        print(f"Skipped {sheet_name} in {file_path}: No 'log fold change' column found")

    return tdf

def process_supp_data_folder(data_folder:str, tracking_file_path:str ):
    """ 
    function process_supp_data_folder

    Walks through all immediate PMID-named subdirectories of data_folder, processes files found according to their extension
    Excludes subdirectories which are marked as 'exclude' in the CSV file defined in article_file_path
    *May* change contents of article_file_path at this level in future, doesn't do this at present

    Parameters:
        data_folder:str
        article_file_path:str # must be a full path

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
        root = row['path']
        file = row['file']
        file_path = os.path.join(root, file)
        # never process files that we wrote out on a previous iteration
        if file.lower().startswith('expdata_'):
            continue
        print(f"Processing file: {file_path}")
        if file.lower().endswith('.xlsx'):
            local_tdf = process_excel_file(file_path)
        elif file.lower().endswith('.xls'):
            local_tdf = process_old_file(file_path)
        elif file.lower().endswith(('.csv', '.tsv', '.txt')):
            local_tdf = process_csv_file(file_path)
        tdf = add_to_tracking(tdf,local_tdf)
        # now exclude the source data
        df.loc[int(index),'excl'] = True
        df.loc[int(index),'step'] = 1


    # now the loop has finished add the accumulated tracking info into the main one
    df = add_to_tracking(df, tdf)

    # write out the updated information (should have the new files we just wrote out)
    save_tracking(df, tracking_file_path)

    # pmids = df['pmid'].tolist().uniq()

    # for pmid in pmids:
    #     pmid_folder = os.path.join(data_folder, str(pmid))
    #     for root, dirs, files in os.walk(pmid_folder):
    #         for file in files:
    #             # skip files that we wrote out on a previous iteration
    #             if file.lower().startswith('expdata_'):
    #                 continue
    #             file_path = os.path.join(root, file)
    #             print(f"Processing file: {file_path}")
    #             if file.lower().endswith('.xlsx'):
    #                 process_excel_file(file_path)
    #             elif file.lower().endswith('.xls'):
    #                 process_old_file(file_path)
    #             elif file.lower().endswith(('.csv', '.tsv', '.txt')):
    #                 process_csv_file(file_path)

def save_filenames(data_folder:str, article_file_path:str, save_out_file:str='supp_files.txt'):
    """
    function save_filename

    Save the supplementary data file names to the given file, so that the work up to this point does not need to be repeated
    if it isn't necessary

    Parameters:
        data_folder:str
        article_file_path:str # must be a full path
        save_out_file:str

    Returns:
        None

    Raises:
        No direct exception handling/raising in this code

    """
    save_out_path = os.path.join(data_folder, save_out_file)

    df = pd.read_csv(article_file_path)

    # only work on the entries that haven't been excluded
    df = df[~df['exclude']]

    pmids = df['pmid'].tolist()

    with open(save_out_path, 'w', encoding="utf-8") as sof:

        for pmid in pmids:
            pmid_folder = os.path.join(data_folder, str(pmid))
            for dirpath, dirs, filenames in os.walk(pmid_folder):
                for filename in filenames:
                    if filename.endswith('.csv'):
                        csv_file_path = os.path.join(dirpath, filename)
                        sof.write(csv_file_path)
                        sof.write('\n')


if __name__ == '__main__':

    # manage the command line options
    parser = argparse.ArgumentParser(description='Convert downloaded supplementary data to graph precursor')
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    main_dir = config['input_dir']

    if not os.path.isdir(main_dir):
        raise AKGException(f"data_convert: data directory {main_dir} must exist")
    
    tracking_file = config['tracking_file']

    print(f'Processing directory {os.path.realpath(main_dir)}: creating tracking file {tracking_file} here')
    tracking_file = os.path.join(main_dir, tracking_file)

    create_tracking(main_dir, tracking_file)

    supp_data_folder = os.path.join(main_dir,"supp_data")
    process_supp_data_folder(supp_data_folder, tracking_file)

    # save_filenames(supp_data_folder, article_file_path)