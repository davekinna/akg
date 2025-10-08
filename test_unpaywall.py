import requests
# unpaywall goes from doi to pdf
doi = "10.1016/j.neuron.2015.11.025"
#doi = "10.1016/j.cell.2015.06.034"  # Replace with your article's DOI
email = "user@domain.com"    # Optional but recommended
url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

response = requests.get(url)
if response.status_code == 200:
    data = response.json()
    oa_location = data.get("best_oa_location", {})
    pdf_url = oa_location.get("url_for_pdf")
    
    if pdf_url:
        print(f"PDF available at:{pdf_url}, trying:")
        response = requests.get(pdf_url, headers=headers)
        if response.status_code == 200:
            with open(f"foundit.pdf", "wb") as f:
                f.write(response.content)
                print(f"PDF downloaded successfully as foundit.pdf")
        else:
            print(f"Failed to download PDF. Status code: {response.status_code}")

    else:
        print("No open-access PDF found.")
else:
    print(f"Failed to access Unpaywall: {response.status_code}")

# other_url = "https://www.cell.com/neuron/fulltext/S0896-6273(15)01031-4?_returnURL=https%3A%2F%2Flinkinghub.elsevier.com%2Fretrieve%2Fpii%2FS0896627315010314%3Fshowall%3Dtrue#"
other_url = "https://www.cell.com/neuron/fulltext/S0896-6273(15)01031-4?_returnURL=https%3A%2F%2Flinkinghub.elsevier.com%2Fretrieve%2Fpii%2FS0896627315010314"

response = requests.get(other_url, headers=headers)
if response.status_code == 200:
    with open(f"foundit.pdf", "wb") as f:
        f.write(response.content)
        print(f"PDF downloaded successfully as foundit.pdf")
else:
    print(f"Failed to download PDF. Status code: {response.status_code}")

