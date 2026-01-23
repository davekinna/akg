#This file searches the Entrez database for relevant papers, retrieves their DOIs metadata, obtains a pdf 
# of the original paper, and all supporting data xlsx files

from Bio import Entrez
from dotenv import load_dotenv


import os
import argparse
import sys
import logging
from bs4 import BeautifulSoup,  SoupStrainer
import requests
from urllib.request import urlopen, urlretrieve
import urllib.request, urllib.error, urllib.parse
import urllib.request
import pandas as pd
from functools import reduce
from metapub import PubMedFetcher
from metapub.convert import pmid2doi
from selenium import webdriver
from urllib.parse import urljoin
from akg import AKGException, akg_logging_config
import configparser

# Load environment variables from .env file
load_dotenv()
# a suitable format for the line in the .env file is:
# ENTREZ_API_KEY="Your-API-Key-Here"
# include .env in .gitignore.

# Get the API key from the environment
Entrez.api_key = os.getenv('ENTREZ_API_KEY')

if not Entrez.api_key:
    raise ValueError("API key not found. Please set it in your .env file.")


def get_search_result(query:str='', email:str='', count:int=30) -> dict:
    """Article search, returning PMIDs for articles matching terms relating to Autism and gene expression"""
    Entrez.email = email
    while '@' not in Entrez.email or '.' not in Entrez.email:
        logging.error("Invalid email format. Try again.")
        print("Invalid email format. Try again.")
        Entrez.email = input("Enter email address for NCBI Entrez: ")

    query = query if query else '((autism[title] or ASD[title]) AND brain AND transcriptomic AND expression AND rna NOT review[title] NOT Review[Publication Type])'

    handle = Entrez.esearch(db='pubmed',
                            term=query,
                            retmax=count,
                            sort='relevance',
                            retmode='xml')
    search_results = Entrez.read(handle)
    return search_results


def get_pmids(search_res) -> list[int]:
    """Stores a list of retrieved PMIDs"""
    initial_list = search_res["IdList"]
    logging.info(f"{len(initial_list)} pmids")
    return initial_list


def get_dois(plist: list[int]) -> tuple[list[int], list[str]]:

    """Converts each PMID to a DOI, returns valid PMIDs and new DOIs as separate lists"""
    doi_list = []
    valid_pmids = []
    for i in plist:
        try:
            doi_number = pmid2doi(i)
            if doi_number is not None:
                doi_list.append(doi_number)
                valid_pmids.append(i)
        except TypeError:
            continue
    logging.info(f"Found {len(doi_list)} DOIs out of {len(plist)} PMIDs")
    return valid_pmids, doi_list


def get_urls(plist: list[int])-> list[str]:
    """converts each pmid to a valid URL"""
    url_list = []
    for p in range(len(plist)):
        prefix = 'https://www.ncbi.nlm.nih.gov/pmc/articles/pmid/'
#                  https://www.ncbi.nlm.nih.gov/pmc/articles/PMC<PMC_ID>/pdf/

        new_url = prefix + plist[p]
        url_list.append(new_url)
    print(url_list)
    return url_list


def get_tables(url:str, output_dir:str, pmid:str) -> None:
    """retrieves supplementary files from the article"""
    new_dir = pmid
    new_path = os.path.join(output_dir, new_dir)
    # creates the directory if it doesn't exist
    os.makedirs(new_path, exist_ok=True)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as u:
            html = u.read().decode('utf-8')
            content_url = u.url
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return

    # keep track of links already found
    links = list()

    # to circumvent the bot protection, fire up a real browser
    # output_sh = os.path.join(output_dir, 'output.sh')
    # put this script to invoke in the directory above output_dir
    # which is the main data directory
    # find the full OS path of output_dir
    abs_output_dir = os.path.abspath(output_dir)
    # the directory we want is the one above that
    main_dir = os.path.dirname(abs_output_dir)

    output_sh = os.path.join(main_dir, 'download.sh')
    logging.info(f"Writing download script to {output_sh}: this sends download requests to Firefox")

    firefox_path = '"C:\\Program Files\\Mozilla Firefox\\firefox.exe"'

    # will need to write the download target location into the profile
    profiles = get_firefox_profiles() 
    # Find the default profile path
    default_path = next(info['path'] for info in profiles.values() if info['default'])

    # Write or overwrite user.js there
    #    user_js_path = os.path.join(default_path, "user.js")

    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all('a', href=True):
        href = link['href']
        if any(href.lower().endswith(x) for x in ['.csv', '.xls', '.xlsx', '.tsv', '.txt']):
            full_url = urljoin(content_url, href)
            # typically the content has two copies of the same link, handle this here
            if full_url not in links:
                links.append(full_url)
                local_filename = href.rsplit('/', 1)[-1]
                filename = os.path.join(new_path, local_filename)
                profile_filename = os.path.join('E:\\firefox_downloads', local_filename)

    # working with profiles not working yet, come back to this. In the meantime copy the file after downloading.
                # with open(user_js_path, "w", encoding="utf-8") as f:
                #     f.write('\n'.join([
                #         'user_pref("browser.download.folderList", 2);',
                #         r'user_pref("browser.download.dir", new_path);'
                #     ]))
                # print(f"Wrote user.js to {user_js_path}")

    # original version skipped the download if it was there already
                print(f"Downloading {full_url} to {filename}...")
                with open(output_sh,'a') as osh:
                    osh.write(firefox_path+ " "+ full_url)
                    osh.write('\n')
                    osh.write('sleep 5s\n')
                    osh.write('\n')
                    osh.write('cp "'+ profile_filename + '" "' + filename + '"')
                    osh.write('\n')

                # possibly reinstate this code as an option/backup 
                # switch to using requests instead of urllib, which was failing
                # try:
                #     response = requests.get(full_url, headers=headers)
                #     response.raise_for_status()
                #     with open(filename, 'wb') as fw:
                #         fw.write(response.content)
                # except requests.exceptions.RequestException as e:
                #     print(f"Error fetching the page: {e}")
                #     return None

    # if not os.listdir(new_path):
    #     print("No files were downloaded.")
    return


def get_pdfs(url):
    """retrieves associated pdf of the full article"""
    main_dir = 'data'
    art_output_dir = 'article_data'
    output_path = os.path.join(main_dir, art_output_dir)
    
    os.makedirs(output_path, exist_ok=True)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        # for reasons that I don't understand response.url is not the same as url used in the requests.get() call, 
        # and yet the fields indicating a redirect are False
        # if we get here, make use of the url set in the response
        content_url = response.url
        html = response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the page: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    # Look for PDF link in meta tags
    pdf_meta_tag = soup.find('meta', {'name': lambda name: name and 'pdf-link' in name.lower()})
    
    if pdf_meta_tag:
        pdf_url = pdf_meta_tag.get('content')
    else:
        # If not found in meta tags, look for PDF links in <a> tags
        pdf_link = soup.find('a', href=lambda href: href and href.lower().endswith('.pdf'))
        if pdf_link:
            pdf_url = pdf_link['href']
        else:
            print("No article PDF link found on the page.")
            return None

    pdf_url = urljoin(content_url, pdf_url)
    filename_part = pdf_url.split('=')[-1] if '=' in pdf_url else pdf_url.split('/')[-1]
    if not filename_part.lower().endswith('.pdf'):
        filename_part += '.pdf'
    filename = os.path.join(output_path, filename_part)

    if os.path.isfile(filename):
        print(f"File '{filename}' already exists. Skipping download.")
        return filename

    print(f"Downloading PDF from {pdf_url}")
    try:
        response = requests.get(pdf_url, headers=headers)
        response.raise_for_status()
        with open(filename, 'wb') as fw:
            fw.write(response.content)
        print(f"PDF downloaded and saved as '{filename}'")
        return filename
    except requests.exceptions.RequestException as e:
        print(f"Error downloading PDF: {e}")
        return None
# this is an example of a real link:  https://pmc.ncbi.nlm.nih.gov/articles/PMC10499611/pdf/41586_2023_Article_6473.pdf
# this is what we're currently creating: https://pmc.ncbi.nlm.nih.gov/pmc/articles/pmid/pdf/41586_2023_Article_6473.pdf
# don't know where the 10499611 is coming from at the moment (see content_url)

def get_upw(doi_list:list[str], valid_pmids: list[str], output_dir:str, email:str):
    """
    get_upw
    gets the PDFs for articles via unpaywall.org
    This site is searchable using the doi for a publication

    Parameters:
        doi_list: list of strings, one doi reference per entry
        output_dir: output directory for all pdfs
        email: valid email address 

    Returns:
        None
    """

    os.makedirs(output_dir, exist_ok=True)

    for doi,pmid in zip(doi_list, valid_pmids):
        try:
            url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
            r = requests.get(url)
            if r.status_code != 200:
                print(f"Failed: {doi} (status {r.status_code})")
                continue

            data = r.json()
            pdf_url = data.get("best_oa_location", {}).get("url_for_pdf")

            if pdf_url:
                print(f"Downloading: {doi} -> {pdf_url}")
                pdf_response = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
                if pdf_response.status_code == 200:
#                    filename = doi.replace("/", "_") + ".pdf"
                    filename = pmid + ".pdf"
                    with open(os.path.join(output_dir, filename), "wb") as f:
                        f.write(pdf_response.content)
                else:
                    print(f"  PDF fetch failed ({pdf_response.status_code})")
            else:
                print(f"No PDF found for: {doi}")

        except Exception as e:
            print(f"Error processing {doi}: {e}")


def get_metadata(plist: list[int], dlist: list[str], article_metadata_file:str):
    fetch = PubMedFetcher()
    articles = {}
    for pmid in plist:
        articles[pmid] = fetch.article_by_pmid(pmid)

    # Extract relevant information and create DataFrames
    titles = {}
    for pmid in plist:
        titles[pmid] = fetch.article_by_pmid(pmid).title
    Title = pd.DataFrame(list(titles.items()), columns=['pmid', 'title'])

    dates = {}
    for pmid in plist:
        dates[pmid] = fetch.article_by_pmid(pmid).year
    Date = pd.DataFrame(list(dates.items()), columns=['pmid', 'year'])

    journals = {}
    for pmid in plist:
        journals[pmid] = fetch.article_by_pmid(pmid).journal 
    Journal = pd.DataFrame(list(journals.items()), columns=['pmid', 'journal'])

    abstracts = {}
    for pmid in plist:
        abstracts[pmid] = fetch.article_by_pmid(pmid).abstract
    Abstract = pd.DataFrame(list(abstracts.items()), columns=['pmid', 'abstract'])

    Doi = pd.DataFrame({'pmid': plist, 'doi': dlist})

    # Merge all DataFrames into a single one
    data_frames = [Title, Date, Journal, Doi, Abstract]
    df_merged = reduce(lambda  left, right: pd.merge(left, right, on=['pmid'], how='outer'), data_frames)

    # add placeholders for the exclusion columns
    df_merged['exclude'] = False
    df_merged['exclude reason'] = ''

    # Export the merged DataFrame to a CSV file
    if os.path.isfile(article_metadata_file):
        logging.info(f"File '{article_metadata_file}' already exists. Overwriting it.")
        df_merged.to_csv(article_metadata_file, index=False)
    else:
        df_merged.to_csv(article_metadata_file, index=False)
        logging.info(f"File '{article_metadata_file}' created.")
    return None

def get_metadata_pmid(pmid:str, article_metadata_file:str):
    """
    Get the metadata for one pmid. Update the metadata file, but don't delete data from the other pmids.
    Parameters:
        pmid:str the pmid
        article_metadata_file:str the file
    Both must be supplied

    """
    fetch = PubMedFetcher()
    article = fetch.article_by_pmid(pmid)
    title   = fetch.article_by_pmid(pmid).title
    date    = fetch.article_by_pmid(pmid).year
    journal = fetch.article_by_pmid(pmid).journal
    abstract= fetch.article_by_pmid(pmid).abstract

    # Export the merged DataFrame to a CSV file
    if os.path.isfile(article_metadata_file):
        logging.info(f"File '{article_metadata_file}' already exists. Updating it.")
        df = pd.read_csv(article_metadata_file)
        # if the metadata for this pmid is already there, overwrite it without deleting the other entries
        if int(pmid) in df['pmid'].values:
            # get the row where pmid matches, and update the fields
            df.loc[df['pmid'] == int(pmid),'title'] = title
            df.loc[df['pmid'] == int(pmid),'year'] = int(date)
            df.loc[df['pmid'] == int(pmid),'journal'] = journal
            df.loc[df['pmid'] == int(pmid),'abstract'] = abstract
            df.loc[df['pmid'] == int(pmid),'doi'] = pmid2doi(pmid)
        else:
            # append a new entry
            new_entry = pd.DataFrame({'pmid': [pmid],
                                       'title': [title],
                                       'year': [int(date)],
                                       'journal': [journal],
                                       'doi': [pmid2doi(pmid)],
                                       'abstract': [abstract],
                                       'exclude': [False],
                                       'exclude reason': ['']})
            df = pd.concat([df, new_entry], ignore_index=True)
    else:
        # create a new file with just this one entry
        df = pd.DataFrame({'pmid': [pmid],
                           'title': [title],
                           'year': [int(date)],
                           'journal': [journal],
                           'abstract': [abstract],
                           'doi': [pmid2doi(pmid)],
                           'exclude': [False],
                           'exclude reason': ['']})
        logging.info(f"File '{article_metadata_file}' created.")

    df.to_csv(article_metadata_file, index=False)

    return None


def main():
    """
    Top-level function for AKG 'process'
    """
    command_line_str = ' '.join(sys.argv)

    # TODO: #8 connect search term and return count command line arguments to actions
    DEFAULT_SEARCH_TERM  = '((autism[title] or ASD[title]) AND brain AND transcriptomic AND expression AND rna NOT review[title] NOT Review[Publication Type])'
    DEFAULT_RETURN_COUNT = 30

    try:
        # manage the command line options
        parser = argparse.ArgumentParser(description='Download and initially process supplementary data')
        parser.add_argument('-t','--search-term', default=DEFAULT_SEARCH_TERM, help='default search term')
        parser.add_argument('-c','--count', default=DEFAULT_RETURN_COUNT, help="default number of search results to return")
        parser.add_argument('-i','--input_dir', default='data', help='Destination top-level directory for downloaded data files (input to graph)')
        parser.add_argument('-s','--search', action='store_true', help='Do the search')
        parser.add_argument('-f','--pdf', action='store_true', help="Download the articles as PDFs if available")
        parser.add_argument('-p','--pmid', default='', help="Operate only for this PMID")
        parser.add_argument('-d','--download', action='store_true', help="Download the supplementary data if available")
        parser.add_argument('-e','--email', help='email address to supply to NCBI and Unpaywall',default='')
        parser.add_argument('-l','--log', default='processing.log', help='Log file name. This file is created in the top-level directory')

        # argparse populates an object using parse_args
        # extract its members into a dict and from there into variables if used in more than one place
        config = vars(parser.parse_args())

        main_dir = config['input_dir']
        os.makedirs(main_dir, exist_ok=True)

        if not os.path.isdir(main_dir):
            raise AKGException(f"processing.py: data directory '{main_dir}' could not be created")

        akg_logging_config( os.path.join(main_dir, config['log']))
        logging.info(f"Program executed with command: {command_line_str}")
        
        if config['download']:
            logging.info('Download supplementary data option')

        article_metadata_file = os.path.join(main_dir, "asd_article_metadata.csv")

        pmid = config['pmid']
        pmid_only = (pmid != '')

        # choose the 'search' option (-s) to force the search to be done
        if config['search']:
            logging.info("Search option chosen")
            if pmid_only:
                logging.info(f"Getting metadata for one PMID: {pmid}")
                get_metadata_pmid(pmid, article_metadata_file)
            else:
                logging.info("Getting metadata for all PMIDs from search")
                # get_search_result has the predefined search term, and prompts on the console for the user email address
                search_data = get_search_result(config['search_term'], config['email'], int(config['count']))
                # get_pmids just extracts the pmids from the structure returned
                pmid_data = get_pmids(search_data)
                # get_dois uses Entrez to extract the associated doi resource names and is working
                valid_pmids, doi_data = get_dois(pmid_data)
                # get_metadata is working fine. It retrieves a lot of metadata separately into DataFrames, 
                # then merges this into a master DataFrame and saves it as a csv file
                get_metadata(valid_pmids, doi_data, article_metadata_file)
        else:
            if not os.path.exists(article_metadata_file):
                error_message = '-s option not chosen and no metadata file exists'
                logging.error(error_message)
                raise AKGException(error_message)

        # this is a change of process: always read back the valid_pmids and doi_data from the file so we can skip the search 
        # and metadata retrieval if it's already been done
        # Load CSV
        df = pd.read_csv(article_metadata_file)

        # only work on the entries that haven't been excluded
        df = df[~df['exclude']]

        # further exclude if we're doing pmid only
        if pmid_only:
            df = df[df['pmid'] == int(pmid)]
            if df.empty:
                raise AKGException(f"PMID {pmid} not found in metadata file or it has been excluded")

        # Extract DOIs and PMIDs
        doi_data = df['doi'].tolist()
        valid_pmids = [str(i) for i in df['pmid'].tolist()]

        url_data = get_urls(valid_pmids)
        if config['pdf']:
            logging.info("PDF download option chosen")
            email  = config['email']
            art_output_dir = 'article_data'
            pdf_output_path = os.path.join(main_dir, art_output_dir)
            # get the PDFs
            get_upw(doi_data, valid_pmids, pdf_output_path, email=email)

        if config['download']:
            print('Download supplementary data option')
            print('Working directory: '+os.getcwd())
            supp_output_dir = 'supp_data'
            table_output_path = os.path.join(main_dir, supp_output_dir)
            for u, p in zip(url_data, valid_pmids):
                try:
                    get_tables(u, table_output_path, p)
                except urllib.error.HTTPError:
                    pass
            print("All articles and data retrieved")
        return 
    except AKGException as e:
        print(e)
        sys.exit(0)

# chatgpt code to find firefox path
def get_firefox_profiles():
    # Determine the path to profiles.ini based on OS
    if sys.platform.startswith('win'):
        ini_path = os.path.join(os.environ['APPDATA'], 'Mozilla', 'Firefox', 'profiles.ini')
    elif sys.platform == 'darwin':
        ini_path = os.path.expanduser('~/Library/Application Support/Firefox/profiles.ini')
    else:  # Linux and other Unices
        ini_path = os.path.expanduser('~/.mozilla/firefox/profiles.ini')

    if not os.path.exists(ini_path):
        raise FileNotFoundError(f"Couldn't find profiles.ini at {ini_path!r}")

    # Parse the INI
    config = configparser.ConfigParser()
    config.read(ini_path)

    base_dir = os.path.dirname(ini_path)
    profiles = {}
    for section in config.sections():
        if not section.startswith('Profile'):
            continue

        name       = config[section].get('Name')
        path       = config[section]['Path']
        is_rel     = config[section].getboolean('IsRelative', fallback=True)
        default    = config[section].getboolean('Default', fallback=False)

        # Resolve full path
        full_path = os.path.join(base_dir, path) if is_rel else path
        profiles[name] = {
            'path': os.path.abspath(full_path),
            'default': default
        }

    return profiles

if __name__ == "__main__":
    profiles = get_firefox_profiles()
    for name, info in profiles.items():
        mark = "(default)" if info['default'] else ""
        print(f"{name:20s} {info['path']} {mark}")

    main()
