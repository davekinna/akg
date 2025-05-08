import pandas as pd
import requests
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Setup
email = "dkinna01@student.bbk.ac.uk"
doi_file = "./data/asd_article_metadata.csv"
doi_column=5
output_folder = "supp_data_from_test"
log_file = "supplementary_download_log.csv"
os.makedirs(output_folder, exist_ok=True)

file_extensions = [".xlsx", ".xls", ".csv", ".tsv", ".txt"]

# Load DOIs
df = pd.read_csv(doi_file)
dois = df.iloc[:, (doi_column-1)].dropna().unique()

log_entries = []

for doi in dois:
    status = "Not attempted"
    files_downloaded = 0
    try:
        print(f"\n Processing DOI: {doi}")

        # Step 1: Query Unpaywall
        api_url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
        r = requests.get(api_url)
        if r.status_code != 200:
            status = "Unpaywall API failed"
            continue

        data = r.json()
        oa_location = data.get("best_oa_location") or data.get("first_oa_location")
        landing_page = oa_location.get("url") if oa_location else None
        if not landing_page:
            status = "No OA landing page"
            continue

        # Step 2: Scrape page
        headers = {"User-Agent": "Mozilla/5.0"}
        page = requests.get(landing_page, headers=headers, timeout=15)
        soup = BeautifulSoup(page.content, "html.parser")
        links = soup.find_all("a", href=True)

        for link in links:
            href = link['href']
            if any(href.lower().endswith(ext) for ext in file_extensions):
                file_url = urljoin(landing_page, href)
                filename = doi.replace("/", "_") + "_" + os.path.basename(href)
                filepath = os.path.join(output_folder, filename)

                try:
                    print(f"  Downloading: {file_url}")
                    file_data = requests.get(file_url, headers=headers)
                    with open(filepath, "wb") as f:
                        f.write(file_data.content)
                    files_downloaded += 1
                except Exception as e:
                    print(f"  Failed to download {file_url}: {e}")

        status = "Files downloaded" if files_downloaded > 0 else "No files found"

    except Exception as e:
        status = f"Error: {str(e)}"

    log_entries.append({
        "DOI": doi,
        "Landing Page": landing_page if 'landing_page' in locals() else None,
        "Files Downloaded": files_downloaded,
        "Status": status
    })

# Save summary log
log_df = pd.DataFrame(log_entries)
log_df.to_csv(log_file, index=False)
print(f"\n Summary written to {log_file}")
