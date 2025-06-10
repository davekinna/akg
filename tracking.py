import os
import re
import pandas as pd
import tempfile
from akg import AKGException
from processing import AkgException

def create_tracking(folder:str, name:str='akg_tracking.xlsx'):
    """
    Create the file that can be used to track the contents of 'folder' through the akg process
    This will start as a pandas dataframe serialised to a csv file
    It may evolve to a class.
    """
    # create an empty dataframe
    tracking_col_names = {'path':"str"
                          , 'pmid':"str"
                          , 'file':"str"
                          , 'excl': "bool"
                          , 'source':"str"
                          , 'derived':"bool"
                          , 'manual':"bool"
                          , 'manualreason':"str"
                          }
    df = pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in tracking_col_names.items()})
    print(f'Creating a tracking file {name} for the contents of folder:{folder}')
    with open(name,'w') as tracker_file:
        for dirpath, dirnames, filenames in os.walk(folder):
            for filename in filenames:
                pmid = os.path.basename(dirpath)
                # assuming a PMID consists of 8 digits
                if re.fullmatch(r'\d{8}',pmid):
                    new = pd.DataFrame([{"path":dirpath,"pmid":pmid,"file":filename, "excl":True, "source":"","derived":False, "manual":True, "manualreason":""}])
                    df = pd.concat([df,new],ignore_index=True)
    df.to_csv(name, index=False)
    with pd.ExcelWriter(name) as writer:
        df.to_excel(writer,index=False,sheet_name='akg tracking', )  

def load_tracking(name:str='akg_tracking.xlsx')->pd.DataFrame:
    """
    Load the tracking data into memory from file
    """

    if not os.path.exists(name):
        raise AkgException(f'Tracking file {name} does not exist')

    with pd.ExcelFile(name) as xls:
        df = pd.read_excel(xls, "akg tracking")  

    # I'm sure there's a better way:
    df['excl'] = df['excl'].astype("bool")
    df['derived'] = df['derived'].astype("bool")
    df['manual'] = df['manual'].astype("bool")

    return df

if __name__ == "__main__":
    # supp_path = os.path.join('data','supp_data')
    # create_tracking(supp_path)
    df = load_tracking()
    print(df)

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
    
        track_file = os.path.join(scratch_dir, "testtrack.csv")
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