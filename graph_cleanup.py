"""script to add extra data cleaning to the file graph file - ensures any values are given correct datatype (double or data), 
and that any blank values are removed. Stores final graph as cleaned_maingraph.nt
"""
import re

def process_nt_file(input_file, output_file):
    decimal_pattern = re.compile(r'"(-?\d+(\.\d+)?([eE][-+]?\d+)?)"')
    empty_literal_pattern = re.compile(r'\s+"(\s*|-)"(\^\^<[^>]+>)?\s*\.$')
    date_pattern = re.compile(r'<http://purl.org/dc/terms/date>\s+"(\d+)"\s+\.$')

    with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
        for line in infile:
            if line.strip() == '' or empty_literal_pattern.search(line):
                continue

            #find any date predicate, label datatype of the object as a date
            if 'http://purl.org/dc/terms/date' in line:
                modified_line = date_pattern.sub(r'<http://purl.org/dc/terms/date> "\1"^^<http://www.w3.org/2001/XMLSchema#gYear> .', line)
                outfile.write(modified_line)
            else:
                #find any decimal value, label datatype of the object as a double
                match = decimal_pattern.search(line)
                if match:
                    modified_line = decimal_pattern.sub(r'"\1"^^<http://www.w3.org/2001/XMLSchema#double>', line)
                    outfile.write(modified_line)
                else:
                    outfile.write(line)

input_file = 'main_graph.nt'
output_file = 'cleaned_maingraph.nt'
process_nt_file(input_file, output_file)