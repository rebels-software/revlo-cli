"""JSON-file cache for datasheet specs.

Stores DatasheetCacheEntry objects keyed by MPN in a JSON file on disk.
Entries expire after 90 days (TTL). Writes use atomic rename to avoid
partial/corrupt files.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import tempfile
from pathlib import Path

from revlo.datasheet.models import DatasheetCacheEntry

logger = logging.getLogger(__name__)

# Default time-to-live for cache entries.
_DEFAULT_TTL_DAYS = 90


class DatasheetCache:
    """A JSON-file cache for DatasheetCacheEntry objects, keyed by MPN.

    Args:
        cache_dir: Directory where the cache JSON file is stored.
            The file will be ``cache_dir / "cache.json"``.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._cache_path = cache_dir / "cache.json"
        self._entries: dict[str, DatasheetCacheEntry] = {}

    def get(self, mpn: str) -> DatasheetCacheEntry | None:
        """Look up a cache entry by MPN.

        Returns ``None`` if the MPN is not in the cache or if the entry
        has expired (``expires_at`` is in the past).
        """
        entry = self._entries.get(mpn)
        if entry is None:
            return None

        # Check TTL expiry.
        if entry.expires_at:
            try:
                expires = datetime.datetime.fromisoformat(entry.expires_at)
                if expires <= datetime.datetime.now(datetime.timezone.utc):
                    return None
            except (ValueError, TypeError):
                # Unparseable expires_at -- treat as expired.
                return None

        return entry

    def put(self, mpn: str, entry: DatasheetCacheEntry) -> None:
        """Store a cache entry.

        If ``fetched_at`` or ``expires_at`` are not already set on the
        entry, they are auto-populated using the current UTC time and
        a 90-day TTL respectively.
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        if not entry.fetched_at:
            entry.fetched_at = now.isoformat()

        if not entry.expires_at:
            expires = now + datetime.timedelta(days=_DEFAULT_TTL_DAYS)
            entry.expires_at = expires.isoformat()

        self._entries[mpn] = entry

    def load(self) -> None:
        """Load the cache from disk.

        If the cache file does not exist the cache starts empty.
        If the file contains invalid JSON a warning is logged and the
        cache starts empty.
        """
        if not self._cache_path.exists():
            self._entries = {}
            return

        try:
            raw_text = self._cache_path.read_text(encoding="utf-8")
            raw_data: dict[str, object] = json.loads(raw_text)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Corrupt or unreadable cache file %s: %s — starting empty",
                self._cache_path,
                exc,
            )
            self._entries = {}
            return

        entries: dict[str, DatasheetCacheEntry] = {}
        for key, value in raw_data.items():
            try:
                entries[key] = DatasheetCacheEntry.model_validate(value)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping invalid cache entry for MPN %r: %s", key, exc
                )
        self._entries = entries

    def save(self) -> None:
        """Write the cache to disk using an atomic rename.

        The cache directory is created if it does not already exist.
        Data is first written to a temporary file in the same directory,
        then atomically renamed to the final path.
        """
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        data = {
            mpn: entry.model_dump() for mpn, entry in self._entries.items()
        }

        # Atomic write: temp file -> rename.
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._cache_dir,
            suffix=".tmp",
            delete=False,
        )
        tmp_path = fd.name
        try:
            with fd:
                json.dump(data, fd, indent=2)
            os.replace(tmp_path, self._cache_path)
        except BaseException:
            # Clean up the temp file on any failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
