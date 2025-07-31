# akg
The Birkbeck ASD Knowledge Graph

"A central information hub of gene expression data from primary research articles, focussed on Autism, specifically utilising data from supporting information accompanying the publications" (T Hill, 2024).

## Aims
* Build on the work of https://github.com/tamjhill/ASDProject

## Workflow for using the code
This section is an outline of the project and available code.

All code files named below have a command line interface that give some control of configuration. Type, for example:
```
python data_convert.py --help
```
to identify these.

Steps in creating and using a graph are as follows:

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

Excluding downloaded data at this point based on PMID can be achieved by deleting it or moving it to a different location. The subsequent steps only work on files under the given top level directory.

3. checking each supplementary data file for relevant expression info and generating derived data set files, one for each table of data
    - data_convert.py

Use this as follows:
```
python data_convert.py -i <top_level_directory>
```
The derived dataset files are named expdata_<filename>.csv, where <filename> is the data file that it came from. These are in the same directory as the datafile itself.

4. Inspection and manual exclusion of data.
data_convert.py this will create an excel spreadsheet 'tracking' file (by default named 'akg_tracking.xlsx'), with one line per downloaded supplementary data file, and then one line per derived dataset file.
The derived dataset file lines include the name of the data file they were generated from.

Inspect the tracking file for dataset lines where the 'log fold change' column has been incorrectly identified and exclude them from subsequent processing. You can do this by setting the 'excl' column to TRUE (save and close the spreadsheet before moving to the next step).  In this case, for reporting and tracking integrity it is also useful to set the 'manual' column to TRUE and put some explanatory text in the 'manualreason' column of the spreadsheet which is there for this purpose.

The code that matches the log fold change column is a simple text match as follows:

```python
    for col in df.columns:
        if any(phrase in re.sub(r'[_\s-]', '', col.lower()) for phrase in ['logfoldchange', 'logfold', 'logfold2', 'lf', 
                                                                           'expression', 'enrichment', 'logfc', 'foldchange', 'fc', 
                                                                           'log2', 'lf2', 'lfc', 'log2fc', 'log', 'fold']):
            log_fold_col = col
            break
 ```

An example of where one would manually exclude the answer given by this algorithm was where a column headed 'ontology' is wrongly identified because this word contains the substring 'log'.

6. data cleaning
    - csv_data_cleaning.py 
This implements a simple cleaning algorithm on the data. It outputs a file clean_expdata_<filename>.csv for each dataset.

Use this as follows:
```
python csv_data_cleaning.py
```

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
