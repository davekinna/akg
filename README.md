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
python akg/data_convert.py --help
```
to identify the available options.  In the following examples many of the defaults have been used, and so the tracking file, for example, is given the name 'akg_tracking.xlsx'. If you change this at an early stage, subsequent steps must be supplied with the same value because they read from as well as write to the tracking file.

Steps in creating and using a graph are as follows:

1. find relevant articles:
```
python akg/processing.py -s -i <top_level>
```
This conducts a search for suitable articles, and saves information about them to <top_level>'asd_article_metadata.csv'.
It doesn't download them. Instead, you should review 'asd_article_metadata.csv' and exclude articles that you don't want to continue with, by marking the 'Exclude' column 'TRUE'.

The search performed is, by default:
```
'((autism[title] or ASD[title]) AND brain AND transcriptomic AND expression AND rna NOT review[title] NOT Review[Publication Type])'
```
you can supply an alternative with the '-t' command line option. 

3. retrieve article metadata, abstracts and the supplementary data files (tables of data) that will eventually form the graph:
```
python akg/processing.py -d -i <top_level>
```
This will scan asd_article_metadata.csv for the non-excluded files, and download supplementary data for them. The data files are output to <top_level>/supp_data.  The next level of directories under supp_data is named by the numeric pubmed ID value. 
So, the files are/should be downloaded to <top_level>/supp_data/\<PMID\>.

NOTE: simple direct download code no longer works because of (not unreasonable) bot protection on the server side. At the moment processing.py writes out a script (download.sh) that is run after processing.py, and sends messages to your live interactive browser session requesting that it visit the relevant page. To make this work, after running:
```
python akg/processing.py -d -i <top_level>
```
run the following (or equivalent for your system after fixing the path to the browser executable used in download.sh):
```
sh -v <top_level>/download.sh
```

Excluding downloaded data at this point based on PMID can be achieved by deleting it or moving it to a different location. The subsequent steps only work on files under the given top level directory.

As an alternative, to just go through the process for one publication, provide its PMID on the command line:
```
python akg/processing.py -p <pmid> -d -i <top_level>
```

4. Split the supplementary data files if necessary and generate derived data set files, one CSV file for each table of data. These are called split_*.csv.
```
python akg/data_split.py -i <top_level>
```
This will have created a file in the data directories, alongside the source data that was downloaded, called split_*tablename*.csv. It does this for *all files* in the supp_data/<pmid> directories, so delete or move any data that you don't want included at this point, or work in a new separate <top_level> directory if necessary.
These are now the working data files. data_split.py also will have created a tracking file called (by default) akg_tracking.xlsx, and a log file called data_split.log.

5. Inspection for suitability and column choice.
Use AI to suggest which of the derived dataset files are suitable for subsequent processing:
```
python akg/genai_check.py -i <top_level>
```
This needs to be run after data_split.py has been run. It looks for the derived dataset file names (with name split_*) and updates the value in column 'suitable' of the tracking file with TRUE if it judges the given file to be of further use, and puts its reasoning (whatever the outcome) in column 'suitablereason'.  
You will need a Google Gemini API key for this, in file .env in the python source directory.

If you judge that the AI check has been giving a good selection, you can use the -e argument to set the values in the 'excl' column to the same as those in the AI choice (see step 4 below):
```
python akg/genai_check.py -e -i <top_level>
```
genai_check.py also suggests which of the column names in the file are suitable for LFC, pvalue and gene name, and the number of lines to skip before you get to the column headers. Check these and modify if necessary.


6. Generate derived data set files, one for each table of data
```
python akg/data_convert.py -i <top_level>
```
These will have skipped the lines at the top of the file as instructed, and the essential data column names will be nominated if not already chosen.

The derived dataset files are named expdata_<filename>.csv, where <filename> is the data file that it came from. These are in the same directory as the datafile itself.

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

7. data cleaning
This implements a simple cleaning algorithm on the data. It outputs a file clean_expdata_<filename>.csv for each dataset.

```
python akg/csv_data_cleaning.py -i <top_level>
```

8. mapping to rdf triples
```
python akg/create_rdf_triples.py -f -i <top_level>
```
This generates a .nt 'triple' file for each data file that is not excluded. It also creates a JSON file mapping the row URIs to row labels that can be used for tracing and graphic output.
```
python akg/graph_cleanup.py -i <top_level> -n combined.nt -u clean_combined.nt
```
This takes the file <top_level>\graph\combined.nt, applies some cleaning criteria (currently putting the date and numerical quantities into a consistent format), and sends the output to <top_level>\graph\clean_combined.nt. This cleaning could be applied as part of the create_rdf_triples step: using a separate program allows a change in the reformatting to be applied without timeconsuming re-scanning of all the data files.

9. data testing and analysis
Example SparQL query files are in directory akg\query. These can be incorporated into python or Jupyter notebook files. Alternatively, the following utility will execute a SparQL query and write its output to another file, with logging and data in the usual locations, and input (-q) and output (-o) files relative to the data (-i) directory:
```
python akg/query_graph.py -i <top_level> -q hgnc.rq -u hgnc.csv clean_combined.nt
```
alternatively the following loads the graph given once, and gives the user a command line that can be used to send repeat queries to the graph:
```
python akg/query_graph.py -i <top_level> clean_combined.nt
```
This is useful when working with large graphs that take a long time to load.

## Developer notes
* Work on the 'dev' branch, merge back into the main branch for stable versions
* tag the main branch
* Use issues to define work steps
* Include a reference to a commit when an issue is closed
