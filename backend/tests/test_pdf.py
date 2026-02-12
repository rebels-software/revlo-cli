"""Test suite for PDF download and text extraction in revlo.datasheet.pdf."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pymupdf
import pytest

from revlo.datasheet.pdf import (
    _PDF_TEXT_LIMIT,
    _select_pages_by_keyword_scan,
    _select_pages_from_bookmarks,
    download_pdf,
    extract_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_pdf(path: Path, num_pages: int = 1, text_per_page: str = "Test content") -> None:
    """Create a small test PDF with specified number of pages."""
    doc = pymupdf.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)  # A4 size
        page.insert_text((72, 72), f"{text_per_page} - Page {i + 1}")
    doc.save(str(path))
    doc.close()


def _create_large_pdf_with_bookmarks(
    path: Path,
    num_pages: int = 50,
    bookmarks: list[tuple[int, str, int]] | None = None,
    page_texts: dict[int, str] | None = None,
) -> None:
    """Create a large synthetic PDF with bookmarks (TOC) and custom page text.

    Args:
        path: Output file path.
        num_pages: Total number of pages.
        bookmarks: List of (level, title, 1-based page_num) TOC entries.
        page_texts: Dict mapping 0-based page index to custom text.
                    Pages not in the dict get generic filler text.
    """
    doc = pymupdf.open()
    page_texts = page_texts or {}

    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)
        text = page_texts.get(i, f"Generic filler content - Page {i + 1}")
        page.insert_text((72, 72), text)

    if bookmarks:
        toc = [[lvl, title, pg] for lvl, title, pg in bookmarks]
        doc.set_toc(toc)

    doc.save(str(path))
    doc.close()


def _compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# download_pdf tests
# ---------------------------------------------------------------------------


class TestDownloadPdf:
    """Tests for async download_pdf function."""

    @pytest.mark.asyncio
    async def test_successful_download_creates_vendor_dir_structure(self, tmp_path):
        """download_pdf creates {cache_dir}/{vendor_domain}/{filename}.pdf"""
        cache_dir = tmp_path / "cache"
        url = "https://www.ti.com/lit/ds/symlink/lm358.pdf"

        # Mock httpx.AsyncClient with proper async generator
        async def mock_aiter_bytes(chunk_size=8192):
            yield b"PDF content"

        mock_response = Mock()
        mock_response.headers = {"content-length": "1024"}
        mock_response.raise_for_status = Mock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = Mock(return_value=mock_stream_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
            result = await download_pdf(url, cache_dir)

        assert result is not None
        expected_path = cache_dir / "www.ti.com" / "lm358.pdf"
        assert result == expected_path
        assert result.exists()
        assert result.read_bytes() == b"PDF content"

    @pytest.mark.asyncio
    async def test_cache_hit_returns_existing_path_without_network_call(self, tmp_path):
        """download_pdf returns existing file immediately without network call."""
        cache_dir = tmp_path / "cache"
        vendor_dir = cache_dir / "www.ti.com"
        vendor_dir.mkdir(parents=True)
        pdf_path = vendor_dir / "lm358.pdf"
        pdf_path.write_bytes(b"Existing PDF")

        url = "https://www.ti.com/lit/ds/symlink/lm358.pdf"

        with patch("revlo.datasheet.pdf.httpx.AsyncClient") as mock_client_class:
            result = await download_pdf(url, cache_dir)
            # Ensure no network call was made
            mock_client_class.assert_not_called()

        assert result == pdf_path
        assert result.read_bytes() == b"Existing PDF"

    @pytest.mark.asyncio
    async def test_size_cap_via_content_length_header(self, tmp_path):
        """download_pdf rejects files larger than 200MB based on Content-Length."""
        cache_dir = tmp_path / "cache"
        url = "https://www.example.com/huge.pdf"

        # Mock response with Content-Length exceeding 200MB
        mock_response = Mock()
        mock_response.headers = {"content-length": str(201 * 1024 * 1024)}
        mock_response.raise_for_status = Mock()

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = Mock(return_value=mock_stream_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
            result = await download_pdf(url, cache_dir)

        assert result is None
        # Verify no file was created
        assert not (cache_dir / "www.example.com" / "huge.pdf").exists()

    @pytest.mark.asyncio
    async def test_size_cap_during_streaming(self, tmp_path):
        """download_pdf aborts and returns None if download exceeds 200MB during streaming."""
        cache_dir = tmp_path / "cache"
        url = "https://www.example.com/huge.pdf"

        # Mock response without Content-Length but stream exceeds limit
        # Use realistic chunk size that will be called by the implementation
        real_chunk_size = 8192  # Matches implementation's chunk_size
        num_chunks = (200 * 1024 * 1024 // real_chunk_size) + 2  # Slightly over 200MB

        async def chunk_generator(chunk_size=8192):
            for _ in range(num_chunks):
                yield b"x" * real_chunk_size

        mock_response = Mock()
        mock_response.headers = {}  # No Content-Length
        mock_response.raise_for_status = Mock()
        mock_response.aiter_bytes = chunk_generator

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = Mock(return_value=mock_stream_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
            result = await download_pdf(url, cache_dir)

        assert result is None
        # Temp file should be cleaned up
        vendor_dir = cache_dir / "www.example.com"
        if vendor_dir.exists():
            assert not (vendor_dir / "huge.pdf").exists()
            assert not (vendor_dir / "huge.tmp").exists()

    @pytest.mark.asyncio
    async def test_http_404_returns_none(self, tmp_path):
        """download_pdf returns None on HTTP 404 error."""
        cache_dir = tmp_path / "cache"
        url = "https://www.example.com/notfound.pdf"

        mock_response = Mock()
        mock_response.status_code = 404

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found", request=Mock(), response=mock_response
            )
        )
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = Mock(return_value=mock_stream_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
            result = await download_pdf(url, cache_dir)

        assert result is None

    @pytest.mark.asyncio
    async def test_network_timeout_returns_none(self, tmp_path):
        """download_pdf returns None on network timeout."""
        cache_dir = tmp_path / "cache"
        url = "https://www.example.com/timeout.pdf"

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(side_effect=httpx.ConnectTimeout("Timeout"))
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = Mock(return_value=mock_stream_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
            result = await download_pdf(url, cache_dir)

        assert result is None

    @pytest.mark.asyncio
    async def test_vendor_domain_extraction_from_url(self, tmp_path):
        """download_pdf correctly extracts vendor domain from various URL formats."""
        cache_dir = tmp_path / "cache"

        test_cases = [
            ("https://www.ti.com/lit/ds/symlink/lm358.pdf", "www.ti.com"),
            ("https://docs.espressif.com/en/latest/esp32/datasheet.pdf", "docs.espressif.com"),
            ("http://ww1.microchip.com/downloads/en/DeviceDoc/ATmega328.pdf", "ww1.microchip.com"),
        ]

        for url, expected_domain in test_cases:
            async def mock_aiter_bytes(chunk_size=8192):
                yield b"PDF"

            mock_response = Mock()
            mock_response.headers = {"content-length": "100"}
            mock_response.raise_for_status = Mock()
            mock_response.aiter_bytes = mock_aiter_bytes

            mock_stream_ctx = AsyncMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_client = AsyncMock()
            mock_client.stream = Mock(return_value=mock_stream_ctx)

            mock_client_ctx = AsyncMock()
            mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

            with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
                result = await download_pdf(url, cache_dir)

            assert result is not None
            assert result.parent.name == expected_domain

    @pytest.mark.asyncio
    async def test_sha256_dedup_removes_duplicate_file(self, tmp_path):
        """download_pdf detects SHA-256 duplicate and returns existing file."""
        cache_dir = tmp_path / "cache"
        vendor_dir = cache_dir / "www.example.com"
        vendor_dir.mkdir(parents=True)

        # Create an existing PDF
        existing_pdf = vendor_dir / "existing.pdf"
        existing_pdf.write_bytes(b"Same content")
        existing_hash = _compute_sha256(existing_pdf)

        # Download a different filename with same content
        url = "https://www.example.com/duplicate.pdf"

        async def mock_aiter_bytes(chunk_size=8192):
            yield b"Same content"

        mock_response = Mock()
        mock_response.headers = {"content-length": "100"}
        mock_response.raise_for_status = Mock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = Mock(return_value=mock_stream_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
            result = await download_pdf(url, cache_dir)

        # Should return the existing file
        assert result == existing_pdf
        # Duplicate should not exist
        assert not (vendor_dir / "duplicate.pdf").exists()
        # Existing file should still be there
        assert existing_pdf.exists()

    @pytest.mark.asyncio
    async def test_malformed_url_returns_none(self, tmp_path):
        """download_pdf returns None for malformed URLs."""
        cache_dir = tmp_path / "cache"
        url = "not-a-valid-url"

        # No need to mock httpx since parsing should fail first
        result = await download_pdf(url, cache_dir)

        # Should handle gracefully
        assert result is None or result.parent.name == "unknown"

    @pytest.mark.asyncio
    async def test_url_without_filename_uses_default(self, tmp_path):
        """download_pdf uses 'download.pdf' when URL has no filename."""
        cache_dir = tmp_path / "cache"
        url = "https://www.example.com/"

        async def mock_aiter_bytes(chunk_size=8192):
            yield b"PDF"

        mock_response = Mock()
        mock_response.headers = {"content-length": "100"}
        mock_response.raise_for_status = Mock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = Mock(return_value=mock_stream_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("revlo.datasheet.pdf.httpx.AsyncClient", return_value=mock_client_ctx):
            result = await download_pdf(url, cache_dir)

        assert result is not None
        assert result.name == "download.pdf"


# ---------------------------------------------------------------------------
# extract_text tests
# ---------------------------------------------------------------------------


class TestExtractText:
    """Tests for extract_text function using PyMuPDF."""

    def test_extract_text_from_single_page_pdf(self, tmp_path):
        """extract_text reads text from a single-page PDF."""
        pdf_path = tmp_path / "single.pdf"
        _create_test_pdf(pdf_path, num_pages=1, text_per_page="Hello World")

        result = extract_text(pdf_path)

        assert "Hello World" in result
        assert "Page 1" in result

    def test_extract_text_from_multi_page_pdf(self, tmp_path):
        """extract_text reads text from all pages of a multi-page PDF."""
        pdf_path = tmp_path / "multi.pdf"
        _create_test_pdf(pdf_path, num_pages=3, text_per_page="Content")

        result = extract_text(pdf_path)

        assert "Page 1" in result
        assert "Page 2" in result
        assert "Page 3" in result
        assert result.count("Content") == 3

    def test_extract_text_respects_max_pages(self, tmp_path):
        """extract_text only reads up to max_pages."""
        pdf_path = tmp_path / "many.pdf"
        _create_test_pdf(pdf_path, num_pages=10, text_per_page="Sample")

        result = extract_text(pdf_path, max_pages=3)

        assert "Page 1" in result
        assert "Page 2" in result
        assert "Page 3" in result
        assert "Page 4" not in result
        assert result.count("Sample") == 3

    def test_extract_text_default_max_pages_is_30(self, tmp_path):
        """extract_text reads all pages for PDFs with <= max_pages (small PDF path)."""
        pdf_path = tmp_path / "medium.pdf"
        _create_test_pdf(pdf_path, num_pages=30, text_per_page="Text")

        result = extract_text(pdf_path)

        # All 30 pages should be read (small-PDF path)
        assert "Page 30" in result
        assert "Page 1" in result

    def test_extract_text_returns_empty_string_for_nonexistent_file(self, tmp_path):
        """extract_text returns empty string for files that don't exist."""
        pdf_path = tmp_path / "nonexistent.pdf"

        result = extract_text(pdf_path)

        assert result == ""

    def test_extract_text_handles_corrupted_pdf(self, tmp_path):
        """extract_text returns empty string for corrupted PDF files."""
        pdf_path = tmp_path / "corrupted.pdf"
        pdf_path.write_bytes(b"Not a valid PDF file")

        result = extract_text(pdf_path)

        assert result == ""

    def test_extract_text_concatenates_pages_with_newline(self, tmp_path):
        """extract_text joins pages with newline separator."""
        pdf_path = tmp_path / "test.pdf"
        _create_test_pdf(pdf_path, num_pages=2, text_per_page="Line")

        result = extract_text(pdf_path)

        # Should have newline between pages
        lines = result.split("\n")
        assert len(lines) >= 2

    def test_extract_text_empty_pdf(self, tmp_path):
        """extract_text handles PDFs with no extractable text gracefully."""
        pdf_path = tmp_path / "empty.pdf"
        # Create a PDF with a page but no text
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)  # A4 page with no text
        doc.save(str(pdf_path))
        doc.close()

        result = extract_text(pdf_path)

        # PDF with no text should return empty string
        assert result == ""


# ---------------------------------------------------------------------------
# _select_pages_from_bookmarks unit tests
# ---------------------------------------------------------------------------


class TestSelectPagesFromBookmarks:
    """Unit tests for the bookmark-based page selector."""

    def test_returns_none_when_toc_is_empty(self):
        result = _select_pages_from_bookmarks([], total_pages=50)
        assert result is None

    def test_returns_none_when_no_matching_bookmarks(self):
        toc = [
            [1, "Introduction", 1],
            [1, "Ordering Information", 10],
            [1, "Package Dimensions", 40],
        ]
        result = _select_pages_from_bookmarks(toc, total_pages=50)
        assert result is None

    def test_matches_absolute_maximum_bookmark(self):
        toc = [
            [1, "Introduction", 1],
            [1, "Absolute Maximum Ratings", 20],
            [1, "Ordering Information", 25],
        ]
        result = _select_pages_from_bookmarks(toc, total_pages=50)
        assert result is not None
        # Pages 19..24 (0-based), i.e. section from page 20 to before page 25
        assert result == list(range(19, 24))

    def test_matches_electrical_characteristics(self):
        toc = [
            [1, "Features", 1],
            [1, "Electrical Characteristics", 15],
            [1, "Packaging", 20],
        ]
        result = _select_pages_from_bookmarks(toc, total_pages=50)
        assert result is not None
        assert result == list(range(14, 19))

    def test_matches_pin_description_variants(self):
        for title in ["Pin Description", "Pin Functions", "Pin Definition Table"]:
            toc = [
                [1, "Overview", 1],
                [1, title, 8],
                [1, "Applications", 12],
            ]
            result = _select_pages_from_bookmarks(toc, total_pages=50)
            assert result is not None, f"Failed to match: {title}"
            assert result == list(range(7, 11))

    def test_matches_recommended_operating_conditions(self):
        toc = [
            [1, "Features", 1],
            [1, "Recommended Operating Conditions", 10],
            [1, "Absolute Maximum Ratings", 13],
        ]
        result = _select_pages_from_bookmarks(toc, total_pages=50)
        assert result is not None
        # Both sections match; recommended: pages 9..12, abs max: pages 12..49
        assert 9 in result  # recommended operating
        assert 12 in result  # absolute maximum

    def test_last_matching_bookmark_extends_to_end(self):
        toc = [
            [1, "Introduction", 1],
            [1, "Electrical Characteristics", 40],
        ]
        result = _select_pages_from_bookmarks(toc, total_pages=50)
        assert result is not None
        # Section extends from page 40 (0-based 39) to end (page 50, 0-based 49)
        assert result == list(range(39, 50))

    def test_nested_bookmarks_respect_level(self):
        """Sub-section bookmarks (higher level) do NOT end the parent section."""
        toc = [
            [1, "Electrical Characteristics", 10],
            [2, "DC Characteristics", 11],  # child — doesn't end section
            [2, "AC Characteristics", 14],  # child — doesn't end section
            [1, "Package Information", 20],  # same level — ends section
        ]
        result = _select_pages_from_bookmarks(toc, total_pages=50)
        assert result is not None
        # Section runs from page 10 (0-based 9) to page 20 (0-based 19 exclusive)
        assert result == list(range(9, 19))

    def test_case_insensitive_matching(self):
        toc = [
            [1, "ABSOLUTE MAXIMUM RATINGS", 5],
            [1, "Next Section", 10],
        ]
        result = _select_pages_from_bookmarks(toc, total_pages=50)
        assert result is not None
        assert result == list(range(4, 9))


# ---------------------------------------------------------------------------
# _select_pages_by_keyword_scan unit tests
# ---------------------------------------------------------------------------


class TestSelectPagesByKeywordScan:
    """Unit tests for the keyword-scanning fallback."""

    def test_finds_pages_with_target_keywords(self, tmp_path):
        pdf_path = tmp_path / "keyword_test.pdf"
        page_texts = {
            0: "Product overview and features",
            5: "Absolute maximum ratings: VCC 7V",
            10: "Electrical characteristics table",
            20: "Package dimensions",
        }
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=30, page_texts=page_texts
        )
        doc = pymupdf.open(str(pdf_path))
        result = _select_pages_by_keyword_scan(doc)
        doc.close()

        assert 5 in result   # "absolute maximum"
        assert 10 in result  # "electrical characteristics"
        assert 20 not in result  # no keywords

    def test_returns_empty_when_no_keywords_found(self, tmp_path):
        pdf_path = tmp_path / "no_keywords.pdf"
        _create_test_pdf(pdf_path, num_pages=5, text_per_page="Generic content")
        doc = pymupdf.open(str(pdf_path))
        result = _select_pages_by_keyword_scan(doc)
        doc.close()

        assert result == []

    def test_finds_recommended_operating_keyword(self, tmp_path):
        pdf_path = tmp_path / "rec_op.pdf"
        page_texts = {3: "Recommended operating conditions: 3.0V to 3.6V"}
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=10, page_texts=page_texts
        )
        doc = pymupdf.open(str(pdf_path))
        result = _select_pages_by_keyword_scan(doc)
        doc.close()

        assert 3 in result

    def test_finds_pin_function_keyword(self, tmp_path):
        pdf_path = tmp_path / "pin_fn.pdf"
        page_texts = {7: "Pin function table: PA0 is GPIO input"}
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=10, page_texts=page_texts
        )
        doc = pymupdf.open(str(pdf_path))
        result = _select_pages_by_keyword_scan(doc)
        doc.close()

        assert 7 in result


# ---------------------------------------------------------------------------
# Smart page selection integration tests (extract_text on large PDFs)
# ---------------------------------------------------------------------------


class TestSmartPageSelection:
    """Integration tests for smart page selection in extract_text."""

    def test_small_pdf_unchanged_behavior(self, tmp_path):
        """PDFs with <= max_pages use the original sequential read."""
        pdf_path = tmp_path / "small.pdf"
        _create_test_pdf(pdf_path, num_pages=25, text_per_page="SmallPDF")

        result = extract_text(pdf_path, max_pages=30)

        # All 25 pages should be present
        for i in range(1, 26):
            assert f"Page {i}" in result

    def test_large_pdf_with_bookmarks_selects_target_sections(self, tmp_path):
        """Large PDF with bookmarks: only target sections + first 3 pages extracted."""
        pdf_path = tmp_path / "datasheet.pdf"
        page_texts = {
            0: "STM32F103 Overview - Page 1",
            1: "Features summary - Page 2",
            2: "Block diagram - Page 3",
            19: "Absolute maximum ratings VCC=4.0V - Page 20",
            20: "Continued absolute max - Page 21",
            29: "Electrical characteristics DC - Page 30",
            30: "Electrical characteristics AC - Page 31",
            31: "Electrical characteristics timing - Page 32",
            39: "Package dimensions - Page 40",
        }
        bookmarks = [
            [1, "Overview", 1],
            [1, "Absolute Maximum Ratings", 20],
            [1, "Electrical Characteristics", 30],
            [1, "Package Information", 40],
            [1, "Ordering", 48],
        ]
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, bookmarks=bookmarks, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        # First 3 pages always included
        assert "Overview - Page 1" in result
        assert "Features summary - Page 2" in result
        assert "Block diagram - Page 3" in result

        # Absolute max section (pages 20-29, 0-based 19-28)
        assert "Absolute maximum ratings VCC=4.0V" in result

        # Electrical characteristics section (pages 30-39, 0-based 29-38)
        assert "Electrical characteristics DC" in result
        assert "Electrical characteristics AC" in result

        # Package info section should NOT be included (no matching bookmark)
        assert "Package dimensions" not in result

    def test_large_pdf_keyword_fallback_when_no_bookmarks(self, tmp_path):
        """Large PDF without bookmarks falls back to keyword scanning."""
        pdf_path = tmp_path / "no_bookmarks.pdf"
        page_texts = {
            0: "Product Overview - Page 1",
            1: "Features - Page 2",
            2: "Pinout - Page 3",
            15: "Absolute maximum ratings table",
            25: "Electrical characteristics data",
            35: "Package outline drawing",
        }
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, bookmarks=None, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        # First 3 pages always included
        assert "Product Overview" in result
        assert "Features" in result
        assert "Pinout" in result

        # Keyword-matched pages
        assert "Absolute maximum ratings table" in result
        assert "Electrical characteristics data" in result

        # Non-matching pages excluded
        assert "Package outline drawing" not in result

    def test_large_pdf_keyword_fallback_when_bookmarks_dont_match(self, tmp_path):
        """Bookmarks present but none match target patterns -> keyword fallback."""
        pdf_path = tmp_path / "unrelated_bookmarks.pdf"
        page_texts = {
            10: "Absolute maximum ratings: do not exceed",
            20: "Electrical characteristics summary",
        }
        bookmarks = [
            [1, "Introduction", 1],
            [1, "Application Notes", 15],
            [1, "Ordering", 40],
        ]
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, bookmarks=bookmarks, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        # Keywords found via scan
        assert "Absolute maximum ratings" in result
        assert "Electrical characteristics summary" in result

    def test_first_three_pages_always_included(self, tmp_path):
        """First 3 pages are always included regardless of method."""
        pdf_path = tmp_path / "first3.pdf"
        page_texts = {
            0: "UNIQUE_OVERVIEW_TEXT",
            1: "UNIQUE_FEATURES_TEXT",
            2: "UNIQUE_PINOUT_TEXT",
        }
        # Only bookmark on page 40
        bookmarks = [
            [1, "Electrical Characteristics", 40],
            [1, "Ordering", 48],
        ]
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, bookmarks=bookmarks, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        assert "UNIQUE_OVERVIEW_TEXT" in result
        assert "UNIQUE_FEATURES_TEXT" in result
        assert "UNIQUE_PINOUT_TEXT" in result

    def test_text_limit_cap(self, tmp_path):
        """Total extracted text is capped at _PDF_TEXT_LIMIT characters."""
        pdf_path = tmp_path / "huge_text.pdf"
        # Create pages with lots of text so total exceeds limit
        big_text = "X" * 5000  # 5K chars per page
        page_texts = {i: f"{big_text} - Page {i + 1}" for i in range(50)}
        # Mark many pages as electrical characteristics to select them all
        for i in range(5, 50):
            page_texts[i] = f"Electrical characteristics {big_text} - Page {i + 1}"

        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        assert len(result) <= _PDF_TEXT_LIMIT + 1000  # small margin for newlines

    def test_deduplication_of_page_indices(self, tmp_path):
        """Pages in both always-include set and bookmark set are only extracted once."""
        pdf_path = tmp_path / "dedup.pdf"
        page_texts = {
            0: "FIRST_PAGE_UNIQUE",
            1: "SECOND_PAGE_UNIQUE",
            2: "THIRD_PAGE_UNIQUE",
        }
        # Bookmark starts at page 1 (0-based 0) — overlaps with always-include
        bookmarks = [
            [1, "Absolute Maximum Ratings", 1],
            [1, "Next Section", 5],
        ]
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, bookmarks=bookmarks, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        # Page 1 text should appear exactly once, not duplicated
        assert result.count("FIRST_PAGE_UNIQUE") == 1

    def test_large_pdf_with_pin_description_bookmark(self, tmp_path):
        """Pin description/function bookmarks are matched."""
        pdf_path = tmp_path / "pin_desc.pdf"
        page_texts = {
            7: "Pin Description table: PA0 GPIO, PA1 USART",
            8: "Pin Description continued: PB0 SPI",
        }
        bookmarks = [
            [1, "Overview", 1],
            [1, "Pin Description", 8],
            [1, "Electrical Characteristics", 15],
            [1, "Package", 40],
        ]
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, bookmarks=bookmarks, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        assert "Pin Description table: PA0 GPIO" in result
        assert "Pin Description continued: PB0 SPI" in result

    def test_large_pdf_recommended_operating_bookmark(self, tmp_path):
        """Recommended operating conditions bookmark is matched."""
        pdf_path = tmp_path / "rec_op.pdf"
        page_texts = {
            9: "Recommended operating conditions: VCC 3.0V to 3.6V",
        }
        bookmarks = [
            [1, "Overview", 1],
            [1, "Recommended Operating Conditions", 10],
            [1, "Absolute Maximum Ratings", 15],
            [1, "Package", 40],
        ]
        _create_large_pdf_with_bookmarks(
            pdf_path, num_pages=50, bookmarks=bookmarks, page_texts=page_texts
        )

        result = extract_text(pdf_path, max_pages=30)

        assert "Recommended operating conditions: VCC 3.0V" in result

    def test_electrical_characteristics_pages_included_synthetic_stm32(self, tmp_path):
        """Synthetic STM32-style datasheet: electrical characteristics pages extracted."""
        pdf_path = tmp_path / "stm32_synthetic.pdf"

        # Simulate a realistic 100-page STM32 datasheet layout
        page_texts = {
            0: "STM32F103xx Medium-density performance line ARM-based 32-bit MCU",
            1: "Features: ARM 32-bit Cortex-M3 CPU, 72 MHz max, 128KB Flash, 20KB SRAM",
            2: "Block diagram and pinout",
            9: "Pin description: PA0-WKUP/USART2_CTS/ADC12_IN0/TIM2_CH1_ETR",
            10: "Pin description continued",
            25: "Absolute maximum ratings: VDDA = 4.0V, VDD = 4.0V",
            26: "Absolute maximum ratings continued",
            30: "General operating conditions",
            35: "Electrical characteristics: DC characteristics",
            36: "Electrical characteristics: ADC characteristics",
            37: "Electrical characteristics: DAC characteristics",
            38: "Electrical characteristics: Timer characteristics",
            50: "Recommended operating conditions: VDD 2.0V to 3.6V, TA -40 to 85",
            51: "Recommended operating conditions continued",
            80: "Package information and ordering codes",
        }

        bookmarks = [
            [1, "Description", 1],
            [1, "Features", 2],
            [1, "Pinout", 3],
            [1, "Pin Description", 10],
            [2, "Port A", 10],
            [2, "Port B", 11],
            [1, "Absolute Maximum Ratings", 26],
            [1, "General Operating Conditions", 31],
            [1, "Electrical Characteristics", 36],
            [2, "DC Characteristics", 36],
            [2, "ADC Characteristics", 37],
            [2, "DAC Characteristics", 38],
            [2, "Timer Characteristics", 39],
            [1, "Recommended Operating Conditions", 51],
            [1, "Package Information", 60],
            [1, "Ordering Codes", 90],
        ]

        _create_large_pdf_with_bookmarks(
            pdf_path,
            num_pages=100,
            bookmarks=bookmarks,
            page_texts=page_texts,
        )

        result = extract_text(pdf_path, max_pages=30)

        # First 3 pages (overview/features)
        assert "STM32F103xx" in result
        assert "ARM 32-bit Cortex-M3" in result
        assert "Block diagram" in result

        # Pin description section (pages 10-25, 0-based 9-24)
        assert "Pin description" in result

        # Absolute maximum ratings (pages 26-30, 0-based 25-29)
        assert "Absolute maximum ratings" in result

        # Electrical characteristics (pages 36-50, 0-based 35-49)
        assert "DC characteristics" in result
        assert "ADC characteristics" in result

        # Recommended operating conditions (pages 51-59, 0-based 50-58)
        assert "Recommended operating conditions" in result

        # Package info should NOT be included
        assert "Package information and ordering codes" not in result
