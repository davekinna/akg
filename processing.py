#This file searches the Entrez database for relevant papers, retreives their DOIs metadata, obtains a pdf 
# of the original paper, and all supporting data xlsx files

# importing libraries
from Bio import Entrez
from metapub.convert import pmid2doi
import os
from bs4 import BeautifulSoup,  SoupStrainer
import requests
from urllib.request import urlopen, urlretrieve
import urllib.request, urllib.error, urllib.parse
import urllib.request
import pandas as pd
from functools import reduce
from metapub import PubMedFetcher
from selenium import webdriver
from urllib.parse import urljoin


def get_search_result():
    """Article search, returning PMIDs for articles matching terms relating to Autism and gene expression"""
    Entrez.email = input("Enter email address for NCBI Entrez: ")
    while '@' not in Entrez.email or '.' not in Entrez.email:
        print("Invalid email format. Try again.")
        Entrez.email = input("Enter email address for NCBI Entrez: ")
    handle = Entrez.esearch(db='pubmed',
                            term='((autism[title] or ASD[title]) AND brain AND transcriptomic AND expression AND rna NOT review[title] NOT Review[Publication Type])',
                            retmax='30',
                            sort='relevance',
                            retmode='xml')
    search_results = Entrez.read(handle)
    return search_results


def get_pmids(search_res) -> list[int]:
    """Stores a list of retrieved PMIDs"""
    initial_list = search_res["IdList"]
    print(len(initial_list))
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
    print(f"Found {len(doi_list)} DOIs out of {len(plist)} PMIDs")
    return valid_pmids, doi_list


def get_urls(plist: list[int])-> list[str]:
    """converts each DOI to a valid URL"""
    url_list = []
    for p in range(len(plist)):
        prefix = 'https://www.ncbi.nlm.nih.gov/pmc/articles/pmid/'
        new_url = prefix + plist[p]
        url_list.append(new_url)
    #print(url_list)
    return url_list


def get_tables(url, pmid) -> None:
    """retrieves supplementary files from the article"""
    main_dir = 'data'
    supp_output_dir = 'supp_data'
    new_dir = pmid
    new_path = os.path.join(main_dir, supp_output_dir, new_dir)
    # creates the directory if it doesn't exist
    os.makedirs(new_path, exist_ok=True)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as u:
            html = u.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return

    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all('a', href=True):
        href = link['href']
        if any(href.lower().endswith(x) for x in ['.csv', '.xls', '.xlsx', '.tsv', '.txt']):
            full_url = urljoin(url, href)
            filename = os.path.join(new_path, href.rsplit('/', 1)[-1])
            if os.path.isfile(filename):
                print(f"File '{filename}' already exists. Skipping file creation.")
            else:
                print(f"Downloading {full_url} to {filename}...")
                try:
                    urllib.request.urlretrieve(full_url, filename)
                    print("Done.")
                except Exception as e:
                    print(f"Error downloading {full_url}: {e}")
    
    if not os.listdir(new_path):
        print("No files were downloaded.")
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

    pdf_url = urljoin(url, pdf_url)
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

def get_metadata(plist: list[int], dlist: list[str]):
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

    # Export the merged DataFrame to a CSV file
    main_dir = 'data'
    file_path = os.path.join(main_dir, 'asd_article_metadata.csv')
    if os.path.isfile(file_path):
        print(f"File '{file_path}' already exists. Overwriting it.")
        df_merged.to_csv(file_path, index=False)
    else:
        df_merged.to_csv(file_path, index=False)
        print(f"File '{file_path}' created.")
    return None


def main():
    search_data = get_search_result()
    pmid_data = get_pmids(search_data)
    valid_pmids, doi_data = get_dois(pmid_data)
    get_metadata(valid_pmids, doi_data)
    url_data = get_urls(valid_pmids)
    for u in url_data:
        try:
            get_pdfs(u)
        except urllib.error.HTTPError:
            pass
    for u, p in zip(url_data, valid_pmids):
        try:
            get_tables(u, p)
        except urllib.error.HTTPError:
            pass
    print("All articles and data retrived")
    return 

#future additions - add a function to be used to pull only new data

if __name__ == "__main__":
    main()
