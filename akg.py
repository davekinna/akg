import pytest 
import time


def get_gene_id(gene_name) -> str:
    """retrieves relevant HGNC gene if from file gene_ids.txt.
    Currently removes extra transcript info for simplicity - can be added back in in future trials
    """
    # Remove 'hp_' and variant info to help matching process
    if gene_name.startswith('hp_'):
        gene_name = gene_name[3:]
    if '_' in gene_name[-5:]:
        gene_name = gene_name[:gene_name.rfind('_', len(gene_name) - 5)]    
    if '.' in gene_name:
        gene_name = gene_name.split('.')[0]
    genefile = 'gene_ids.txt'
    #print(f"Searching for gene: {gene_name}")
    with open(genefile, 'r') as file:
        next(file)  
        for line in file:
            if gene_name.upper() in line.upper():
                #print(f"{gene_name} HGNC ID found")
                return line.split('\t')[0]
    #print(f"HGNC ID not found for {gene_name}")
    return ''

class GeneIdStore:
    """
    Store of gene IDs in multiple formats. For searching.
    """
    def __init__(self, source:str="gene_ids.txt"):
        with open(source, 'r') as file:
            next(file)  
            lines = file.readlines()
            self._lines = [line.upper() for line in lines]
            # self._lines = file.readlines()
    def get_gene_id(self, gene_name:str):
        for line in self._lines:
            if gene_name.upper() in line: # .upper():
                #print(f"{gene_name} HGNC ID found")
                return line.split('\t')[0]
    #print(f"HGNC ID not found for {gene_name}")
        return ''
        

def test_sanity():
    """
    function test_sanity - checks the testing is working
    """
    

def test_original_get_gene_id():
    """
    Just run the original with timing. 

    Test the function twice: the optimised version will cache the require data, 
    so the speed improvement will come on the second call
    
    """
    not_found = 'GO:0006952'

    start = time.perf_counter()

    test_count = 100.
    for i in 1,test_count:
        r1 = get_gene_id(not_found)
        assert r1 == ''

    end = time.perf_counter()

    test_elapsed = end-start
    test_mean = test_elapsed/test_count

    print(f"Elapsed time for {test_count} calls: {test_elapsed:.4f} seconds (mean={test_mean:.4f})")


def test_create_GIDS():
    mygids = GeneIdStore()

def test_new_get_gene_id():
    not_found = 'GO:0006952'


    mygids = GeneIdStore()

    start = time.perf_counter()

    test_count = 100.
    for i in 1,test_count:
        r1 = mygids.get_gene_id(not_found)
        assert r1 == ''

    end = time.perf_counter()

    test_elapsed = end-start
    test_mean = test_elapsed/test_count

    print(f"GeneIdStore version, elapsed time for {test_count} calls: {test_elapsed:.4f} seconds (mean={test_mean:.4f})")
