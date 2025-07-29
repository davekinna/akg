# akg
The Birkbeck ASD Knowledge Graph

"A central information hub of gene expression data from primary research articles, focussed on Autism, specifically utilising data from supporting information accompanying the publications" (T Hill, 2024).

## Aims
* Build on the work of https://github.com/tamjhill/ASDProject

## Workflow for using the code
Outline of the project and code:

1. finding relevant articles
    - processing.py

2. retrieving article metadata, abstracts and supplementary data files
    - processing.py

Use this as follows:
```
python processing.py -o <top_level_directory>
```

The data files are output to directories under top_level_directory. These are organised by PMID - i.e., the next level of directories is named by the numeric pubmed ID value. 
Beneath each of those is a directory 'supp_data' holding the downloaded data files.

3. checking each supplementary data file for relevant expression info and generating derived data set files, one for each table of data
    - data_convert.py

Use this as follows:
```
python data_convert.py -i <top_level_directory>
```
The derived dataset files are named expdata_<filename>.csv, where <filename> is the data file that it came from. These are in the same directory as the datafile itself.

By default this will create an excel spreadsheet file 'akg_tracking.xlsx', with one line per data file, and then one line per derived dataset file.
The derived dataset file lines include the name of the data file they were generated from.
You can exclude a dataset from subsequent processing by setting the 'excl' column to TRUE (save and close the spreadsheet before using this).

4. data cleaning
    - csv_data_cleaning.py 

Use this as follows:

6. mapping to rdf triples
    - create_rdf_triples.py
    - graph_cleanup.py

7. data testing and analysis (see analysis directory)
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
