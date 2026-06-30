"""
pmc_downloader.py
-----------------
Downloads supplementary files for a PubMed article using the NCBI OA API,
with a Playwright-based fallback for cases where the OA tarball is unavailable.

Usage:
    python pmc_downloader.py <PMID> <output_dir>

Example:
    python pmc_downloader.py 33277541 ./supplements

Public API:
    download_supplements(pmid: str, output_dir: str | Path, use_fallback: bool = True) -> DownloadResult

Optional Fallback Feature (Requires GUI):
    For cases where the OA tarball is unavailable, this script can open a visible
    browser to scrape supplement links directly from the PMC article page.
    User interaction may be required to complete bot verification.
    
    Installation:
        pip install playwright
        playwright install chromium
    
    Note: Requires X11/Wayland on Linux or native GUI on Windows/macOS.
"""

from __future__ import annotations

import logging
import tarfile
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    HAS_PLAYWRIGHT = True
    _PLAYWRIGHT_IMPORT_MSG = "[OK] Playwright available"
except ImportError as e:
    HAS_PLAYWRIGHT = False
    PlaywrightTimeoutError = None
    _PLAYWRIGHT_IMPORT_MSG = f"[X] Playwright not available: {e}"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OA_API_BASE = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"

# Filename fragments that indicate a file is supplementary material rather
# than the main manuscript body.
SUPPLEMENT_INDICATORS = (
    "supp", "supplement", "supplemental",
    "additional", "s1", "s2", "s3", "s4", "s5",
    "table_s", "figure_s", "data_s",
)

HEADERS = {"User-Agent": "pmc_downloader/1.0 (research tool; please contact user)"}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ArticleIdentifiers:
    """Holds the PMID and the resolved PMCID for an article."""
    pmid: str
    pmcid: str  # always in 'PMC1234567' form


@dataclass
class ArticlePackage:
    """Represents the OA tarball package for an article."""
    pmcid: str
    tar_url: str          # HTTPS URL to the .tar.gz
    file_list: list[str] = field(default_factory=list)  # populated after inspection


@dataclass
class DownloadResult:
    """Summary of a completed (or failed) download operation."""
    pmid: str
    pmcid: str
    output_dir: Path
    downloaded_files: list[Path] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.downloaded_files)

    def __str__(self) -> str:
        if not self.success:
            return f"DownloadResult(FAILED pmid={self.pmid}, error={self.error!r})"
        names = [f.name for f in self.downloaded_files]
        return (
            f"DownloadResult(pmid={self.pmid}, pmcid={self.pmcid}, "
            f"files={names})"
        )


# ---------------------------------------------------------------------------
# Step 1 – resolve PMID → PMCID
# ---------------------------------------------------------------------------

def resolve_pmcid(pmid: str, session: requests.Session) -> ArticleIdentifiers:
    """
    Convert a PMID to a PMCID using the eutils id-converter.

    Raises:
        ValueError: if no PMCID is found for the given PMID.
        requests.HTTPError: on network/HTTP failure.
    """
    url = f"{EUTILS_BASE}/elink.fcgi"
    params = {
        "dbfrom": "pubmed",
        "db": "pmc",
        "id": pmid,
        "retmode": "xml",
    }
    resp = session.get(url, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    # <LinkSetDb><LinkName>pubmed_pmc</LinkName><Link><Id>…</Id></Link></LinkSetDb>
    ids = [
        el.text
        for el in root.findall(".//LinkSetDb[LinkName='pubmed_pmc']/Link/Id")
        if el.text
    ]
    if not ids:
        raise ValueError(
            f"No PMC record found for PMID {pmid}. "
            "The article may not be open-access or may not be in PMC."
        )

    pmcid = f"PMC{ids[0]}"
    return ArticleIdentifiers(pmid=pmid, pmcid=pmcid)


# ---------------------------------------------------------------------------
# Step 2 – look up the OA package URL
# ---------------------------------------------------------------------------

def fetch_oa_package(identifiers: ArticleIdentifiers, session: requests.Session) -> ArticlePackage:
    """
    Query the NCBI OA API to get the HTTPS URL for the article tar.gz.

    Raises:
        ValueError: if no HTTPS link is available (e.g. embargoed article).
        requests.HTTPError: on network/HTTP failure.
    """
    params = {"id": identifiers.pmcid}
    resp = session.get(OA_API_BASE, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)

    # Check for an error element first
    error_el = root.find(".//error")
    if error_el is not None:
        raise ValueError(
            f"OA API error for {identifiers.pmcid}: {error_el.text}"
        )

    # Prefer the HTTPS link; fall back to FTP
    https_link = root.find(".//link[@format='tgz'][@href]")
    if https_link is None:
        # Try any link with .tar.gz in the href
        for link in root.findall(".//link"):
            href = link.get("href", "")
            if href.endswith(".tar.gz"):
                https_link = link
                break

    if https_link is None:
        raise ValueError(
            f"No downloadable package found for {identifiers.pmcid}. "
            "The article may be under an access restriction."
        )

    tar_url = https_link.get("href")
    # Convert FTP to HTTPS if needed
    if tar_url.startswith("ftp://"):
        tar_url = "https://" + tar_url[6:]

    return ArticlePackage(pmcid=identifiers.pmcid, tar_url=tar_url)


# ---------------------------------------------------------------------------
# Step 3 – identify supplementary files inside the tarball
# ---------------------------------------------------------------------------

def _is_supplement(name: str) -> bool:
    """Heuristic: is this tarball member likely a supplementary file?"""
    lower = name.lower()
    # Skip directories
    if lower.endswith("/"):
        return False
    # Skip the main manuscript XML/HTML and PDF
    if lower.endswith(".nxml") or lower.endswith(".xml"):
        return False
    # Anything whose filename contains a supplement indicator is included
    stem = Path(lower).stem
    if any(ind in stem for ind in SUPPLEMENT_INDICATORS):
        return True
    # Also include common data file types that are unlikely to be the manuscript
    data_extensions = {".xlsx", ".csv", ".tsv", ".zip", ".gz", ".rdata",
                       ".rds", ".mat", ".h5", ".hdf5", ".txt", ".docx"}
    if Path(lower).suffix in data_extensions:
        return True
    return False


def inspect_package(package: ArticlePackage, session: requests.Session) -> ArticlePackage:
    """
    Stream just enough of the tarball to list its members, then record
    which ones look like supplementary files.

    Returns the same package object with `file_list` populated.
    """
    resp = session.get(package.tar_url, stream=True, timeout=60)
    resp.raise_for_status()

    members: list[str] = []
    with tarfile.open(fileobj=resp.raw, mode="r|gz") as tf:
        for member in tf:
            members.append(member.name)

    package.file_list = [m for m in members if _is_supplement(m)]
    return package


# ---------------------------------------------------------------------------
# Step 4 – download and extract identified supplementary files
# ---------------------------------------------------------------------------

def extract_supplements(
    package: ArticlePackage,
    output_dir: Path,
    session: requests.Session,
) -> tuple[list[Path], list[str]]:
    """
    Re-download the tarball and extract only the supplementary files into
    output_dir.

    Returns:
        (downloaded_files, skipped_files) where skipped_files are members
        that matched the supplement list but could not be extracted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    supplement_set = set(package.file_list)

    downloaded: list[Path] = []
    skipped: list[str] = []

    resp = session.get(package.tar_url, stream=True, timeout=120)
    resp.raise_for_status()

    with tarfile.open(fileobj=resp.raw, mode="r|gz") as tf:
        for member in tf:
            if member.name not in supplement_set:
                continue
            # Flatten path: write directly into output_dir regardless of
            # subdirectory structure inside the tarball.
            dest_name = Path(member.name).name
            dest_path = output_dir / dest_name

            try:
                f = tf.extractfile(member)
                if f is None:
                    skipped.append(member.name)
                    continue
                dest_path.write_bytes(f.read())
                downloaded.append(dest_path)
            except Exception as exc:
                skipped.append(f"{member.name} ({exc})")

    return downloaded, skipped


# ---------------------------------------------------------------------------
# Step 4b – fallback: scrape supplements directly from article page
# ---------------------------------------------------------------------------

def scrape_supplements_with_playwright(
    pmcid: str,
    output_dir: Path,
    session: requests.Session,
) -> tuple[list[Path], list[str]]:
    """
    Fallback method: open a visible Playwright browser to navigate to the PMC
    article page and scrape direct links to supplementary files.
    
    This allows the user to interact with bot-check dialogs or similar
    verification challenges on the page.

    Returns:
        (downloaded_files, skipped_files)
    """
    if not HAS_PLAYWRIGHT:
        raise ImportError(
            "Playwright is required for the fallback scraper. "
            "Install it with: pip install playwright"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    article_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"

    downloaded: list[Path] = []
    skipped: list[str] = []

    logging.info("[Fallback] Opening article page in visible browser: %s", article_url)
    logging.info("[Fallback] Browser window will open. If you see a bot check, please complete it.")
    logging.info("[Fallback] Once the page is fully loaded, press ENTER in this terminal to continue.")

    with sync_playwright() as p:
        # Launch with headless=False to show the browser window
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            # Navigate to the article page with longer timeout for bot checks
            page.goto(article_url, wait_until="load", timeout=120000)

            # Wait longer for any dynamic content and bot checks to complete
            page.wait_for_timeout(3000)

            # Prompt user in the console (not via logging) before scraping.
            input("[Waiting] Press ENTER when you've completed any bot checks and the page is ready: ")

            # After user confirms, wait a bit more for any post-verification content
            page.wait_for_timeout(2000)

            logging.info("[Fallback] Scanning page for supplementary file links...")

            # Extract all links from the page
            all_links = page.locator("a").all()
            supplement_links: dict[str, str] = {}  # text -> url

            def normalize_supp_url(raw_url: str) -> str:
                """Normalize known PMC supplement URL patterns to stable /pmc/articles/PMC.../bin/... links."""
                parsed = urlparse(raw_url)
                path = parsed.path

                # /articles/instance/<id>/bin/<file> -> /pmc/articles/PMC<id>/bin/<file>
                path = re.sub(
                    r"^/articles/instance/(\d+)/bin/",
                    lambda m: f"/pmc/articles/PMC{m.group(1)}/bin/",
                    path,
                )

                # /articles/<id>/bin/<file> -> /pmc/articles/PMC<id>/bin/<file>
                path = re.sub(
                    r"^/articles/(\d+)/bin/",
                    lambda m: f"/pmc/articles/PMC{m.group(1)}/bin/",
                    path,
                )

                # Last-resort: if still /articles/instance/ and includes /bin/, force to current PMCID.
                if "/articles/instance/" in path and "/bin/" in path:
                    bin_tail = path.split("/bin/", 1)[1]
                    path = f"/pmc/articles/{pmcid}/bin/{bin_tail}"

                return parsed._replace(path=path).geturl()

            for elem in all_links:
                href = elem.get_attribute("href")
                text_content = elem.text_content()
                text = text_content.strip() if text_content else ""
                
                if not href or not text:
                    continue
                
                # Skip navigation/non-supplement links
                skip_phrases = {
                    "google scholar",
                    "help",
                    "sign in",
                    "contact",
                    "about ncbi",
                    "copyright",
                    "disclaimer",
                    "home",
                    "accessibility",
                    "terms",
                    "cookie",
                    "ncbi",
                }
                
                if any(skip in text.lower() for skip in skip_phrases):
                    continue
                
                # Skip hash/anchor links
                if href.startswith("#"):
                    continue

                # Make absolute URL if relative
                abs_url = urljoin(article_url, href)
                parsed_abs = urlparse(abs_url)
                url_l = abs_url.lower()
                text_l = text.lower()

                # Skip obvious external noise links.
                if any(noisy in parsed_abs.netloc.lower() for noisy in ["google.com", "scholar.google", "x.com", "twitter.com"]):
                    continue

                # Skip known non-download patterns.
                if "open in a new tab" in text_l or "/figure/" in parsed_abs.path.lower():
                    continue

                # Skip the main article PDF entry; we only want supplements/datasets here.
                if "/pdf/" in parsed_abs.path.lower() and "supp" not in text_l:
                    continue

                # Skip PDF supplement links in fallback mode (user only wants data files).
                if parsed_abs.path.lower().endswith(".pdf"):
                    continue
                
                # Prefer true supplement/download links.
                has_file_ext = any(url_l.endswith(ext) for ext in [
                    ".xlsx", ".xls", ".csv", ".tsv", ".zip", ".gz", ".tar",
                    ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg", ".gif"
                ])
                
                has_supp_keyword = any(keyword in url_l or keyword in text_l 
                                      for keyword in ["supp", "supplement", "additional", "moesm", "data", "fig", "table"])

                has_bin_path = "/bin/" in parsed_abs.path.lower()
                is_ncbi_host = parsed_abs.netloc in {"www.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov"}
                
                # Accept either:
                # - NCBI bin links (normalized), or
                # - external direct file/supplement links from publisher domains.
                if (is_ncbi_host and (has_file_ext or (has_supp_keyword and has_bin_path) or has_bin_path)) or (
                    not is_ncbi_host and (has_file_ext or has_supp_keyword)
                ):
                    if is_ncbi_host:
                        abs_url = normalize_supp_url(abs_url)
                    # Use cleaned text as key
                    clean_text = " ".join(text.split())[:80]  # Normalize whitespace
                    if clean_text and clean_text not in supplement_links:
                        supplement_links[clean_text] = abs_url

            if not supplement_links:
                raise ValueError("No supplementary file links found on the article page.")

            logging.info("[Fallback] Found %d supplement link(s):", len(supplement_links))
            for text, url in supplement_links.items():
                logging.info("  - %s -> %s...", text[:60], url[:60])

            def build_candidate_urls(primary_url: str) -> list[str]:
                """Generate host/path variants for supplement download retries."""
                candidates: list[str] = []

                def add(u: str) -> None:
                    if u and u not in candidates:
                        candidates.append(u)

                add(primary_url)
                add(normalize_supp_url(primary_url))

                parsed = urlparse(primary_url)
                path = parsed.path
                article_id = pmcid.removeprefix("PMC")
                bin_tail = path.split("/bin/", 1)[1] if "/bin/" in path else ""

                # Try both NCBI hosts because redirect behavior differs by environment.
                for host in ("www.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov"):
                    add(parsed._replace(netloc=host).geturl())
                    add(urlparse(normalize_supp_url(parsed._replace(netloc=host).geturl())).geturl())

                # Force explicit path variants when /bin/ filename exists.
                if bin_tail:
                    for host in ("www.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov"):
                        # /pmc/articles/PMC.../bin/... form
                        add(f"https://{host}/pmc/articles/{pmcid}/bin/{bin_tail}")
                        # /articles/PMC.../bin/... form
                        add(f"https://{host}/articles/{pmcid}/bin/{bin_tail}")
                        # /articles/<id>/bin/... form
                        add(f"https://{host}/articles/{article_id}/bin/{bin_tail}")
                        # /articles/instance/<id>/bin/... form
                        add(f"https://{host}/articles/instance/{article_id}/bin/{bin_tail}")

                return candidates

            # Download each supplement
            for text, url in supplement_links.items():
                try:
                    content: bytes | None = None
                    final_url = url
                    last_error: Exception | None = None
                    candidate_urls = build_candidate_urls(url)
                    logging.debug("[Fallback] Trying %d candidate URL(s) for: %s", len(candidate_urls), text)

                    # First pass: requests session.
                    for idx, candidate in enumerate(candidate_urls):
                        if idx > 0:
                            logging.debug("[Fallback] Retry with alternative: %s...", candidate[:60])
                        try:
                            resp = session.get(candidate, timeout=60)
                            if 200 <= resp.status_code < 300 and resp.content:
                                content = resp.content
                                final_url = str(resp.url)
                                break
                            last_error = requests.HTTPError(
                                f"HTTP {resp.status_code} for {candidate}"
                            )
                        except Exception as req_exc:
                            last_error = req_exc

                    # Second pass: browser-context request (shares bot-check/browser state).
                    if content is None:
                        for idx, candidate in enumerate(candidate_urls):
                            if idx == 0:
                                logging.debug("[Fallback] Trying browser-session download...")
                            try:
                                pw_resp = page.context.request.get(
                                    candidate,
                                    timeout=60000,
                                    fail_on_status_code=False,
                                    headers={"referer": article_url},
                                )
                                if pw_resp.ok:
                                    body = pw_resp.body()
                                    if body:
                                        content = body
                                        final_url = pw_resp.url
                                        break
                                last_error = requests.HTTPError(
                                    f"HTTP {pw_resp.status} for {candidate} (browser session)"
                                )
                            except Exception as pw_exc:
                                last_error = pw_exc

                    if content is None:
                        raise last_error or RuntimeError(f"Unable to download supplement: {url}")

                    # Extract filename from URL or use text
                    parsed = urlparse(final_url)  # Use final URL after redirects
                    filename = Path(parsed.path).name
                    
                    if not filename or filename.endswith("/"):
                        # Fallback to sanitized text with extension from URL
                        ext = ""
                        if "." in parsed.path:
                            ext = "." + parsed.path.rsplit(".", 1)[-1]
                        # Sanitize text for filename
                        text_clean = "".join(c if c.isalnum() or c in "._- " else "_" for c in text)
                        text_clean = "_".join(text_clean.split())[:80]  # Remove extra spaces
                        filename = text_clean + ext if ext else text_clean

                    dest_path = output_dir / filename
                    dest_path.write_bytes(content)
                    downloaded.append(dest_path)
                    logging.info("[Fallback] Downloaded: %s", filename)
                    print(f"[Fallback] Downloaded: {filename}")

                except Exception as exc:
                    skipped.append(f"{text} ({exc})")
                    logging.warning("[Fallback] Failed: %s: %s", text, exc)

            summary_msg = f"[Fallback] Downloads completed: {len(downloaded)} file(s)."
            logging.info(summary_msg)
            print(summary_msg)

        finally:
            browser.close()

    return downloaded, skipped


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def download_supplements(pmid: str | int, output_dir: str | Path, use_fallback: bool = True) -> DownloadResult:
    """
    Download supplementary files for a PubMed article into output_dir.

    Args:
        pmid:          PubMed ID (integer or string).
        output_dir:    Directory to save files into (created if absent).
        use_fallback:  If True and OA API fails, try Playwright-based scraping.

    Returns:
        A DownloadResult describing what was saved (or any error).
    """
    pmid = str(pmid).strip()
    output_dir = Path(output_dir)

    result = DownloadResult(pmid=pmid, pmcid="", output_dir=output_dir)
    
    # Debug: show Playwright status on first call
    if use_fallback:
        logging.debug("%s", _PLAYWRIGHT_IMPORT_MSG)

    with requests.Session() as session:
        session.headers.update(HEADERS)

        try:
            identifiers = resolve_pmcid(pmid, session)
            result.pmcid = identifiers.pmcid

            package = fetch_oa_package(identifiers, session)
            
            try:
                # Wrap both inspect and extract in try-except for 404 handling
                package = inspect_package(package, session)

                if not package.file_list:
                    result.error = "No supplementary files identified in the article package."
                    return result

                downloaded, skipped = extract_supplements(package, output_dir, session)
                result.downloaded_files = downloaded
                result.skipped_files = skipped
                
            except requests.HTTPError as e:
                # 404 or other HTTP error on tarball operations - try fallback
                status_code = e.response.status_code if e.response is not None else "unknown"
                logging.debug(
                    "HTTPError caught: status_code=%s, use_fallback=%s, HAS_PLAYWRIGHT=%s",
                    status_code,
                    use_fallback,
                    HAS_PLAYWRIGHT,
                )
                if use_fallback and e.response.status_code == 404:
                    logging.warning("OA tarball unavailable (404). Attempting fallback with Playwright scraper...")
                    try:
                        downloaded, skipped = scrape_supplements_with_playwright(
                            result.pmcid, output_dir, session
                        )
                        result.downloaded_files = downloaded
                        result.skipped_files = skipped
                    except Exception as fallback_exc:
                        result.error = f"OA tarball failed (404) and fallback scraper failed: {fallback_exc}"
                else:
                    raise

        except ValueError as exc:
            result.error = str(exc)
        except requests.HTTPError as exc:
            result.error = f"HTTP error: {exc}"
        except Exception as exc:
            result.error = f"Unexpected error: {exc}"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from akg import akg_logging_config

    akg_logging_config("pmc_downloader.log")

    if len(sys.argv) != 3:
        logging.error("Usage: python pmc_downloader.py <PMID> <output_dir>")
        sys.exit(1)

    result = download_supplements(pmid=sys.argv[1], output_dir=sys.argv[2])
    logging.info("%s", result)
    if result.downloaded_files:
        for f in result.downloaded_files:
            logging.info("  Saved: %s", f)
    if result.skipped_files:
        for s in result.skipped_files:
            logging.info("  Skipped: %s", s)
    if not result.success:
        sys.exit(1)
