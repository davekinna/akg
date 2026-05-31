from Bio import Entrez
import time
import metapub

fetcher = metapub.PubMedFetcher()
time.sleep(1)  # force a gap before each call
pmidi = 31097668
article = fetcher.article_by_pmid(pmidi)
#article = fetcher.article_by_pmid("31097668")
