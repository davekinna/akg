# tracking report generator
# loads the tracking file and generates a report containing the contents of the AKG,
# as described by the tracking file. Most useful here is the data for which PMIDs are in the graph,
# which are not, and which tables are used by each PMID.
import argparse
import logging
import os
import pandas as pd
from akg import AKGException, akg_logging_config
from tracking import load_tracking
import sys

def main():
    command_line_str = ' '.join(sys.argv)
    parser = argparse.ArgumentParser(description="Generate a report from the tracking file")
    # manage the command line options
    parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t','--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-m','--metadata', action='store_true', help="Process the article metadata file (default is to skip this step)")
    parser.add_argument('-l','--log', default='tracking_report.log', help='Log file name. This file is created in the top-level directory.')
    parser.add_argument('-e', '--excluded', action='store_false', help="Report on excluded PMIDs (default is to skip this step)")
    parser.add_argument('-r','--report_file', default='tracking_report.txt', help='Report file name. This file is created in the top-level directory.')
    config = vars(parser.parse_args())

    metadata = config['metadata']
    excluded = config['excluded']

    main_dir = config['input_dir']  

    if not os.path.isdir(main_dir):
        raise AKGException(f"tracking_report: data directory {main_dir} must exist")

    # set up logging
    akg_logging_config( os.path.join(main_dir, config['log']))
    logging.info(f"Program executed with command: {command_line_str}")

    tracking_file = config['tracking_file']
    tracking_file = os.path.join(main_dir, tracking_file)
    if not os.path.isfile(tracking_file):
        raise AKGException(f"tracking_report: tracking file {tracking_file} must exist")
    logging.info(f"Loading tracking file {tracking_file}")
    tdf = load_tracking(tracking_file)
    logging.info(f"Tracking file loaded")

# the pmids with step=0 are the source publications

# print out the pmids with step=0
    logging.info(f"Number of source PMIDs (step=0): {len(tdf[tdf['step']== 0]['pmid'].unique())}")
    if len(tdf[tdf['step']== 0]) == 0:
        logging.warning(f"No source PMIDs found in tracking file")
        return
    
# open the report file
    report_file = config['report_file'] 
    report_file = os.path.join(main_dir, report_file)
    with open(report_file, 'w', encoding='utf-8-sig') as rf:
        rf.write(f"Tracking report generated from tracking file {tracking_file}\n")
        rf.write(f"Number of source PMIDs (step=0): {len(tdf[tdf['step']== 0])}\n")
        rf.write("Source PMIDs (step=0):\n")
        for pmid in tdf[tdf['step']== 0]['pmid'].unique():
            rf.write(f"{pmid}\n")

    # the files with step=0 are the downloaded files, the first ones in the process
        for pmid in tdf[tdf['step']== 0]['pmid'].unique():
            pmid_rows = tdf[tdf['pmid'] == pmid]
            rf.write(f"\nPMID: {pmid} downloaded files:\n")
            downloaded_files = pmid_rows[pmid_rows['step'] == 0]['file'].unique()

            full_dofi_names = []
            for dofi in downloaded_files:
                # get the row of the tracking file for this downloaded file
                trow = pmid_rows[(pmid_rows['step'] == 0) & (pmid_rows['file'] == dofi)]
                if len(trow) != 1:
                    logging.warning(f"Tracking file row for downloaded file {dofi} not found or ambiguous")
                    continue
                dofi_path = trow.iloc[0]['path']
                # construct the name for comparison with the filenames in the source column
                full_dofi_name = os.path.join(dofi_path, dofi)
                rf.write(f"\t{full_dofi_name}\n")
                full_dofi_names.append(full_dofi_name)

    # step 1: split
            for full_dofi_name in full_dofi_names:
                # find the rows for which this file is the source
                split_source_rows = pmid_rows[pmid_rows['source'] == full_dofi_name]
                if len(split_source_rows) == 0:
                    rf.write(f"\nNo split files found for downloaded file {full_dofi_name}\n")
                    continue
                rf.write(f"\nSplit files derived from {full_dofi_name}:\n")
                full_ssf_names = []
                for ssf in split_source_rows['file'].unique():
                    ssf_row = split_source_rows[split_source_rows['file'] == ssf]
                    if len(ssf_row) != 1:
                        logging.warning(f"Tracking file row for split file {ssf} not found or ambiguous")
                        continue
                    ssf_path = ssf_row.iloc[0]['path']
                    full_ssf_name = os.path.join(ssf_path, ssf)
                    rf.write(f"\t{full_ssf_name}\n")
                    full_ssf_names.append(full_ssf_name)

    # step 2: data_convert
                for full_ssf_name in full_ssf_names:
                    data_convert_source_rows = pmid_rows[pmid_rows['source'] == full_ssf_name]
                    if len(data_convert_source_rows) == 0:
                        rf.write(f"\tNo data_convert files found for split file {full_ssf_name}\n")
                        continue
                    rf.write(f"\tData convert files derived from {full_ssf_name}:\n")
                    full_dcf_names = []
                    for dcf in data_convert_source_rows['file'].unique():
                        dcf_row = data_convert_source_rows[data_convert_source_rows['file'] == dcf]
                        if len(dcf_row) != 1:
                            logging.warning(f"Tracking file row for data_convert file {dcf} not found or ambiguous")
                            continue
                        dcf_path = dcf_row.iloc[0]['path']
                        full_dcf_name = os.path.join(dcf_path, dcf)
                        rf.write(f"\t\t{full_dcf_name}\n")
                        full_dcf_names.append(full_dcf_name)

    # step 3: csv_data_cleaning
                    for full_dcf_name in full_dcf_names:
                        csv_data_cleaning_source_rows = pmid_rows[pmid_rows['source'] == full_dcf_name]
                        if len(csv_data_cleaning_source_rows) == 0:
                            rf.write(f"\t\tNo csv_data_cleaning files found for data_convert file {full_dcf_name}\n")
                            continue
                        rf.write(f"\t\tCSV data cleaning files derived from {full_dcf_name}:\n")
                        full_cdcf_names = []
                        for cdcf in csv_data_cleaning_source_rows['file'].unique():
                            cdcf_row = csv_data_cleaning_source_rows[csv_data_cleaning_source_rows['file'] == cdcf]
                            if len(cdcf_row) != 1:
                                logging.warning(f"Tracking file row for csv_data_cleaning file {cdcf} not found or ambiguous")
                                continue
                            cdcf_path = cdcf_row.iloc[0]['path']
                            full_cdcf_name = os.path.join(cdcf_path, cdcf)
                            rf.write(f"\t\t\t{full_cdcf_name}\n")
                            full_cdcf_names.append(full_cdcf_name)

    # step 4: create_rdf_triples
                            for full_cdcf_name in full_cdcf_names:
                                create_rdf_triples_source_rows = pmid_rows[pmid_rows['source'] == full_cdcf_name]
                                if len(create_rdf_triples_source_rows) == 0:
                                    rf.write(f"\t\t\tNo create_rdf_triples files found for csv_data_cleaning file {full_cdcf_name}\n")
                                    continue
                                rf.write(f"\t\t\tRDF triples files derived from {full_cdcf_name}:\n")
                                for crtf in create_rdf_triples_source_rows['file'].unique():
                                    crtf_row = create_rdf_triples_source_rows[create_rdf_triples_source_rows['file'] == crtf]
                                    if len(crtf_row) != 1:
                                        logging.warning(f"Tracking file row for create_rdf_triples file {crtf} not found or ambiguous")
                                        continue
                                    crtf_path = crtf_row.iloc[0]['path']
                                    crtf_pval = crtf_row.iloc[0]['pval']
                                    crtf_lfc = crtf_row.iloc[0]['lfc']
                                    crtf_gene = crtf_row.iloc[0]['gene']
                                    full_crtf_name = os.path.join(crtf_path, crtf)
                                    rf.write(f"\t\t\t\t{full_crtf_name}\n")
                                    rf.write(f"\t\t\t\t\tcolumn names: PVAL: '{crtf_pval}', LFC: '{crtf_lfc}', GENE: '{crtf_gene}'\n")

if __name__ == "__main__":
    main()
