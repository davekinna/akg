# akg
An Autism Knowledge Graph

"A central information hub of gene expression data from primary research articles, focussed on Autism, specifically utilising data from supporting information accompanying the publications" (T Hill, 2024).

## Aims
* Build on the work of https://github.com/tamjhill/ASDProject

## Installation
A fully automated installation is not yet in place (see https://github.com/davekinna/akg/issues/34). To check out the code with command line git:
```
git clone https://github.com/davekinna/akg.git
```
This will create a subdirectory 'akg' with the python scripts in. The most recent code version is on the dev branch - so to see this in your environment:
```
cd akg
git checkout dev
```
... and then return to the parent directory (cd ..), the examples below do this to avoid mixing code and data. With the current immature version of the code, you may need to install modules to run the code.

## Workflow for using the code
This section is an outline of the project and available code.  

I assume here you are running from the directory level above the source code (which is in directory akg).

All code files named below have a command line interface that give some control of configuration. Type, for example:
```
python akg\data_convert.py --help
```
to run the code and identify the available options.  In the following examples many of the defaults have been used, and so the tracking file, for example, is given the name 'akg_tracking.xlsx'. If you change this at an early stage, subsequent steps must be supplied with the same value because they read from as well as write to the tracking file.

Steps in creating and using a graph are as follows:

1. Create a working directory for your downloaded data, derived data and graph files. I refer to this here as <top_level>. Everything will be downloaded to, or generated here. 

2. find relevant articles:
```
python akg\processing.py -s -i d2025-08-12
```
This conducts a search for suitable articles, and saves information about them to 'asd_article_metadata.csv'.  
It doesn't download them. Instead, you should review 'asd_article_metadata.csv' and exclude articles that you don't want to continue with, by marking the 'exclude' column 'True'.

3. retrieve more article metadata, abstracts and the supplementary data files (tables of data) that will eventually form the graph:
```
python akg\processing.py -d -i <top_level>
```
This will scan asd_article_metadata.csv for the non-excluded files, and download supplementary data for them. The data files are output to <top_level>/supp_data.  The next level of directories under supp_data is named by the numeric pubmed ID value. 
So, the files are/should be downloaded to <top_level>/supp_data/<PMID>.

Excluding downloaded data at this point based on PMID can be achieved by deleting it or moving it to a different location. The subsequent steps only work on files under the given top level directory.

As an alternative, to just go through the process for one publication, provide its PMID on the command line:
```
python akg\processing.py -p <pmid> -d -i <top_level>
```

4. Split the supplementary data files if necessary and generate derived data set files, one CSV file for each table of data. These are called split_*.csv.
```
python akg\data_split.py -i <top_level>
```
This will have created a file in the data directories, alongside the source data that was downloaded, called split_*tablename*.csv. It does this for *all files* in the supp_data/<pmid> directories, so delete or move any data that you don't want included at this point, or work in a new separate <top_level> directory if necessary.
These are now the working data files. data_split.py also will have created a tracking file called (by default) akg_tracking.xlsx, and a log file called data_split.log.

3.1 Use AI to suggest which of the derived dataset files are suitable for subsequent processing.
    - genai_check.py

Use this as follows:
```
python akg\genai_check.py -i <top_level>
```
This needs to be run after data_split.py has been run. It looks for the derived dataset file names (with name split_*) and updates the value in column 'suitable' of the tracking file with TRUE if it judges the given file to be of further use, and puts its reasoning (whatever the outcome) in column 'suitablereason'.  If you judge that the AI check has been giving a good selection, use the -e argument to set the values in the 'excl' column to the same as those in the AI choice (see step 4 below):
```
python akg\genai_check.py -e -i <top_level>
```

3. checking each supplementary data file for relevant expression info and generating derived data set files, one for each table of data 
    - data_convert.py

Use this as follows:
```
python akg\data_convert.py -i <top_level>
```
The derived dataset files are named expdata_<filename>.csv, where <filename> is the data file that it came from. These are in the same directory as the datafile itself.


4. Inspection and manual exclusion of data. 
data_convert.py will create an excel spreadsheet 'tracking' file (by default named 'akg_tracking.xlsx'), with one line per downloaded supplementary data file, and then one line per derived dataset file.
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
python akg\csv_data_cleaning.py -i <top_level>
```

6. mapping to rdf triples
    - create_rdf_triples.py
    - graph_cleanup.py
Use these as follows:
```
python akg\create_rdf_triples.py -f -i d2025-08-26
```
```
python .\akg\graph_cleanup.py -i d2025-08-26 -n combined.nt -u clean_combined.nt
```
This takes the file d2025-08-26\graph\combined.nt, applies some cleaning criteria (currently putting the date and numerical quantities into a consistent format), and sends the output to d2025-08-26\graph\clean_combined.nt. This cleaning could be applied as part of the create_rdf_triples step: using a separate program allows a change in the reformatting to be applied without timeconsuming re-scanning of all the data files.

7. data testing and analysis
Example SparQL query files are in directory akg\query. These can be incorporated into Jupyter notebook files. Alternatively, the following utility will execute a SparQL query and write its output to another file, with logging and data in the usual locations, and input (-q) and output (-o) files relative to the data (-i) directory:
```
python .\akg\query_graph.py -i d2025-08-26 -q hgnc.rq -u hgnc.csv clean_combined.nt
```
alternatively the following loads the graph given and gives the user to a command line that can be used to send repeat queries to the graph:
```
python .\akg\query_graph.py -i d2025-08-26 clean_combined.nt
```
This is useful when working with large graphs that take a long time to load.

## Developer notes
* Work on the 'dev' branch, merge back into the main branch for stable versions
* tag the main branch
* Use issues to define work steps
* Include a reference to a commit when an issue is closed
