"""Datasheet URL resolver for the datasheet intelligence pipeline.

Resolves datasheet PDF URLs from multiple sources in priority order:
1. Schematic-embedded URL (from KiCad component properties) — validated via HEAD.
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
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


async def _validate_url(url: str) -> bool:
    """Return True if *url* is reachable (2xx/3xx HEAD response within 10s)."""
    # Derive a Referer from the URL's origin to look like in-site navigation.
    from urllib.parse import urlparse

    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {**_BROWSER_HEADERS, "Referer": referer}

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=10.0),
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.head(url)
            return resp.status_code < 400
    except (httpx.RequestError, httpx.HTTPStatusError):
        return False


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


async def resolve_datasheet_url(
    part: NormalizedPartNumber,
    cache_dir: str = "datasheets",
) -> str | None:
    """Resolve a datasheet PDF URL for *part* from multiple sources.

    Priority order:
    1. Schematic-embedded URL (``part.datasheet_url``) — validated via a
       fast HEAD request (10 s timeout) before returning.
    2. Mouser search API (if ``MOUSER_API_KEY`` env var is set).
    3. Farnell/Element14 API (if ``FARNELL_API_KEY`` env var is set).

    Generic/passive parts are skipped entirely (returns ``None``).

    If all sources fail for a non-generic part, a user-facing warning is
    logged advising manual PDF placement in *cache_dir*.

    This function never raises; errors from individual sources are logged
    as warnings and the next source is tried.
    """
    # Skip generic parts -- no point looking up "100nF" in a distributor API.
    if part.is_generic:
        return None

    # 1. Schematic-embedded URL — validate with a HEAD request.
    if part.datasheet_url:
        if await _validate_url(part.datasheet_url):
            return part.datasheet_url
        logger.warning(
            "Embedded datasheet URL unreachable for %s: %s",
            part.mpn,
            part.datasheet_url,
        )

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

    # All sources exhausted.
    logger.warning(
        "Could not fetch datasheet for %s. Place PDF manually in %s/ for better review results.",
        part.mpn,
        cache_dir,
    )
    return None
