"""Test suite for PDF download and text extraction in revlo.datasheet.pdf."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pymupdf
import pytest

from revlo.datasheet.pdf import download_pdf, extract_text


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
        """extract_text uses max_pages=30 by default."""
        pdf_path = tmp_path / "large.pdf"
        _create_test_pdf(pdf_path, num_pages=35, text_per_page="Text")

        result = extract_text(pdf_path)

        # Should have 30 pages
        assert "Page 30" in result
        assert "Page 31" not in result

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
