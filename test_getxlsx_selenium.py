import os
import time
import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from urllib.parse import urljoin

# Setup
email = "user@domain.com"
csv_file = "./data/asd_article_metadata.csv"
output_folder = "supp_data_sel"
log_file = "supplementary_download_log_sel.csv"
os.makedirs(output_folder, exist_ok=True)
download_dir = os.path.abspath("supplementary_data_sel")
os.makedirs(download_dir, exist_ok=True)

file_extensions = [".xlsx", ".xls", ".csv", ".tsv", ".txt"]

# Chrome options to allow automatic downloads
chrome_options = Options()
chrome_options.add_argument("--headless=new")  # "new" is required in latest versions
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
})
driver = webdriver.Chrome(options=chrome_options)

# Load DOIs
df = pd.read_csv(csv_file)
dois = df.iloc[:, 4].dropna().unique()

log_entries = []

for doi in dois:
    status = "Not attempted"
    files_downloaded = 0
    landing_page = None

    try:
        print(f"\n📌 Processing DOI: {doi}")

        # Step 1: Get landing page from Unpaywall
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

        # Step 2: Visit page and click on file links
        driver.get(landing_page)
        time.sleep(10)  # Allow page + JS to load

        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href")
            if href and any(href.lower().endswith(ext) for ext in file_extensions):
                try:
                    print(f"⬇️ Clicking to download: {href}")
                    driver.execute_script("arguments[0].click();", link)
                    files_downloaded += 1
                except Exception as e:
                    print(f"  ❌ Click/download failed: {e}")

        # Wait for files to appear in download dir (simple delay)
        time.sleep(5)

        status = "Files downloaded" if files_downloaded else "No files found"

    except Exception as e:
        status = f"Error: {str(e)}"

    log_entries.append({
        "DOI": doi,
        "Landing Page": landing_page,
        "Files Downloaded": files_downloaded,
        "Status": status
    })

driver.quit()

# Save log
log_df = pd.DataFrame(log_entries)
log_df.to_csv(log_file, index=False)
print(f"\n📝 Summary saved to {log_file}")
