"""Tests for revlo.datasheet.cache — JSON-file cache with TTL and atomic writes."""

import datetime
import json
from pathlib import Path

import pytest

from revlo.datasheet import DatasheetCache, DatasheetCacheEntry, DatasheetSpec


# -------------------------------------------------------------------------
# Basic get/put operations
# -------------------------------------------------------------------------


def test_get_put_round_trip(tmp_path):
    """get() retrieves entry stored with put()."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805")
    cache.put("LM7805", entry)
    retrieved = cache.get("LM7805")
    assert retrieved is not None
    assert retrieved.mpn == "LM7805"


def test_get_missing_key_returns_none(tmp_path):
    """get() returns None for missing MPN."""
    cache = DatasheetCache(tmp_path)
    assert cache.get("LM7805") is None


def test_multiple_mpns(tmp_path):
    """put/get multiple different MPNs independently."""
    cache = DatasheetCache(tmp_path)
    entry1 = DatasheetCacheEntry(mpn="LM7805")
    entry2 = DatasheetCacheEntry(mpn="STM32F103C8T6")
    cache.put("LM7805", entry1)
    cache.put("STM32F103C8T6", entry2)
    assert cache.get("LM7805").mpn == "LM7805"
    assert cache.get("STM32F103C8T6").mpn == "STM32F103C8T6"


def test_empty_string_mpn_as_key(tmp_path):
    """Empty string MPN is valid as a key."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="")
    cache.put("", entry)
    retrieved = cache.get("")
    assert retrieved is not None
    assert retrieved.mpn == ""


# -------------------------------------------------------------------------
# TTL expiry
# -------------------------------------------------------------------------


def test_expired_entry_returns_none(tmp_path):
    """get() returns None for expired entry (expires_at in the past)."""
    cache = DatasheetCache(tmp_path)
    past = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    entry = DatasheetCacheEntry(
        mpn="LM7805", expires_at=past.isoformat()
    )
    cache.put("LM7805", entry)
    assert cache.get("LM7805") is None


def test_expires_at_exactly_now_is_expired(tmp_path):
    """Entry with expires_at exactly equal to current time is expired."""
    cache = DatasheetCache(tmp_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    entry = DatasheetCacheEntry(
        mpn="LM7805", expires_at=now.isoformat()
    )
    cache.put("LM7805", entry)
    # Should be treated as expired (expires <= now)
    assert cache.get("LM7805") is None


def test_invalid_expires_at_format_returns_none(tmp_path):
    """get() returns None if expires_at string is unparseable."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805", expires_at="not-a-date")
    cache.put("LM7805", entry)
    assert cache.get("LM7805") is None


def test_unexpired_entry_returns_entry(tmp_path):
    """get() returns entry if expires_at is in the future."""
    cache = DatasheetCache(tmp_path)
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
    entry = DatasheetCacheEntry(
        mpn="LM7805", expires_at=future.isoformat()
    )
    cache.put("LM7805", entry)
    retrieved = cache.get("LM7805")
    assert retrieved is not None
    assert retrieved.mpn == "LM7805"


# -------------------------------------------------------------------------
# Auto-set timestamps
# -------------------------------------------------------------------------


def test_auto_set_fetched_at_when_empty(tmp_path):
    """put() auto-sets fetched_at if empty."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805")
    assert entry.fetched_at == ""
    cache.put("LM7805", entry)
    # Entry is mutated in-place
    assert entry.fetched_at != ""
    # Verify it's a valid ISO timestamp
    datetime.datetime.fromisoformat(entry.fetched_at)


def test_auto_set_expires_at_when_empty(tmp_path):
    """put() auto-sets expires_at to ~90 days from now if empty."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805")
    assert entry.expires_at == ""
    now = datetime.datetime.now(datetime.timezone.utc)
    cache.put("LM7805", entry)
    # Entry is mutated in-place
    assert entry.expires_at != ""
    expires = datetime.datetime.fromisoformat(entry.expires_at)
    # Verify it's approximately 90 days from now (within 1 minute tolerance)
    expected_expires = now + datetime.timedelta(days=90)
    assert abs((expires - expected_expires).total_seconds()) < 60


def test_preset_timestamps_preserved(tmp_path):
    """put() does not overwrite pre-set fetched_at/expires_at."""
    cache = DatasheetCache(tmp_path)
    custom_fetched = "2025-01-01T00:00:00Z"
    custom_expires = "2025-04-01T00:00:00Z"
    entry = DatasheetCacheEntry(
        mpn="LM7805",
        fetched_at=custom_fetched,
        expires_at=custom_expires,
    )
    cache.put("LM7805", entry)
    assert entry.fetched_at == custom_fetched
    assert entry.expires_at == custom_expires


# -------------------------------------------------------------------------
# save/load from disk
# -------------------------------------------------------------------------


def test_save_load_round_trip(tmp_path):
    """save() then load() restores entries."""
    cache1 = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805")
    cache1.put("LM7805", entry)
    cache1.save()

    cache2 = DatasheetCache(tmp_path)
    cache2.load()
    retrieved = cache2.get("LM7805")
    assert retrieved is not None
    assert retrieved.mpn == "LM7805"


def test_save_creates_directory(tmp_path):
    """save() creates cache_dir if it does not exist."""
    cache_dir = tmp_path / "subdir" / "cache"
    assert not cache_dir.exists()
    cache = DatasheetCache(cache_dir)
    entry = DatasheetCacheEntry(mpn="LM7805")
    cache.put("LM7805", entry)
    cache.save()
    assert cache_dir.exists()
    assert (cache_dir / "cache.json").exists()


def test_load_missing_file_starts_empty(tmp_path):
    """load() when cache.json does not exist starts empty (no error)."""
    cache = DatasheetCache(tmp_path)
    cache.load()
    assert cache.get("LM7805") is None


def test_load_corrupt_json_starts_empty(tmp_path, caplog):
    """load() when cache.json contains invalid JSON logs warning and starts empty."""
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("not valid JSON{", encoding="utf-8")

    cache = DatasheetCache(tmp_path)
    cache.load()
    assert cache.get("LM7805") is None
    assert "Corrupt or unreadable cache file" in caplog.text


def test_load_partially_invalid_entries(tmp_path, caplog):
    """load() with one valid and one invalid entry loads valid entry, skips invalid."""
    cache_path = tmp_path / "cache.json"
    data = {
        "LM7805": {
            "mpn": "LM7805",
            "spec": None,
            "pdf_path": None,
            "pdf_sha256": None,
            "source_url": "",
            "fetched_at": "",
            "expires_at": "",
        },
        "INVALID": {
            # Missing required 'mpn' field
            "spec": None,
        },
    }
    cache_path.write_text(json.dumps(data), encoding="utf-8")

    cache = DatasheetCache(tmp_path)
    cache.load()
    assert cache.get("LM7805") is not None
    assert cache.get("INVALID") is None
    assert "Skipping invalid cache entry for MPN 'INVALID'" in caplog.text


def test_save_with_nested_spec(tmp_path):
    """save() correctly serializes entry with nested DatasheetSpec."""
    cache = DatasheetCache(tmp_path)
    spec = DatasheetSpec(
        mpn="LM7805",
        manufacturer="Texas Instruments",
        supply_voltage_min=7.0,
        supply_voltage_max=35.0,
    )
    entry = DatasheetCacheEntry(
        mpn="LM7805",
        spec=spec,
        pdf_path="/cache/lm7805.pdf",
    )
    cache.put("LM7805", entry)
    cache.save()

    cache2 = DatasheetCache(tmp_path)
    cache2.load()
    retrieved = cache2.get("LM7805")
    assert retrieved.spec.manufacturer == "Texas Instruments"
    assert retrieved.spec.supply_voltage_min == 7.0
    assert retrieved.pdf_path == "/cache/lm7805.pdf"


def test_save_many_entries(tmp_path):
    """save/load works correctly with many entries."""
    cache = DatasheetCache(tmp_path)
    for i in range(100):
        entry = DatasheetCacheEntry(mpn=f"PART{i}")
        cache.put(f"PART{i}", entry)
    cache.save()

    cache2 = DatasheetCache(tmp_path)
    cache2.load()
    for i in range(100):
        assert cache2.get(f"PART{i}").mpn == f"PART{i}"


# -------------------------------------------------------------------------
# Atomic writes
# -------------------------------------------------------------------------


def test_save_uses_temp_file(tmp_path):
    """save() writes to a temp file in cache_dir before rename."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805")
    cache.put("LM7805", entry)
    cache.save()
    # No .tmp files should remain
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_save_atomic_rename(tmp_path):
    """save() uses atomic rename to prevent partial writes."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805")
    cache.put("LM7805", entry)
    cache.save()
    cache_file = tmp_path / "cache.json"
    assert cache_file.exists()
    # File should be valid JSON
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "LM7805" in data


# -------------------------------------------------------------------------
# Edge cases
# -------------------------------------------------------------------------


def test_entry_with_spec_none_cached_miss(tmp_path):
    """Entry with spec=None (cached miss) round-trips correctly."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="UNKNOWN_PART", spec=None)
    cache.put("UNKNOWN_PART", entry)
    cache.save()

    cache2 = DatasheetCache(tmp_path)
    cache2.load()
    retrieved = cache2.get("UNKNOWN_PART")
    assert retrieved is not None
    assert retrieved.mpn == "UNKNOWN_PART"
    assert retrieved.spec is None


def test_overwrite_existing_entry(tmp_path):
    """put() overwrites existing entry for same MPN."""
    cache = DatasheetCache(tmp_path)
    entry1 = DatasheetCacheEntry(mpn="LM7805", pdf_path="/old/path")
    cache.put("LM7805", entry1)
    entry2 = DatasheetCacheEntry(mpn="LM7805", pdf_path="/new/path")
    cache.put("LM7805", entry2)
    retrieved = cache.get("LM7805")
    assert retrieved.pdf_path == "/new/path"


def test_get_after_put_without_save(tmp_path):
    """get() returns entry from in-memory cache before save()."""
    cache = DatasheetCache(tmp_path)
    entry = DatasheetCacheEntry(mpn="LM7805")
    cache.put("LM7805", entry)
    # No save() yet
    retrieved = cache.get("LM7805")
    assert retrieved is not None
    assert retrieved.mpn == "LM7805"
