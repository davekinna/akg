from selenium import webdriver
from selenium.webdriver.chrome.options import Options

#pmcid = "PMC4519016"
pmcid = "PMC10499611"
# pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
# pdf_url = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC10499611/pdf/41586_2023_Article_6473.pdf'
pdf_url = 'https://www.cell.com/article/S0896627315010314/pdf'
# Set up headless Chrome
options = Options()
options.add_argument('--headless')
options.add_argument('--disable-gpu')
driver = webdriver.Chrome(options=options)

# Navigate to the PDF URL
driver.get(pdf_url)

# Wait for challenge to complete (adjust time if needed)
import time
time.sleep(10)

# Get final redirected PDF URL if available
pdf_data = driver.page_source
with open(f"selenium_page.html", "w", encoding='utf-8') as f:
    f.write(pdf_data)

driver.quit()
