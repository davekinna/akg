import pytest 
import time
import sys


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
        # create a dict for lookup of ensemble IDs, mapping back to HGNC IDs.
        # this is an optimisation
        self._ens:dict[str,str] = {}
        with open(source, 'r') as file:
            next(file)  
            lines = file.readlines()
            self._lines = [line.upper() for line in lines]
        # populate the ensemble ID dict
        for line in self._lines:
            sline = line.split('\t')
            if len(sline) > 2: # (the second entry on the line is the ensemble ID for it to be useful)
                hgnc_ID = sline[0].strip() # first entry needs to be hgnc to be useful. See issue 17.
                if hgnc_ID.startswith('HGNC'):
                    ensemble_ID = sline[1].strip().upper()
                    if ensemble_ID.startswith('ENS'): # really is an ensemble ID
                        # for consistent behaviour with the original, don't overwrite 
                        # values with ones that are later on in the gene_ids.txt data
                        if ensemble_ID not in self._ens:
                            self._ens[ensemble_ID] = hgnc_ID
        print(f'ensemble_id to hgnc dict has {len(self._ens)} entries')
        sys.stdout.flush()

    def get_gene_id(self, gene_name:str):
        u_gene_name = gene_name.upper()
        direct_lookup = self._ens.get(u_gene_name, None)
        if direct_lookup is not None:
            return direct_lookup
        else:
            for line in self._lines:
                if u_gene_name in line: # .upper():
                    print(f"{gene_name} HGNC ID found")
                    sys.stdout.flush()
                    return line.split('\t')[0]
        # for optimisation, really useful to know what is not found
        print(f"HGNC ID not found for {gene_name}")
        sys.stdout.flush()
        return ''
        
# run the tests on the command line with 
# pytest -v akg.py
# (if you don't name the file, pytest will try to discover all in the current directory)
# or for a specific test:
# pytest -v akg.py::test_ens_1
# to see the timing data and anything else that is being printed out, use -s:
# pytest -v -s akg.py
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

def compare_for_test(gene:str, response:str, timing:bool=True, gids:GeneIdStore=None) -> GeneIdStore:
    """
    Compare two versions of lookup for a single gene, with timing if necessary
    Facilitates wider ranging tests

    Parameters:
        gene:str                the gene to search for
        response:str            the expected response
        timing:bool=True        set to true if timing output needed
        gids:GeneIdStore=None   the GeneIdStore to use. If None, one will be created

    Return value:
        The GeneIdStore used in this comparison. Useful to speed up repeat trials.
    """
    mygids = gids if gids is not None else GeneIdStore()

    start = time.perf_counter()

    r1 = get_gene_id(gene)
    assert r1 == response

    end = time.perf_counter()

    print(f"Original version, elapsed time for {gene} search: {end-start:.4f} seconds")

    start = time.perf_counter()

    r1 = mygids.get_gene_id(gene)
    assert r1 == response
    end = time.perf_counter()

    print(f"GeneIdStore version, elapsed time for {gene} search: {end-start:.4f} seconds")
    return mygids

def test_ens_1():
    """
    confirm consistent response for an input of type ENS...
    choose a gene that is low-down the file for the timing test
    file 'maketests.sh' generated these test lines
    """

    mygids = compare_for_test('ENSG00000198888','HGNC:7455')
    mygids = compare_for_test('ENSG00000198763','HGNC:7456',gids=mygids)
    mygids = compare_for_test('ENSG00000198804','HGNC:7419',gids=mygids)
    mygids = compare_for_test('ENSG00000198712','HGNC:7421',gids=mygids)
    mygids = compare_for_test('ENSG00000228253','HGNC:7415',gids=mygids)
    mygids = compare_for_test('ENSG00000198899','HGNC:7414',gids=mygids)
    mygids = compare_for_test('ENSG00000198938','HGNC:7422',gids=mygids)
    mygids = compare_for_test('ENSG00000198840','HGNC:7458',gids=mygids)
    mygids = compare_for_test('ENSG00000212907','HGNC:7460',gids=mygids)
    mygids = compare_for_test('ENSG00000198886','HGNC:7459',gids=mygids)
    mygids = compare_for_test('ENSG00000198786','HGNC:7461',gids=mygids)
    mygids = compare_for_test('ENSG00000198695','HGNC:7462',gids=mygids)
    mygids = compare_for_test('ENSG00000198727','HGNC:7427',gids=mygids)
    mygids = compare_for_test('ENSG00000274847','HGNC:31102',gids=mygids)
    mygids = compare_for_test('ENSG00000291368','HGNC:126',gids=mygids)
    mygids = compare_for_test('ENSG00000291420','HGNC:144',gids=mygids)
    mygids = compare_for_test('ENSG00000288204','HGNC:5017',gids=mygids)
    mygids = compare_for_test('ENSG00000291420','HGNC:144',gids=mygids)
    mygids = compare_for_test('ENSG00000288204','HGNC:5017',gids=mygids)
    mygids = compare_for_test('ENSG00000291420','HGNC:144',gids=mygids)
    mygids = compare_for_test('ENSG00000291421','HGNC:29279',gids=mygids)
    mygids = compare_for_test('ENSG00000288499','HGNC:22140',gids=mygids)
    mygids = compare_for_test('ENSG00000263150','HGNC:15311',gids=mygids)
    mygids = compare_for_test('ENSG00000262851','HGNC:15296',gids=mygids)
    mygids = compare_for_test('ENSG00000261897','HGNC:15297',gids=mygids)
    mygids = compare_for_test('ENSG00000262784','HGNC:14821',gids=mygids)
    mygids = compare_for_test('ENSG00000262611','HGNC:14824',gids=mygids)
    mygids = compare_for_test('ENSG00000262755','HGNC:15313',gids=mygids)
    mygids = compare_for_test('ENSG00000263328','HGNC:14831',gids=mygids)
    mygids = compare_for_test('ENSG00000262796','HGNC:14855',gids=mygids)
    mygids = compare_for_test('ENSG00000262315','HGNC:27538',gids=mygids)
    mygids = compare_for_test('ENSG00000281038','HGNC:29166',gids=mygids)
    mygids = compare_for_test('ENSG00000288269','HGNC:4192',gids=mygids)
    mygids = compare_for_test('ENSG00000288213','HGNC:28007',gids=mygids)
    mygids = compare_for_test('ENSG00000288186','HGNC:16813',gids=mygids)
    mygids = compare_for_test('ENSG00000281934','HGNC:14086',gids=mygids)
    mygids = compare_for_test('ENSG00000282175','HGNC:29295',gids=mygids)
    mygids = compare_for_test('ENSG00000282817','HGNC:28841',gids=mygids)
    mygids = compare_for_test('ENSG00000282584','HGNC:31971',gids=mygids)
    mygids = compare_for_test('ENSG00000282663','HGNC:27997',gids=mygids)
    mygids = compare_for_test('ENSG00000279195','HGNC:28415',gids=mygids)
    mygids = compare_for_test('ENSG00000282119','HGNC:30583',gids=mygids)
    mygids = compare_for_test('ENSG00000282437','HGNC:51234',gids=mygids)
    mygids = compare_for_test('ENSG00000282559','HGNC:51235',gids=mygids)
    mygids = compare_for_test('ENSG00000282566','HGNC:49179',gids=mygids)
    mygids = compare_for_test('ENSG00000282530','HGNC:48813',gids=mygids)
    mygids = compare_for_test('ENSG00000281987','HGNC:49178',gids=mygids)
    mygids = compare_for_test('ENSG00000282095','HGNC:51333',gids=mygids)
    mygids = compare_for_test('ENSG00000261958','HGNC:15319',gids=mygids)
    mygids = compare_for_test('ENSG00000262191','HGNC:31940',gids=mygids)
    mygids = compare_for_test('ENSG00000282298','HGNC:27996',gids=mygids)
    mygids = compare_for_test('ENSG00000282741','HGNC:13262',gids=mygids)
    mygids = compare_for_test('ENSG00000262647','HGNC:15322',gids=mygids)
    mygids = compare_for_test('ENSG00000282212','HGNC:30693',gids=mygids)
    mygids = compare_for_test('ENSG00000282424','HGNC:27995',gids=mygids)
    mygids = compare_for_test('ENSG00000281107','HGNC:15287',gids=mygids)
    mygids = compare_for_test('ENSG00000282583','HGNC:24074',gids=mygids)
    mygids = compare_for_test('ENSG00000282125','HGNC:49193',gids=mygids)
    mygids = compare_for_test('ENSG00000293551','HGNC:34393',gids=mygids)
    mygids = compare_for_test('ENSG00000291381','HGNC:26604',gids=mygids)
    mygids = compare_for_test('ENSG00000288263','HGNC:10013',gids=mygids)
    mygids = compare_for_test('ENSG00000291382','HGNC:28127',gids=mygids)
    mygids = compare_for_test('ENSG00000291375','HGNC:29249',gids=mygids)
    mygids = compare_for_test('ENSG00000291379','HGNC:30232',gids=mygids)
    mygids = compare_for_test('ENSG00000291401','HGNC:28026',gids=mygids)
    mygids = compare_for_test('ENSG00000291380','HGNC:25528',gids=mygids)
    mygids = compare_for_test('ENSG00000291387','HGNC:18341',gids=mygids)
    mygids = compare_for_test('ENSG00000291426','HGNC:16476',gids=mygids)

def test_ens_2():
    """
    As test_ens_1 but for the last 100. Takes longer, they're at the end of the file 
    file 'makemoretests.sh' generated these test lines
    """
    mygids = compare_for_test('ENSG00000244462','HGNC:9898')
    mygids = compare_for_test('ENSG00000108684','HGNC:99',gids=mygids)
    mygids = compare_for_test('ENSG00000171791','HGNC:990',gids=mygids)
    mygids = compare_for_test('ENSG00000102317','HGNC:9900',gids=mygids)
    mygids = compare_for_test('ENSG00000173933','HGNC:9901',gids=mygids)
    mygids = compare_for_test('ENSG00000003756','HGNC:9902',gids=mygids)
    mygids = compare_for_test('ENSG00000004534','HGNC:9903',gids=mygids)
    mygids = compare_for_test('ENSG00000076053','HGNC:9904',gids=mygids)
    mygids = compare_for_test('ENSG00000265241','HGNC:9905',gids=mygids)
    mygids = compare_for_test('ENSG00000100320','HGNC:9906',gids=mygids)
    mygids = compare_for_test('ENSG00000277564','HGNC:9906',gids=mygids)
    mygids = compare_for_test('ENSG00000153250','HGNC:9907',gids=mygids)
    mygids = compare_for_test('ENSG00000225422','HGNC:9908',gids=mygids)
    mygids = compare_for_test('ENSG00000076067','HGNC:9909',gids=mygids)
    mygids = compare_for_test('ENSG00000140379','HGNC:991',gids=mygids)
    mygids = compare_for_test('ENSG00000147274','HGNC:9910',gids=mygids)
    mygids = compare_for_test('ENSG00000216835','HGNC:9911',gids=mygids)
    mygids = compare_for_test('ENSG00000234414','HGNC:9912',gids=mygids)
    mygids = compare_for_test('ENSG00000169811','HGNC:9916',gids=mygids)
    mygids = compare_for_test('ENSG00000226092','HGNC:9917',gids=mygids)
    mygids = compare_for_test('ENSG00000224657','HGNC:9918',gids=mygids)
    mygids = compare_for_test('ENSG00000114115','HGNC:9919',gids=mygids)
    mygids = compare_for_test('ENSG00000171552','HGNC:992',gids=mygids)
    mygids = compare_for_test('ENSG00000114113','HGNC:9920',gids=mygids)
    mygids = compare_for_test('ENSG00000265203','HGNC:9921',gids=mygids)
    mygids = compare_for_test('ENSG00000138207','HGNC:9922',gids=mygids)
    mygids = compare_for_test('ENSG00000234159','HGNC:9923',gids=mygids)
    mygids = compare_for_test('ENSG00000100387','HGNC:9928',gids=mygids)
    mygids = compare_for_test('ENSG00000137875','HGNC:993',gids=mygids)
    mygids = compare_for_test('ENSG00000049449','HGNC:9934',gids=mygids)
    mygids = compare_for_test('ENSG00000117906','HGNC:9935',gids=mygids)
    mygids = compare_for_test('ENSG00000102076','HGNC:9936',gids=mygids)
    mygids = compare_for_test('ENSG00000109047','HGNC:9937',gids=mygids)
    mygids = compare_for_test('ENSG00000153094','HGNC:994',gids=mygids)
    mygids = compare_for_test('ENSG00000135437','HGNC:9940',gids=mygids)
    mygids = compare_for_test('ENSG00000112619','HGNC:9942',gids=mygids)
    mygids = compare_for_test('ENSG00000137710','HGNC:9944',gids=mygids)
    mygids = compare_for_test('ENSG00000255387','HGNC:9945',gids=mygids)
    mygids = compare_for_test('ENSG00000223391','HGNC:9946',gids=mygids)
    mygids = compare_for_test('ENSG00000004700','HGNC:9948',gids=mygids)
    mygids = compare_for_test('ENSG00000160957','HGNC:9949',gids=mygids)
    mygids = compare_for_test('ENSG00000129473','HGNC:995',gids=mygids)
    mygids = compare_for_test('ENSG00000108469','HGNC:9950',gids=mygids)
    mygids = compare_for_test('ENSG00000115386','HGNC:9951',gids=mygids)
    mygids = compare_for_test('ENSG00000172023','HGNC:9952',gids=mygids)
    mygids = compare_for_test('ENSG00000204787','HGNC:9953',gids=mygids)
    mygids = compare_for_test('ENSG00000162924','HGNC:9954',gids=mygids)
    mygids = compare_for_test('ENSG00000173039','HGNC:9955',gids=mygids)
    mygids = compare_for_test('ENSG00000104856','HGNC:9956',gids=mygids)
    mygids = compare_for_test('ENSG00000189056','HGNC:9957',gids=mygids)
    mygids = compare_for_test('ENSG00000143839','HGNC:9958',gids=mygids)
    mygids = compare_for_test('ENSG00000102032','HGNC:9959',gids=mygids)
    mygids = compare_for_test('ENSG00000175730','HGNC:996',gids=mygids)
    mygids = compare_for_test('ENSG00000005007','HGNC:9962',gids=mygids)
    mygids = compare_for_test('ENSG00000169891','HGNC:9963',gids=mygids)
    mygids = compare_for_test('ENSG00000133884','HGNC:9964',gids=mygids)
    mygids = compare_for_test('ENSG00000142599','HGNC:9965',gids=mygids)
    mygids = compare_for_test('ENSG00000084093','HGNC:9966',gids=mygids)
    mygids = compare_for_test('ENSG00000165731','HGNC:9967',gids=mygids)
    mygids = compare_for_test('ENSG00000009413','HGNC:9968',gids=mygids)
    mygids = compare_for_test('ENSG00000035928','HGNC:9969',gids=mygids)
    mygids = compare_for_test('ENSG00000236616','HGNC:997',gids=mygids)
    mygids = compare_for_test('ENSG00000049541','HGNC:9970',gids=mygids)
    mygids = compare_for_test('ENSG00000133119','HGNC:9971',gids=mygids)
    mygids = compare_for_test('ENSG00000163918','HGNC:9972',gids=mygids)
    mygids = compare_for_test('ENSG00000111445','HGNC:9973',gids=mygids)
    mygids = compare_for_test('ENSG00000169733','HGNC:9974',gids=mygids)
    mygids = compare_for_test('ENSG00000204713','HGNC:9975',gids=mygids)
    mygids = compare_for_test('ENSG00000234495','HGNC:9975',gids=mygids)
    mygids = compare_for_test('ENSG00000229006','HGNC:9975',gids=mygids)
    mygids = compare_for_test('ENSG00000233948','HGNC:9975',gids=mygids)
    mygids = compare_for_test('ENSG00000215641','HGNC:9975',gids=mygids)
    mygids = compare_for_test('ENSG00000237462','HGNC:9975',gids=mygids)
    mygids = compare_for_test('ENSG00000237071','HGNC:9975',gids=mygids)
    mygids = compare_for_test('ENSG00000204977','HGNC:9976',gids=mygids)
    mygids = compare_for_test('ENSG00000128250','HGNC:9977',gids=mygids)
    mygids = compare_for_test('ENSG00000225465','HGNC:9978',gids=mygids)
    mygids = compare_for_test('ENSG00000128253','HGNC:9979',gids=mygids)
    mygids = compare_for_test('ENSG00000069399','HGNC:998',gids=mygids)
    mygids = compare_for_test('ENSG00000128276','HGNC:9980',gids=mygids)
    mygids = compare_for_test('ENSG00000205853','HGNC:9981',gids=mygids)
    mygids = compare_for_test('ENSG00000288283','HGNC:9982',gids=mygids)
    mygids = compare_for_test('ENSG00000132005','HGNC:9982',gids=mygids)
    mygids = compare_for_test('ENSG00000087903','HGNC:9983',gids=mygids)
    mygids = compare_for_test('ENSG00000080298','HGNC:9984',gids=mygids)
    mygids = compare_for_test('ENSG00000111783','HGNC:9985',gids=mygids)
    mygids = compare_for_test('ENSG00000143390','HGNC:9986',gids=mygids)
    mygids = compare_for_test('ENSG00000064490','HGNC:9987',gids=mygids)
    mygids = compare_for_test('ENSG00000133111','HGNC:9988',gids=mygids)
    mygids = compare_for_test('ENSG00000130988','HGNC:9989',gids=mygids)
    mygids = compare_for_test('ENSG00000148604','HGNC:9990',gids=mygids)
    mygids = compare_for_test('ENSG00000090104','HGNC:9991',gids=mygids)
    mygids = compare_for_test('ENSG00000148908','HGNC:9992',gids=mygids)
    mygids = compare_for_test('ENSG00000076344','HGNC:9993',gids=mygids)
    mygids = compare_for_test('ENSG00000159788','HGNC:9994',gids=mygids)
    mygids = compare_for_test('ENSG00000127074','HGNC:9995',gids=mygids)
    mygids = compare_for_test('ENSG00000169220','HGNC:9996',gids=mygids)
    mygids = compare_for_test('ENSG00000143333','HGNC:9997',gids=mygids)
    mygids = compare_for_test('ENSG00000116741','HGNC:9998',gids=mygids)
    mygids = compare_for_test('ENSG00000138835','HGNC:9999',gids=mygids)
