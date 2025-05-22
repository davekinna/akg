# akg
The Birkbeck ASD Knowledge Graph

"A central information hub of gene expression data from primary research articles, focussed on Autism, specifically utilising data from supporting information accompanying the publications" (T Hill, 2024).

## Aims
* Build on the work of https://github.com/tamjhill/ASDProject

## Workflow for using the code
These are the original author's notes and are still relevant.

Outline of the project and code:

1. finding relevant articles
    - processing.py

2. retrieving article metadata, abstracts and supporting files
    - processing.py

3. checking each data file for relevant expression info
    - dataconvert.py
   
4. data cleaning
    - csv_data_cleaning.py 

5. mapping to rdf triples
    - create_rdf_triples.py
    - graph_cleanup.py

6. data testing and analysis (see analysis directory)
    - general_tests.ipynb
    - graphanalysis.ipynb
    - usecase1.ipynb
    - usecase2.ipynb
    - usecase2.ipynb

Retrieved article outputs are stored in the 'data' directory, the rdf graph is stored in 'cleaned_maingraph.nt' .

## Developer notes
* Work on the 'dev' branch, merge back into the main branch for stable versions
* tag the main branch
* Use issues to define work steps
* Include a reference to a commit when an issue is closed
