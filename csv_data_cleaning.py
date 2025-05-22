import pandas as pd
import os
import re
import warnings


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


def process_csv_file(file_path):
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
        df_cleaned.to_csv(file_path, index=False, sep=",")
        print(f"Processed and overwritten: {file_path}")
    except pd.errors.DtypeWarning:
        print(f"Skipped file due to mixed data types: {file_path}")
    except Exception as e:
        print(f"Error processing file {file_path}: {str(e)}")


def process_data_folder(data_folder:str,  article_file_path:str):
    df = pd.read_csv(article_file_path)

    # only work on the entries that haven't been excluded
    df = df[~df['exclude']]

    pmids = df['pmid'].tolist()

    for pmid in pmids:
        pmid_folder = os.path.join(data_folder, str(pmid))
        for root, dirs, files in os.walk(pmid_folder):
            for file in files:
                if file.startswith('expdata') and file.endswith('.csv'):
                    file_path = os.path.join(root, file)
                    print(f"Processing file: {file_path}")
                    process_csv_file(file_path)

if __name__ == '__main__':
    main_dir = 'data'
    if not os.path.isdir(main_dir):
        os.mkdir(main_dir)
    article_file_path = os.path.join(main_dir, 'asd_article_metadata.csv')
    if not os.path.isfile(article_file_path):
        print(f"Error: running csv_data_cleaning.py but {article_file_path} does not exist: run processing.py first ")

    supp_data_folder = os.path.join(main_dir,"supp_data")
    process_data_folder(supp_data_folder, article_file_path)
    