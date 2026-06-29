"""
test_pmc_downloader.py
----------------------
Unit tests for pmc_downloader.py.

Run with:
    pytest test_pmc_downloader.py -v

All network calls are mocked; no real HTTP requests are made.
"""

from __future__ import annotations

import io
import tarfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pmc_downloader import (
    ArticleIdentifiers,
    ArticlePackage,
    DownloadResult,
    _is_supplement,
    download_supplements,
    extract_supplements,
    fetch_oa_package,
    inspect_package,
    resolve_pmcid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(text: str = "", status: int = 200, content: bytes = b"") -> MagicMock:
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.content = content
    resp.raw = io.BytesIO(content)
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return resp


def _make_tarball(*entries: tuple[str, bytes]) -> bytes:
    """
    Build an in-memory .tar.gz with the given (filename, content) pairs.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _is_supplement
# ---------------------------------------------------------------------------

class TestIsSupplementHeuristic(unittest.TestCase):

    def test_supplement_in_name(self):
        self.assertTrue(_is_supplement("PMC123/supp_table1.xlsx"))
        self.assertTrue(_is_supplement("PMC123/supplemental_data.csv"))
        self.assertTrue(_is_supplement("PMC123/additional_file_1.pdf"))

    def test_numbered_supplement_prefix(self):
        self.assertTrue(_is_supplement("PMC123/s1_results.xlsx"))
        self.assertTrue(_is_supplement("PMC123/s3_methods.docx"))

    def test_data_extensions_included(self):
        self.assertTrue(_is_supplement("PMC123/data.csv"))
        self.assertTrue(_is_supplement("PMC123/results.rdata"))

    def test_main_manuscript_excluded(self):
        self.assertFalse(_is_supplement("PMC123/main.nxml"))
        self.assertFalse(_is_supplement("PMC123/article.xml"))

    def test_directory_excluded(self):
        self.assertFalse(_is_supplement("PMC123/"))

    def test_pdf_of_supplement_included(self):
        # PDFs are included because the suffix alone isn't a reason to exclude
        # them — supplement PDFs are common
        self.assertFalse(_is_supplement("PMC123/random_name.pdf"))
        self.assertTrue(_is_supplement("PMC123/supplement1.pdf"))


# ---------------------------------------------------------------------------
# resolve_pmcid
# ---------------------------------------------------------------------------

ELINK_XML_GOOD = textwrap.dedent("""\
    <?xml version="1.0"?>
    <eLinkResult>
      <LinkSet>
        <LinkSetDb>
          <LinkName>pubmed_pmc</LinkName>
          <Link><Id>7678724</Id></Link>
        </LinkSetDb>
      </LinkSet>
    </eLinkResult>
""")

ELINK_XML_EMPTY = textwrap.dedent("""\
    <?xml version="1.0"?>
    <eLinkResult>
      <LinkSet>
        <LinkSetDb>
          <LinkName>pubmed_pmc</LinkName>
        </LinkSetDb>
      </LinkSet>
    </eLinkResult>
""")


class TestResolvePmcid(unittest.TestCase):

    def _session(self, response_text):
        session = MagicMock()
        session.get.return_value = _make_response(text=response_text)
        return session

    def test_resolves_pmcid(self):
        ids = resolve_pmcid("33277541", self._session(ELINK_XML_GOOD))
        self.assertEqual(ids.pmid, "33277541")
        self.assertEqual(ids.pmcid, "PMC7678724")

    def test_raises_when_no_pmcid(self):
        with self.assertRaises(ValueError):
            resolve_pmcid("99999999", self._session(ELINK_XML_EMPTY))

    def test_http_error_propagates(self):
        session = MagicMock()
        session.get.return_value = _make_response(status=500)
        with self.assertRaises(Exception):
            resolve_pmcid("33277541", session)


# ---------------------------------------------------------------------------
# fetch_oa_package
# ---------------------------------------------------------------------------

OA_XML_GOOD = textwrap.dedent("""\
    <?xml version="1.0"?>
    <OA>
      <records>
        <record id="PMC7678724" citation="...">
          <link format="tgz" updated="2021-01-01"
                href="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa/package/PMC7678724.tar.gz"/>
        </record>
      </records>
    </OA>
""")

OA_XML_ERROR = textwrap.dedent("""\
    <?xml version="1.0"?>
    <OA>
      <error>Article not found</error>
    </OA>
""")

OA_XML_NO_LINK = textwrap.dedent("""\
    <?xml version="1.0"?>
    <OA><records><record id="PMC9999"/></records></OA>
""")


class TestFetchOaPackage(unittest.TestCase):

    def _ids(self):
        return ArticleIdentifiers(pmid="33277541", pmcid="PMC7678724")

    def _session(self, text):
        s = MagicMock()
        s.get.return_value = _make_response(text=text)
        return s

    def test_returns_package(self):
        pkg = fetch_oa_package(self._ids(), self._session(OA_XML_GOOD))
        self.assertEqual(pkg.pmcid, "PMC7678724")
        self.assertIn("PMC7678724.tar.gz", pkg.tar_url)
        self.assertTrue(pkg.tar_url.startswith("https://"))

    def test_ftp_url_converted_to_https(self):
        xml = OA_XML_GOOD.replace("https://", "ftp://")
        pkg = fetch_oa_package(self._ids(), self._session(xml))
        self.assertTrue(pkg.tar_url.startswith("https://"))

    def test_raises_on_api_error(self):
        with self.assertRaises(ValueError):
            fetch_oa_package(self._ids(), self._session(OA_XML_ERROR))

    def test_raises_when_no_link(self):
        with self.assertRaises(ValueError):
            fetch_oa_package(self._ids(), self._session(OA_XML_NO_LINK))


# ---------------------------------------------------------------------------
# inspect_package
# ---------------------------------------------------------------------------

class TestInspectPackage(unittest.TestCase):

    def _make_package(self, url="https://example.com/pkg.tar.gz"):
        return ArticlePackage(pmcid="PMC7678724", tar_url=url)

    def _session_with_tarball(self, *entries):
        tar_bytes = _make_tarball(*entries)
        s = MagicMock()
        resp = _make_response(content=tar_bytes)
        resp.raw = io.BytesIO(tar_bytes)
        s.get.return_value = resp
        return s

    def test_identifies_supplement_files(self):
        session = self._session_with_tarball(
            ("PMC7678724/article.nxml", b"<article/>"),
            ("PMC7678724/supp_table1.xlsx", b"data"),
            ("PMC7678724/s2_figures.pdf", b"pdf"),
        )
        pkg = inspect_package(self._make_package(), session)
        names = pkg.file_list
        self.assertIn("PMC7678724/supp_table1.xlsx", names)
        self.assertIn("PMC7678724/s2_figures.pdf", names)
        self.assertNotIn("PMC7678724/article.nxml", names)

    def test_empty_package(self):
        session = self._session_with_tarball(
            ("PMC7678724/article.nxml", b"<article/>"),
        )
        pkg = inspect_package(self._make_package(), session)
        self.assertEqual(pkg.file_list, [])


# ---------------------------------------------------------------------------
# extract_supplements
# ---------------------------------------------------------------------------

class TestExtractSupplements(unittest.TestCase):

    def _session_with_tarball(self, *entries):
        tar_bytes = _make_tarball(*entries)
        s = MagicMock()
        resp = _make_response(content=tar_bytes)
        resp.raw = io.BytesIO(tar_bytes)
        s.get.return_value = resp
        return s

    def test_extracts_files(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            session = self._session_with_tarball(
                ("PMC7678724/supp_table1.xlsx", b"excel-data"),
                ("PMC7678724/article.nxml", b"<article/>"),
            )
            pkg = ArticlePackage(
                pmcid="PMC7678724",
                tar_url="https://example.com/pkg.tar.gz",
                file_list=["PMC7678724/supp_table1.xlsx"],
            )
            downloaded, skipped = extract_supplements(pkg, out, session)
            self.assertEqual(len(downloaded), 1)
            self.assertEqual(downloaded[0].name, "supp_table1.xlsx")
            self.assertEqual(downloaded[0].read_bytes(), b"excel-data")
            self.assertEqual(skipped, [])

    def test_creates_output_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "new_subdir"
            session = self._session_with_tarball(
                ("PMC7678724/s1.csv", b"col1,col2\n1,2\n"),
            )
            pkg = ArticlePackage(
                pmcid="PMC7678724",
                tar_url="https://example.com/pkg.tar.gz",
                file_list=["PMC7678724/s1.csv"],
            )
            extract_supplements(pkg, out, session)
            self.assertTrue(out.is_dir())


# ---------------------------------------------------------------------------
# DownloadResult
# ---------------------------------------------------------------------------

class TestDownloadResult(unittest.TestCase):

    def test_success_property_true(self):
        r = DownloadResult(
            pmid="123", pmcid="PMC123",
            output_dir=Path("."),
            downloaded_files=[Path("x.xlsx")],
        )
        self.assertTrue(r.success)

    def test_success_property_false_on_error(self):
        r = DownloadResult(
            pmid="123", pmcid="PMC123",
            output_dir=Path("."),
            error="Something went wrong",
        )
        self.assertFalse(r.success)

    def test_success_property_false_when_no_files(self):
        r = DownloadResult(pmid="123", pmcid="PMC123", output_dir=Path("."))
        self.assertFalse(r.success)


# ---------------------------------------------------------------------------
# download_supplements (integration-style, all network mocked)
# ---------------------------------------------------------------------------

class TestDownloadSupplements(unittest.TestCase):
    """
    Patches requests.Session to exercise the full pipeline without I/O.
    """

    def _make_session_mock(self, elink_xml, oa_xml, tar_entries):
        tar_bytes = _make_tarball(*tar_entries)

        responses = {
            "elink": _make_response(text=elink_xml),
            "oa":    _make_response(text=oa_xml),
            "tar1":  MagicMock(raise_for_status=MagicMock(), raw=io.BytesIO(tar_bytes)),
            "tar2":  MagicMock(raise_for_status=MagicMock(), raw=io.BytesIO(tar_bytes)),
        }

        call_order = ["elink", "oa", "tar1", "tar2"]
        call_counter = {"n": 0}

        def fake_get(url, **kwargs):
            key = call_order[min(call_counter["n"], len(call_order) - 1)]
            call_counter["n"] += 1
            return responses[key]

        session = MagicMock()
        session.get.side_effect = fake_get
        session.__enter__ = lambda s: session
        session.__exit__ = MagicMock(return_value=False)
        return session

    def test_full_pipeline_success(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tar_entries = [
                ("PMC7678724/supp_table1.xlsx", b"data"),
                ("PMC7678724/article.nxml", b"<article/>"),
            ]
            session = self._make_session_mock(
                ELINK_XML_GOOD, OA_XML_GOOD, tar_entries
            )
            with patch("pmc_downloader.requests.Session", return_value=session):
                result = download_supplements("33277541", td)

            self.assertTrue(result.success)
            self.assertEqual(result.pmcid, "PMC7678724")
            self.assertEqual(len(result.downloaded_files), 1)

    def test_no_pmc_record_returns_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            session = self._make_session_mock(ELINK_XML_EMPTY, "", [])
            with patch("pmc_downloader.requests.Session", return_value=session):
                result = download_supplements("99999999", td)
            self.assertFalse(result.success)
            self.assertIsNotNone(result.error)

    def test_oa_api_error_returns_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            session = self._make_session_mock(ELINK_XML_GOOD, OA_XML_ERROR, [])
            with patch("pmc_downloader.requests.Session", return_value=session):
                result = download_supplements("33277541", td)
            self.assertFalse(result.success)

    def test_accepts_integer_pmid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tar_entries = [("PMC7678724/s1.csv", b"a,b\n1,2\n")]
            session = self._make_session_mock(
                ELINK_XML_GOOD, OA_XML_GOOD, tar_entries
            )
            with patch("pmc_downloader.requests.Session", return_value=session):
                result = download_supplements(33277541, td)  # integer PMID
            self.assertEqual(result.pmid, "33277541")


if __name__ == "__main__":
    unittest.main()
