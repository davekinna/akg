from time import sleep
from typing import Tuple
import os
import google.generativeai as genai
from dotenv import load_dotenv
import textwrap
import json
import argparse
from akg import AKGException, akg_logging_config
import logging
from tracking import load_tracking, save_tracking
import sys 
import pandas as pd
import re

def standard_check(file_path:str, skip_rows:int)->Tuple[bool,str, str]:
    """Check (using standard algorithm) if the file is of the type we require
    for our study. See prompt_template below for the exact details.

    Args:
        file_path (str): The path to the file to check.
    Returns:
        bool: True if the file is of the required type, False otherwise.
        str: Explanation of the result.
        lfc: the title of the column containing log fold changes.
    """
    # Read the content of the file
    try:
        # Try reading with different settings
        for encoding in ['utf-8', 'iso-8859-1', 'latin1']:
# commented out previous version           for delim in ['\t', ',', ';']:  # prioritize tab
            for delim in [',', '\t', ';']:  # prioritize comma, this is a CSV file. I don't know why the previous prioritisation was used.
                try:
                    # this is the only point where the skip at the start of the file is made
                    # after this stage, the column headers are assumed to be on the first line.
                    df = pd.read_csv(file_path, delimiter=delim, encoding=encoding, on_bad_lines='warn', skiprows=skip_rows)
                    if not df.empty:
# commented out previous version                       df.columns = df.columns.astype(str)
                        log_fold_col = None
                        for col in df.columns:
                            logging.debug(f"Column found: {col}")
                            if any(phrase in re.sub(r'[_\s-]', '', col.lower()) for phrase in ['logfoldchange', 'logfold', 'logfold2', 'lf', 
                                                                                            'expression', 'enrichment', 'logfc', 'foldchange', 'fc', 
                                                                                            'log2', 'lf2', 'lfc', 'log2fc', 'log', 'fold']):
                                log_fold_col = col
                                logging.info(f"Log Fold Change Column: {log_fold_col}")
                                break
                        if log_fold_col:
                            return True, "Found a log fold change column.", log_fold_col
                        else:
                            return False, "No suitable column found.", ''
                except Exception as e:
                    logging.error(f"Failed to read {file_path} with delimiter '{delim}' and encoding '{encoding}': {str(e)}")
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    return False, "File is not of the required type.", ''


if __name__ == "__main__":

    command_line_str = ' '.join(sys.argv)

    # manage the command line options
    parser = argparse.ArgumentParser(description='Check the format of chosen files using Google Gemini AI model.')
    parser.add_argument('-i', '--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t', '--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-l', '--log', default='standard_check.log', help='Log file name. This file is created in the top-level directory.')
    parser.add_argument('-e', '--exclude', action='store_true', help='Set the tracking file exclude value to True for the files that are not suitable')
    parser.add_argument('-c', '--check-one-file', default=None, help='Check this one file only, in the input directory')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    main_dir = config['input_dir']
    one_file = config['check_one_file']
    record_exclusions = config['exclude']

    if one_file:
        filename = one_file

        is_valid, explanation, lfc = standard_check(filename, 0)
        if is_valid:
            print(f"File '{filename}' is of the required type.")
        else:
            print(f"File '{filename}' is not of the required type.")
        print(f"Explanation: {explanation}")
        print(f"Log Fold Change Column: {lfc}") 
    else:
        if not os.path.isdir(main_dir):
            raise AKGException(f"data_convert: data directory {main_dir} must exist") 

        akg_logging_config(os.path.join(main_dir, config['log']))
        logging.info(f"Program executed with command: {command_line_str}")

        logging.info(f'Top-level data directory {os.path.realpath(main_dir)}')

        # create the tracking file    
        tracking_file = config['tracking_file']
        tracking_file = os.path.join(main_dir, tracking_file)
        if not os.path.exists(tracking_file):
            raise AKGException(f'No tracking file {tracking_file}, cannot track results or determine which files to process')

        # loop over all the files identified by the tracking file and process them
        df = load_tracking(tracking_file)

    # TODO: remove loop iteration, do sthg more pythonic
        for index, row in df.iterrows():
            root = row['path']
            file = row['file']
            skip_rows = row['skip'] if 'skip' in row else 0
            # only operate on those files created by data_convert
            # ignore excluded flag at present, to make a comparison
            if row['step'] == 1:
                if row['excl']:
                    logging.info(f"File: {file_path} flagged as excluded")
                file_path = os.path.join(root, file)
                logging.info(f"Processing file: {file_path}")
                is_valid, explanation, lfc = standard_check(file_path, skip_rows)
                if is_valid:
                    logging.info(f"File '{file_path}' is of the required type.")
                else:
                    logging.info(f"File '{file_path}' is not of the required type.")
                logging.info(f"Explanation: {explanation}")
                if lfc:
                    logging.info(f"Log Fold Change Column: {lfc}")
                df.loc[int(index),'suitable'] = is_valid
                df.loc[int(index),'suitablereason'] = explanation
                df.loc[int(index),'lfc'] = lfc
                if not is_valid and record_exclusions:
                    df.loc[int(index),'excl'] = True
                    logging.info(f"Excluding file: {file_path}")

        save_tracking(df, tracking_file)
