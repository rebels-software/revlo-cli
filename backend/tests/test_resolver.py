"""Tests for datasheet URL resolver (US-015)."""

import os
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from revlo.datasheet.models import NormalizedPartNumber
from revlo.datasheet.resolver import resolve_datasheet_url


class TestSchematicURLPriority:
    """Verify schematic-embedded URLs are returned first."""

    @pytest.mark.asyncio
    async def test_returns_schematic_url_when_present(self):
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            manufacturer="STMicroelectronics",
            is_generic=False,
            datasheet_url="https://example.com/datasheet.pdf",
        )
        with patch("revlo.datasheet.resolver._validate_url", return_value=True):
            result = await resolve_datasheet_url(part)
        assert result == "https://example.com/datasheet.pdf"


class TestURLValidation:
    """Test URL validation via HEAD requests."""

    @pytest.mark.asyncio
    async def test_validate_url_returns_true_for_2xx(self):
        """_validate_url returns True for 2xx status codes."""
        from revlo.datasheet.resolver import _validate_url

        mock_response = Mock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver.httpx.AsyncClient", return_value=mock_client):
            result = await _validate_url("https://example.com/datasheet.pdf")

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_url_returns_true_for_3xx(self):
        """_validate_url returns True for 3xx status codes (redirects)."""
        from revlo.datasheet.resolver import _validate_url

        mock_response = Mock()
        mock_response.status_code = 302

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver.httpx.AsyncClient", return_value=mock_client):
            result = await _validate_url("https://example.com/redirect")

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_url_returns_false_for_4xx(self):
        """_validate_url returns False for 4xx status codes."""
        from revlo.datasheet.resolver import _validate_url

        mock_response = Mock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver.httpx.AsyncClient", return_value=mock_client):
            result = await _validate_url("https://example.com/notfound.pdf")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_url_returns_false_for_5xx(self):
        """_validate_url returns False for 5xx status codes."""
        from revlo.datasheet.resolver import _validate_url

        mock_response = Mock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver.httpx.AsyncClient", return_value=mock_client):
            result = await _validate_url("https://example.com/error.pdf")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_url_returns_false_on_timeout(self):
        """_validate_url returns False when request times out."""
        from revlo.datasheet.resolver import _validate_url

        async def raise_timeout(*args, **kwargs):
            raise httpx.ConnectTimeout("Connection timeout")

        mock_client = AsyncMock()
        mock_client.head = raise_timeout
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver.httpx.AsyncClient", return_value=mock_client):
            result = await _validate_url("https://example.com/slow.pdf")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_url_returns_false_on_connection_error(self):
        """_validate_url returns False on connection errors."""
        from revlo.datasheet.resolver import _validate_url

        async def raise_connection_error(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        mock_client = AsyncMock()
        mock_client.head = raise_connection_error
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver.httpx.AsyncClient", return_value=mock_client):
            result = await _validate_url("https://unreachable.example.com/datasheet.pdf")

        assert result is False



class TestGenericParts:
    """Generic/passive parts should be skipped entirely."""

    @pytest.mark.asyncio
    async def test_returns_none_for_generic_part(self):
        part = NormalizedPartNumber(
            raw_value="100nF", mpn="100nF", is_generic=True
        )
        result = await resolve_datasheet_url(part)
        assert result is None



class TestMouserAPI:
    """Test Mouser API integration."""

    @pytest.mark.asyncio
    async def test_mouser_success(self):
        """Mouser returns datasheet URL."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        mouser_response = {
            "SearchResults": {
                "Parts": [
                    {"DataSheetUrl": "https://mouser.com/ds/STM32F103.pdf"}
                ]
            }
        }

        mock_response = AsyncMock()
        mock_response.json = lambda: mouser_response
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(os.environ, {"MOUSER_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result == "https://mouser.com/ds/STM32F103.pdf"

    @pytest.mark.asyncio
    async def test_mouser_empty_results(self):
        """Mouser returns empty parts list."""
        part = NormalizedPartNumber(
            raw_value="UNKNOWN-PART",
            mpn="UNKNOWN-PART",
            is_generic=False,
        )

        mouser_response = {"SearchResults": {"Parts": []}}

        mock_response = AsyncMock()
        mock_response.json = lambda: mouser_response
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(os.environ, {"MOUSER_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result is None

    @pytest.mark.asyncio
    async def test_mouser_http_error(self):
        """Mouser API returns HTTP error."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        mock_response = Mock()
        mock_response.status_code = 403

        def raise_status_error():
            raise httpx.HTTPStatusError(
                "Forbidden", request=Mock(), response=mock_response
            )

        mock_response.raise_for_status = raise_status_error

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(os.environ, {"MOUSER_API_KEY": "invalid-key"}):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result is None


class TestFarnellAPI:
    """Test Farnell API integration."""

    @pytest.mark.asyncio
    async def test_farnell_success(self):
        """Farnell returns datasheet URL."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        farnell_response = {
            "manufacturerPartNumberSearchReturn": {
                "products": [
                    {
                        "datasheets": [
                            {"url": "https://farnell.com/datasheets/STM32.pdf"}
                        ]
                    }
                ]
            }
        }

        mock_response = AsyncMock()
        mock_response.json = lambda: farnell_response
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(os.environ, {"FARNELL_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result == "https://farnell.com/datasheets/STM32.pdf"

    @pytest.mark.asyncio
    async def test_farnell_network_error(self):
        """Farnell API request fails with network error."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        async def raise_request_error(*args, **kwargs):
            raise httpx.RequestError("Connection timeout")

        mock_client = AsyncMock()
        mock_client.get = raise_request_error
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(os.environ, {"FARNELL_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result is None


class TestEmbeddedURLFallback:
    """Test fallback from embedded URL to APIs when validation fails."""

    @pytest.mark.asyncio
    async def test_falls_back_to_mouser_when_embedded_url_times_out(self):
        """Embedded URL times out during validation, falls back to Mouser."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
            datasheet_url="https://slow.example.com/datasheet.pdf",
        )

        # Mock _validate_url to return False (timeout)
        mouser_response = {
            "SearchResults": {
                "Parts": [
                    {"DataSheetUrl": "https://mouser.com/ds/STM32F103.pdf"}
                ]
            }
        }

        mock_mouser_response = AsyncMock()
        mock_mouser_response.json = lambda: mouser_response
        mock_mouser_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_mouser_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver._validate_url", return_value=False):
            with patch.dict(os.environ, {"MOUSER_API_KEY": "test-key"}):
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await resolve_datasheet_url(part)

        assert result == "https://mouser.com/ds/STM32F103.pdf"

    @pytest.mark.asyncio
    async def test_falls_back_to_farnell_when_embedded_url_returns_404(self):
        """Embedded URL returns 404, falls back to Farnell."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
            datasheet_url="https://example.com/notfound.pdf",
        )

        # Mock _validate_url to return False (404)
        farnell_response = {
            "manufacturerPartNumberSearchReturn": {
                "products": [
                    {
                        "datasheets": [
                            {"url": "https://farnell.com/datasheets/STM32.pdf"}
                        ]
                    }
                ]
            }
        }

        mock_farnell_response = AsyncMock()
        mock_farnell_response.json = lambda: farnell_response
        mock_farnell_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_farnell_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver._validate_url", return_value=False):
            with patch.dict(os.environ, {"FARNELL_API_KEY": "test-key"}):
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await resolve_datasheet_url(part)

        assert result == "https://farnell.com/datasheets/STM32.pdf"

    @pytest.mark.asyncio
    async def test_falls_back_when_embedded_url_has_connection_error(self):
        """Embedded URL has connection error, falls back to API."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
            datasheet_url="https://unreachable.example.com/datasheet.pdf",
        )

        mouser_response = {
            "SearchResults": {
                "Parts": [
                    {"DataSheetUrl": "https://mouser.com/ds/STM32F103.pdf"}
                ]
            }
        }

        mock_mouser_response = AsyncMock()
        mock_mouser_response.json = lambda: mouser_response
        mock_mouser_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_mouser_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("revlo.datasheet.resolver._validate_url", return_value=False):
            with patch.dict(os.environ, {"MOUSER_API_KEY": "test-key"}):
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await resolve_datasheet_url(part)

        assert result == "https://mouser.com/ds/STM32F103.pdf"


class TestFallbackChain:
    """Test fallback priority chain."""

    @pytest.mark.asyncio
    async def test_falls_back_from_mouser_to_farnell(self):
        """Mouser fails, Farnell succeeds."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        # Mouser returns empty
        mouser_response = {"SearchResults": {"Parts": []}}
        mock_mouser_response = AsyncMock()
        mock_mouser_response.json = lambda: mouser_response
        mock_mouser_response.raise_for_status = lambda: None

        # Farnell succeeds
        farnell_response = {
            "manufacturerPartNumberSearchReturn": {
                "products": [
                    {
                        "datasheets": [
                            {"url": "https://farnell.com/datasheets/STM32.pdf"}
                        ]
                    }
                ]
            }
        }
        mock_farnell_response = AsyncMock()
        mock_farnell_response.json = lambda: farnell_response
        mock_farnell_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_mouser_response)
        mock_client.get = AsyncMock(return_value=mock_farnell_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(
            os.environ, {"MOUSER_API_KEY": "test-key", "FARNELL_API_KEY": "test-key"}
        ):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result == "https://farnell.com/datasheets/STM32.pdf"

    @pytest.mark.asyncio
    async def test_returns_none_when_all_sources_fail(self):
        """No schematic URL, both APIs fail."""
        part = NormalizedPartNumber(
            raw_value="UNKNOWN-PART",
            mpn="UNKNOWN-PART",
            is_generic=False,
        )

        # Mouser returns empty
        mouser_response = {"SearchResults": {"Parts": []}}
        mock_mouser_response = AsyncMock()
        mock_mouser_response.json = lambda: mouser_response
        mock_mouser_response.raise_for_status = lambda: None

        # Farnell returns empty
        farnell_response = {"manufacturerPartNumberSearchReturn": {"products": []}}
        mock_farnell_response = AsyncMock()
        mock_farnell_response.json = lambda: farnell_response
        mock_farnell_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_mouser_response)
        mock_client.get = AsyncMock(return_value=mock_farnell_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(
            os.environ, {"MOUSER_API_KEY": "test-key", "FARNELL_API_KEY": "test-key"}
        ):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result is None

    @pytest.mark.asyncio
    async def test_logs_user_facing_message_when_all_sources_fail(self, caplog):
        """When all sources fail, log user-facing message about manual PDF placement."""
        part = NormalizedPartNumber(
            raw_value="UNKNOWN-PART",
            mpn="UNKNOWN-PART",
            is_generic=False,
        )

        # Mock all sources to fail
        mouser_response = {"SearchResults": {"Parts": []}}
        mock_mouser_response = AsyncMock()
        mock_mouser_response.json = lambda: mouser_response
        mock_mouser_response.raise_for_status = lambda: None

        farnell_response = {"manufacturerPartNumberSearchReturn": {"products": []}}
        mock_farnell_response = AsyncMock()
        mock_farnell_response.json = lambda: farnell_response
        mock_farnell_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_mouser_response)
        mock_client.get = AsyncMock(return_value=mock_farnell_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(
            os.environ, {"MOUSER_API_KEY": "test-key", "FARNELL_API_KEY": "test-key"}
        ):
            with patch("httpx.AsyncClient", return_value=mock_client):
                with caplog.at_level("WARNING"):
                    result = await resolve_datasheet_url(part, cache_dir="datasheets")

        assert result is None
        # Verify the user-facing message was logged
        assert any(
            "Could not fetch datasheet for UNKNOWN-PART" in record.message
            and "Place PDF manually in datasheets/" in record.message
            for record in caplog.records
        )


class TestErrorHandling:
    """Test graceful error handling."""

    @pytest.mark.asyncio
    async def test_mouser_invalid_json(self):
        """Mouser returns invalid JSON."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        def raise_json_error():
            raise ValueError("Invalid JSON")

        mock_response = Mock()
        mock_response.json = raise_json_error
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(os.environ, {"MOUSER_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result is None

    @pytest.mark.asyncio
    async def test_farnell_missing_keys(self):
        """Farnell returns malformed response with missing keys."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        # Missing 'products' key
        farnell_response = {"manufacturerPartNumberSearchReturn": {}}

        mock_response = AsyncMock()
        mock_response.json = lambda: farnell_response
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.dict(os.environ, {"FARNELL_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await resolve_datasheet_url(part)
                assert result is None
