import re
import sys

# Regex to capture Subject, Predicate, and Object from N-Triples
# It handles both <URIs> and "Literals"
TRIPLE_REGEX = re.compile(r'^<(?P<s1>[^>]+)>\s+<(?P<p1>[^>]+)>\s+(?:<(?P<o_uri>[^>]+)>|"(?P<o_lit>[^"]+)")\s+\.$')

def get_numeric_value(line):
    """Extracts the numeric value if the predicate is a 'data_' type."""
    match = TRIPLE_REGEX.match(line.strip())
    if match:
        pred = match.group('p1')
        # We target predicates containing 'edamontology.org/data_'
        if "edamontology.org/data_" in pred:
            val_str = match.group('o_lit')
            try:
                return float(val_str)
            except (ValueError, TypeError):
                return None
    return None

def process_file(input_path):
    # Pass 1: Find Min and Max
    values = []
    with open(input_path, 'r') as f:
        for line in f:
            val = get_numeric_value(line)
            if val is not None:
                values.append(val)

    if not values:
        print("No numeric data found for binning.")
        return

    v_min, v_max = min(values), max(values)
    v_range = v_max - v_min

    # Pass 2: Reformat and Output
    with open(input_path, 'r') as f:
        for line in f:
            val = get_numeric_value(line)
            
            if val is not None:
                # Calculate bin index (0 to 9)
                if v_range == 0:
                    bin_idx = 0
                else:
                    # Map value to 0.0 - 1.0 range, then multiply by 10
                    bin_idx = int(((val - v_min) / v_range) * 10)
                    if bin_idx > 9: bin_idx = 9 # Handle rounding at the very max
                
                # Reconstruct the line with the bin label
                # You can change "bin_" to something more descriptive if desired
                match = TRIPLE_REGEX.match(line.strip())
                s, p = match.group('s1'), match.group('p1')
                print(f'<{s}> <{p}> "bin_{bin_idx}" .')
            else:
                # Print non-numeric lines exactly as they are
                print(line.strip())

if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_file(sys.argv[1])
    else:
        print("Usage: python bin_edam.py your_data_file.nt")