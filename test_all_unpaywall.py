import pandas as pd
import requests
import os

# Load CSV
df = pd.read_csv("data/asd_article_metadata.csv")

email = "dkinna01@student.bbk.ac.uk"

# Extract DOIs from column 5 (index 4)
doi_list = df.iloc[:, 4].dropna().unique()

# Create folder for PDFs
os.makedirs("unpaywall_pdfs", exist_ok=True)

for doi in doi_list:
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
                filename = doi.replace("/", "_") + ".pdf"
                with open(os.path.join("unpaywall_pdfs", filename), "wb") as f:
                    f.write(pdf_response.content)
            else:
                print(f"  PDF fetch failed ({pdf_response.status_code})")
        else:
            print(f"No PDF found for: {doi}")

    except Exception as e:
        print(f"Error processing {doi}: {e}")
