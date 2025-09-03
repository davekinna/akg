import os
import re
import pandas as pd
import tempfile
from akg import AKGException
import logging
"""
Tracking functions
TODO: refactor to a class
"""
tracking_col_names = {'step':'int'
                        , 'path':"str"
                        , 'pmid':"str"
                        , 'file':"str"
                        , 'excl': "bool"
                        , 'derived':"bool"
                        , 'source':"str"
                        , 'cleaned':'bool'
                        , 'manual':"bool"
                        , 'manualreason':"str"
                        , 'skip':'int'
                        , 'pval':'str'
                        , 'gene':'str'
                        , 'lfc':"str"
                        , 'graphfile':'str'
                        , 'matched':'int'
                        , 'unmatched':'int'
                        , 'suitable':'bool'
                        , 'suitablereason':'str'
                        }

def create_empty_tracking_store()->pd.DataFrame:
    """
    create_empty_tracking_store
    Parameters: 
    Returns:
        an empty pandas dataframe with the correct column headers
    """
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in tracking_col_names.items()})

def add_to_tracking(existing:pd.DataFrame, new:pd.DataFrame)->pd.DataFrame:
    """"
    Adds 'new' entry to existing tracking DataFrame

    Parameters:
    Both have the correct column headers
        existing:   pd.DataFrame      a tracking store
        new:        pd.DataFrame      a tracking store

    Returns:
        the content of existing, with new's entries added
    """
    return pd.concat([existing,new],ignore_index=True)

def check_tracking_writeable(tracking_file_path:str)->bool:
    """
    Check if the tracking file is writable
    parameters:
        tracking_file_path: str   The full path to the tracking file (actually any file)
    """
    try:
        # 'w' will create the file if it doesn't exist.
        with open(tracking_file_path, 'r+') as f:
            # If open() succeeds, you will be able to write.
            pass
    except (IOError, PermissionError) as e:
        return False
    return True

def create_tracking(folder:str, name:str='akg_tracking.xlsx'):
    """
    Create the file that can be used to track the contents of 'folder' through the akg process
    This will start as a pandas dataframe serialised to a file
    """
    # create an empty dataframe
    df = create_empty_tracking_store()
    logging.info(f'Creating a tracking file {name} for the contents of folder:{folder}')
    for dirpath, dirnames, filenames in os.walk(folder):
        for filename in filenames:
            pmid = os.path.basename(dirpath)
            # assuming a PMID consists of 8 digits
            if re.fullmatch(r'\d{8}',pmid):
                new = tracking_entry(0,dirpath,pmid,filename,False,False,'',False,False,'', 0, '', '', '','', 0, 0,False,'')
                df = add_to_tracking(df,new)
                
    save_tracking(df, name)

def tracking_entry(step:int, path:str, pmid:str, filename:str, excl:bool, derived:bool, source:str, cleaned:bool, manual:bool, manualreason:str, 
                   skip:int, pval:str, gene:str, lfc:str, graphfile:str, matched:int, unmatched:int, suitable:bool, suitablereason:str)->pd.DataFrame:
    """
    Format the provided data into a default tracking entry
    """
    return pd.DataFrame([{'step':step,"path":path,"pmid":int(pmid),"file":filename, "excl":excl, "derived":derived,"source":source,"cleaned":cleaned, 
                          "manual":manual, "manualreason":manualreason, "skip":skip, "pval":pval, "gene":gene,'lfc':lfc, 'graphfile':graphfile, 'matched':matched, 'unmatched':unmatched,
                          'suitable':suitable, 'suitablereason':suitablereason}])

def load_tracking(name:str='akg_tracking.xlsx')->pd.DataFrame:
    """
    Load the tracking data into memory from file
    """

    if not os.path.exists(name):
        raise AKGException(f'Tracking file {name} does not exist')

    with pd.ExcelFile(name) as xls:
        df = pd.read_excel(xls, "akg tracking", keep_default_na=False)  

    # I'm sure there's a better way:
    df['step'] = df['step'].astype('int')
    df['pmid'] = df['pmid'].astype('int')
    df['excl'] = df['excl'].astype("bool")
    df['derived'] = df['derived'].astype("bool")
    df['manual'] = df['manual'].astype("bool")
    df['cleaned'] = df['cleaned'].astype("bool")
    df['skip'] = df['skip'].astype('int')
    df['matched'] = df['matched'].astype('int')
    df['unmatched'] = df['unmatched'].astype('int')
    df['suitable'] = df['suitable'].astype('bool')

    return df

def save_tracking(df:pd.DataFrame, name:str='akg_tracking.xlsx'):
    """
    Save the tracking data to file
    """
    # sort the data first
    sorted_df = df.sort_values(by=['step','pmid','file'])

    with pd.ExcelWriter(name) as writer:
        sorted_df.to_excel(writer,index=False,sheet_name='akg tracking', )  


if __name__ == "__main__":
    supp_path = os.path.join('data','supp_data')
    create_tracking(supp_path)
    # df = load_tracking()
    # print(df)

def test_create_tracking():
    """
    Just test the file creation based on an existing directory
    """

    # Create and enter a temporary directory
    with tempfile.TemporaryDirectory(prefix="scratch_") as scratch_dir:
        print("Scratch dir created at:", scratch_dir)
    
        test_file = os.path.join(scratch_dir, "testtrack.xlsx")
        assert not os.path.exists(test_file)

        supp_path = os.path.join('data','supp_data')
        create_tracking(supp_path, test_file)

        assert os.path.exists(test_file)

def test_tracking_to_df():
    """
    Create some content to track and test that it can be read into a dataframe correctly
    """
        # Create and enter a temporary directory
    with tempfile.TemporaryDirectory(prefix="scratch_") as scratch_dir:
        print("Scratch dir created at:", scratch_dir)
    
        track_file = os.path.join(scratch_dir, "testtrack.xlsx")
        assert not os.path.exists(track_file)

        # create some content
        supp_dir = os.path.join(scratch_dir, 'supp_data', '12345678')
        os.makedirs(supp_dir)        
        datafile = os.path.join(supp_dir, 'datafile.csv')
        with open(datafile, 'a'):
            pass

        # start the tracking (create the file)
        create_tracking(supp_dir, track_file)

        assert os.path.exists(track_file)

        # it should be a csv file that we can read into pandas
        df = load_tracking(track_file)

        print(df)