import pandas as pd
import os
import re
import warnings
import argparse
import logging
from akg import AKGException, akg_logging_config
from tracking import create_tracking, load_tracking, save_tracking, create_empty_tracking_store, add_to_tracking, tracking_entry


def rename_ensembl_column(df):
    """finds a column with clear ensembl data and renames the column title
    """
    for column in df.columns:
        if df[column].dtype == 'object':  # Check if the column contains strings
            ensembl_count = df[column].iloc[1:].astype(str).str.match(r'^ENS(G|T)', case=False).sum()
            if ensembl_count > 3:
                df = df.rename(columns={column: 'ensembl'})
                break
    return df


def process_csv_file(file_path)->str:
    """Data cleaning for the saved expression info csv files.
    removes rows with multiple blank cells, and removes spaces and characters from column headers.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.DtypeWarning)
            df = pd.read_csv(file_path)
    # Remove rows with multiple NAs or blanks
        df_cleaned = df.dropna(thresh=len(df.columns)//4)
        # Process column names to remove extra characters and gaps to help searching and prevent broken URIs
        df_cleaned.columns = df_cleaned.columns.map(lambda x: re.sub(r'[\s\-_<>\(\)\[\]\{\}]', '', x.lower()))
        # Rename Ensembl column if it exists
        df_cleaned = rename_ensembl_column(df_cleaned)

        # prepend 'clean_' to the filename for output
        base_name = os.path.basename(file_path)
        dir_name = os.path.dirname(file_path)
        new_file_name = f"clean_{base_name}"
        new_file_path = os.path.join(dir_name, new_file_name)
        df_cleaned.to_csv(new_file_path, index=False, sep=",")
        logging.info(f"Processed to: {new_file_path}")
        return new_file_name
    except pd.errors.DtypeWarning:
        logging.info(f"Skipped file due to mixed data types: {file_path}")
    except Exception as e:
        logging.error(f"Error processing file {file_path}: {str(e)}")

    # default is to return None, failure to add any new file
    return None

def process_data_folder(data_folder:str,  tracking_file:str):

    df = load_tracking(tracking_file)
    tdf = create_empty_tracking_store()

    for index, row in df.iterrows():
        excl = row['excl']
        root = row['path']
        file = row['file']
        pmid = row['pmid']
        lfc = row['lfc']
        file_path = os.path.join(root, file)
        if excl:
            logging.info(f"Excluding file: {file_path} manual: {row['manual']} : {row['manualreason']}")
        else:
            df.loc[index,'step'] = 2
            if file.endswith('.csv'):
                logging.info(f"Processing file: {file_path}")
                new_file_path = process_csv_file(file_path)
                if new_file_path:
                    # Add the new file to the tracking DataFrame
                    new_entry = tracking_entry(3, root, pmid, new_file_path, False, True, file_path, False, False,lfc, '', '', 0, 0)
                    tdf = add_to_tracking(tdf, new_entry)
                df.loc[index,'cleaned'] = True

    # now the loop has finished add the accumulated tracking info into the main one
    df = add_to_tracking(df, tdf)

    # write out the updated information (should have the new files we just wrote out)
    save_tracking(df, tracking_file)

if __name__ == '__main__':

    # manage the command line options
    parser = argparse.ArgumentParser(description='Convert downloaded supplementary data to graph precursor')
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-l','--log', default='csv_data_cleaning.log', help='Log file name. This file is created in the top-level directory.')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    main_dir = config['input_dir']

    if not os.path.isdir(main_dir):
        raise AKGException(f"data_convert: data directory {main_dir} must exist")
    
    # set up logging
    akg_logging_config( os.path.join(main_dir, config['log']))

    tracking_file = config['tracking_file']
    tracking_file = os.path.join(main_dir, tracking_file)

    # the tracking file must exist because it tells us which files to process
    if not os.path.exists(tracking_file):
        raise AKGException(f"csv_data_cleaning: {tracking_file} must exist")

    supp_data_folder = os.path.join(main_dir,"supp_data")
    process_data_folder(supp_data_folder, tracking_file)
    