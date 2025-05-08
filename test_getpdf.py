import requests

pmcid = "PMC4519016"
pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
# response = requests.get(pdf_url, headers=headers)
# if response.status_code == 200:
#     with open(f"{pmcid}.pdf", "wb") as f:
#         f.write(response.content)
#     print(f"PDF downloaded successfully as {pmcid}.pdf")
# else:
#     print(f"Failed to download PDF. Status code: {response.status_code}")
xlsx_url = 'https://pmc.ncbi.nlm.nih.gov/articles/instance/4519016/bin/NIHMS705244-supplement-2.xlsx'
#xlsx_url = 'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4519016/bin/NIHMS705244-supplement-2.xlsx'
response = requests.get(xlsx_url, headers=headers)
if response.status_code == 200:
    with open(f"supp-2.xlsx", "wb") as f:
        f.write(response.content)
    print(f"file downloaded successfully as supp-2.xlsx")
else:
    print(f"Failed to download xlsx. Status code: {response.status_code}")
