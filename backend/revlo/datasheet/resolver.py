"""Datasheet URL resolver for the datasheet intelligence pipeline.

Resolves datasheet PDF URLs from multiple sources in priority order:
1. Schematic-embedded URL (from KiCad component properties).
2. Mouser search API (requires MOUSER_API_KEY env var).
3. Farnell/Element14 search API (requires FARNELL_API_KEY env var).
"""

from __future__ import annotations

import logging
import os

import httpx

from revlo.datasheet.models import NormalizedPartNumber

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15.0  # seconds


async def _query_mouser(mpn: str, api_key: str) -> str | None:
    """Query the Mouser search API for a datasheet URL.

    Returns the DataSheetUrl of the first matching part, or None on any
    failure.
    """
    url = f"https://api.mouser.com/api/v1/search/partnumber?apiKey={api_key}"
    body = {"SearchByPartRequest": {"mouserPartNumber": mpn}}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        parts = data.get("SearchResults", {}).get("Parts", [])
        if parts:
            ds_url = parts[0].get("DataSheetUrl", "")
            if ds_url:
                logger.info("Mouser resolved %s -> %s", mpn, ds_url)
                return ds_url

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Mouser API HTTP %s for MPN %s", exc.response.status_code, mpn
        )
    except (httpx.RequestError, KeyError, IndexError, ValueError) as exc:
        logger.warning("Mouser API error for MPN %s: %s", mpn, exc)

    return None


async def _query_farnell(mpn: str, api_key: str) -> str | None:
    """Query the Farnell/Element14 catalog API for a datasheet URL.

    Returns the URL of the first datasheet for the first matching product,
    or None on any failure.
    """
    url = "https://api.element14.com/catalog/products"
    params = {
        "versionNumber": "1.2",
        "term": f"manuPartNum:{mpn}",
        "storeInfo.id": "uk.farnell.com",
        "resultsSettings.offset": "0",
        "resultsSettings.numberOfResults": "1",
        "resultsSettings.responseGroup": "large",
        "callInfo.apiKey": api_key,
        "callInfo.responseDataFormat": "JSON",
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        products = (
            data.get("manufacturerPartNumberSearchReturn", {})
            .get("products", [])
        )
        if products:
            datasheets = products[0].get("datasheets", [])
            if datasheets:
                ds_url = datasheets[0].get("url", "")
                if ds_url:
                    logger.info("Farnell resolved %s -> %s", mpn, ds_url)
                    return ds_url

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Farnell API HTTP %s for MPN %s", exc.response.status_code, mpn
        )
    except (httpx.RequestError, KeyError, IndexError, ValueError) as exc:
        logger.warning("Farnell API error for MPN %s: %s", mpn, exc)

    return None


async def resolve_datasheet_url(part: NormalizedPartNumber) -> str | None:
    """Resolve a datasheet PDF URL for *part* from multiple sources.

    Priority order:
    1. Schematic-embedded URL (``part.datasheet_url``).
    2. Mouser search API (if ``MOUSER_API_KEY`` env var is set).
    3. Farnell/Element14 API (if ``FARNELL_API_KEY`` env var is set).

    Generic/passive parts are skipped entirely (returns ``None``).

    This function never raises; errors from individual sources are logged
    as warnings and the next source is tried.
    """
    # Skip generic parts -- no point looking up "100nF" in a distributor API.
    if part.is_generic:
        return None

    # 1. Schematic-embedded URL.
    if part.datasheet_url:
        return part.datasheet_url

    # 2. Mouser API.
    mouser_key = os.environ.get("MOUSER_API_KEY", "")
    if mouser_key:
        result = await _query_mouser(part.mpn, mouser_key)
        if result:
            return result

    # 3. Farnell API.
    farnell_key = os.environ.get("FARNELL_API_KEY", "")
    if farnell_key:
        result = await _query_farnell(part.mpn, farnell_key)
        if result:
            return result

    return None
