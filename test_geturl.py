#This file searches the Entrez database for relevant papers, retrieves their DOIs metadata, obtains a pdf 
# of the original paper, and all supporting data xlsx files
# Linux adapted


from dotenv import load_dotenv
import os
# Load environment variables from .env file
load_dotenv()

from Bio import Entrez
# a suitable format for the line in the .env file is:
# ENTREZ_API_KEY="Your-API-Key-Here"
# include .env in .gitignore.

# set the API key immediately, from the environment
Entrez.api_key = os.getenv('ENTREZ_API_KEY')

if not Entrez.api_key:
    raise ValueError("API key not found. Please set it in the environment or your .env file.")

#import argparse
#import sys
#import time
#from bs4 import BeautifulSoup,  SoupStrainer
#import requests
from urllib.request import urlopen, urlretrieve
import urllib.request, urllib.error, urllib.parse
import urllib.request
#import pandas as pd
#from functools import reduce
#from metapub import PubMedFetcher
#from metapub.convert import pmid2doi
#from selenium import webdriver
from urllib.parse import urljoin
#from akg import AKGException, akg_logging_config
#import configparser



def get_tables(url:str, output_dir:str, pmid:str) -> None:
    """retrieves supplementary files from the article"""
    new_dir = pmid
    new_path = os.path.join(output_dir, new_dir)
    # creates the directory if it doesn't exist
    os.makedirs(new_path, exist_ok=True)
    logging.info(f"request returned {len(html)} bytes of data")
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
        logging.info(f"parser found a link with href: {href}")
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


import sys
from bs4 import BeautifulSoup,  SoupStrainer

def main():
    """
    Just test getting a URL
    """
    url = sys.argv[1]
    print('Test retrieving a URL')
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    print(f"requesting {url} ")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as u:
            html = u.read().decode('utf-8')
            content_url = u.url
            print(f"content_url:{content_url}")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        logging.error(f"HTTP Error {e.code}: {e.reason}")
        return

    print(f"full html content length: {len(html)} ")
    print("parsing...")
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all('a', href=True):
        href = link['href']
        print(href)



if __name__ == '__main__':
    main()
