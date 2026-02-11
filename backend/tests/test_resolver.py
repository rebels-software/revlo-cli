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
        result = await resolve_datasheet_url(part)
        assert result == "https://example.com/datasheet.pdf"

    @pytest.mark.asyncio
    async def test_schematic_url_bypasses_api_calls(self):
        """Even with API keys set, schematic URL is returned first."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            datasheet_url="https://example.com/datasheet.pdf",
        )
        with patch.dict(
            os.environ, {"MOUSER_API_KEY": "test-key", "FARNELL_API_KEY": "test-key"}
        ):
            with patch("httpx.AsyncClient") as mock_client:
                result = await resolve_datasheet_url(part)
                assert result == "https://example.com/datasheet.pdf"
                # No API calls should have been made
                mock_client.assert_not_called()


class TestGenericParts:
    """Generic/passive parts should be skipped entirely."""

    @pytest.mark.asyncio
    async def test_returns_none_for_generic_part(self):
        part = NormalizedPartNumber(
            raw_value="100nF", mpn="100nF", is_generic=True
        )
        result = await resolve_datasheet_url(part)
        assert result is None

    @pytest.mark.asyncio
    async def test_generic_part_bypasses_api_calls(self):
        """Generic parts skip API lookups even with keys set."""
        part = NormalizedPartNumber(
            raw_value="10K", mpn="10K", is_generic=True
        )
        with patch.dict(
            os.environ, {"MOUSER_API_KEY": "test-key", "FARNELL_API_KEY": "test-key"}
        ):
            with patch("httpx.AsyncClient") as mock_client:
                result = await resolve_datasheet_url(part)
                assert result is None
                mock_client.assert_not_called()


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
    async def test_mouser_no_api_key(self):
        """Without MOUSER_API_KEY, Mouser is skipped."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        with patch.dict(os.environ, {}, clear=True):
            with patch("httpx.AsyncClient") as mock_client:
                result = await resolve_datasheet_url(part)
                assert result is None
                mock_client.assert_not_called()

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
    async def test_farnell_no_api_key(self):
        """Without FARNELL_API_KEY, Farnell is skipped."""
        part = NormalizedPartNumber(
            raw_value="STM32F103CBT6",
            mpn="STM32F103CBT6",
            is_generic=False,
        )

        with patch.dict(os.environ, {}, clear=True):
            with patch("httpx.AsyncClient") as mock_client:
                result = await resolve_datasheet_url(part)
                assert result is None
                mock_client.assert_not_called()

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
