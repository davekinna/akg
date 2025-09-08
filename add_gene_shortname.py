import csv
import sys
import os
from akg import GeneIdStore

def add_shortname_column(input_filepath, output_filepath, gidstore: GeneIdStore):
    """
    Reads a CSV file, adds a 'shortname' column, 
     If a field starts with 'https://monarchinitiative.org/', translate it to a short gene name and add
     its name to the new column. If there are no HGNC fields, the new column will be empty.

    Parameters:
        input_filepath (str): The path to the source CSV file.
        output_filepath (str): The path where the modified CSV file will be saved.
    """
    monarch_url_stub = "https://monarchinitiative.org/"
    
    try:
        with open(input_filepath, mode='r', newline='', encoding='utf-8') as infile, \
             open(output_filepath, mode='w', newline='', encoding='utf-8') as outfile:
            
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            
            # Read and update the header
            try:
                header = next(reader)
                writer.writerow(header + ['shortname'])
            except StopIteration:
                print("Warning: Input CSV file is empty.")
                return

            # Process each data row
            for row in reader:
                shortname = ''
                for field in row:
                    if isinstance(field, str) and field.startswith(monarch_url_stub):
                        # Extract the identifier after the prefix
                        identifier = field[len(monarch_url_stub):]
                        # Get the shortname using the provided function
                        shortname = gidstore.get_hgnc_symbol(identifier)
                        # Once found, no need to check other fields in the same row
                        break 
                
                # Append the shortname (or an empty string) and write the new row
                writer.writerow(row + [shortname])
                
        print(f"\nProcessing complete. Output written to: {output_filepath}")

    except FileNotFoundError:
        print(f"Error: The file '{input_filepath}' was not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


# read a csv file with several columns and loop over the results
if __name__ == "__main__":
    # take filename from command line argument
    if len(sys.argv) != 2:
        print("Usage: python script.py <csvfilename>")
        sys.exit(1)

    # this is a local class that reads a JSON file from HGNC that holds the gene ID mappings
    # an alternative would be to use the HGNC lookup service
    mygids = GeneIdStore()

    csvfilename = sys.argv[1]
    outputfilename = sys.argv[2] if len(sys.argv) > 2 else "output.csv"
    if not os.path.isfile(csvfilename):
        print(f"Error: File '{csvfilename}' not found.")
        sys.exit(1)
    add_shortname_column(csvfilename, outputfilename, mygids)