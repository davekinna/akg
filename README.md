# akg
The Birkbeck ASD Knowledge Graph

"A central information hub of gene expression data from primary research articles, focussed on Autism, specifically utilising data from supporting information accompanying the publications" (T Hill, 2024).

## Aims
* Build on the work of https://github.com/tamjhill/ASDProject

## Installation
A fully automated installation is not yet in place (see https://github.com/davekinna/akg/issues/34). To check out the code with command line git:
```
git clone https://github.com/davekinna/akg.git
```
This will create a subdirectory 'akg' with the python scripts in. This is the "project root". 
The most recent code version is on the linux branch - so to see this in your environment:
```
cd akg
git checkout linux
```

### Linux quick setup
From the project root, run:
```
module load python/v3.11
bash setup_linux.sh
```
The linux version of the project includes:
* requirements.txt (Python dependencies used by scripts/tests)
* setup_linux.sh (creates/uses .venv and installs dependencies)

By default, the virtual environment is created at .venv inside the project root. To use a different location, set VENV_DIR when running setup:
```
VENV_DIR=/path/to/venvs/akg bash setup_linux.sh
```

To actually start the virtual environment from the project root, run:
```
source .venv/bin/activate.csh

## the bash/zsh equivalent is also available:
# source .venv/bin/activate
# if you chose a non-default location for the venv, use that instead:
# source /path/to/venvs/akg/bin/activate.csh

```

Then return to the parent directory (cd ..), the examples below do this to avoid mixing code and data.


## Workflow for using the code
This section is an outline of the project and available code.  I assume here you are running from the directory level above the source code (which is in directory akg).

All code files named below have a command line interface that give some control of configuration. Type, for example:
```
python akg\data_convert.py --help
```
to run the code and identify the available options.  In the following examples many of the defaults have been used, and so the tracking file, for example, is given the name 'akg_tracking.xlsx'. If you change this at an early stage, subsequent steps must be supplied with the same value because they read from as well as write to the tracking file.

Steps in creating and using a graph are as follows:

0. Create a working directory for your downloaded data, derived data and graph files. In the examples I've named my working directories with the date, for example, 'd2025-08-12'. I refer to this here as <top_level>  
0.1 update akg/.env with your API key from NCBI/Entrez

1. finding relevant articles
```
python akg\processing.py -i <top_level> -s -e <your-entrez-email>
```
First time around, consider using '-c 1' to stop the search after one hit!

The default query is: 
```
((autism[title] or ASD[title]) AND brain AND transcriptomic AND expression AND rna NOT review[title] NOT Review[Publication Type])
```
... use the -t option to supply an alternative

2. retrieving article metadata, abstracts and supplementary data files
```
python akg\processing.py -i <top_level> -s -d
```

The data files are output to <top_level>/supp_data.  The next level of directories under supp_data is named by the numeric pubmed ID value. 
So, the files are/should be downloaded to <top_level>/supp_data/\<PMID\>.

If they are not downloaded, look in processing.log, which will show you the publication locations as web addresses. Visit these with your browser, download the supplementary files, and put them into <top_level>/supp_data/\<PMID\> with their current filenames.

Excluding downloaded data at this point based on PMID can be achieved by deleting it or moving it to a different location. The subsequent steps only work on files under the given top level directory.

4. Split the supplementary data files if necessary and generate derived data set files, one CSV file for each table of data. These are called split_*.csv.
```
python akg\data_split.py -i <top_level>
```
This will have created a file in the data directories, alongside the source data that was downloaded, called split_*tablename*.csv.
These are now the working data files. data_split.py also will have created the first version of the tracking file called (by default) akg_tracking.xlsx, and a log file called data_split.log.

5. check each supplementary data file for relevant expression info and generate derived data set files, one for each table of data 
```
python akg\data_convert.py -i <top_level>
```
The derived dataset files are named expdata_<filename>.csv, where <filename> is the data file that it came from. These are in the same directory as the datafile itself.

5.1. Use AI to suggest which of the derived dataset files are suitable for subsequent processing.
    - genai_check.py

Use this as follows:
```
python akg\genai_check.py -i <top_level>
```
This needs to be run after data_convert.py has been run. It looks for the derived dataset file names (with name expdata_*) and updates the value in column 'suitable' with TRUE if it judges the given file to be of further use, and puts its reasoning (whatever the outcome) in column 'suitablereason'.  If you judge that the AI check has been giving a good selection, use the -e argument to set the values in the 'excl' column to the same as those in the AI choice (see step 4 below):
```
python akg\genai_check.py -e -i <top_level>
```

5.2. Inspection and manual exclusion of data. 
The derived dataset file lines in akg_tracking.xlsx include the name of the data file they were generated from.

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
This implements a simple cleaning algorithm on the data. It outputs a file clean_expdata_<filename>.csv for each dataset.

Use this as follows:
```
python akg\csv_data_cleaning.py -i <top_level>
```

7. mapping to rdf triples
    - create_rdf_triples.py
   This generates the graph triples from the clean csv files. Currently implemented is the per-file option, which generates a .nt file for each csv file:
```
python akg\create_rdf_triples.py -f -i <top_level>
```

8. Combine graphs:
I recommend first combining the triple files for each PMID. The following does this for 31097668, with output to file <top_level>/graph/combined_31097668.nt
```
python akg\combine_graphs.py -i <top_level> -p 31097668
```
You should then be able to combine these further with, for example
```
python akg\combine_graphs.py -i <top_level>  -o bigger_graph.nt graph/combined_31097668.nt graph/combined_31097668.nt
```

9. Cleanup graph
Ensures any values are given correct datatype (double or data), and that any blank values are removed.

```
python akg\graph_cleanup.py -i <top_level> -n bigger_graph.nt -u clean_combined.nt
```

## Developer notes
* Work on the 'dev' branch, merge back into the main branch for stable versions
* tag the main branch
* Use issues to define work steps
* Include a reference to a commit when an issue is closed
