"""Unit tests for caching system."""

import pytest
import tempfile
from pathlib import Path
from src.cache import CacheManager, compute_pdf_hash


def test_compute_pdf_hash(tmp_path):
    """Test PDF hash computation."""
    # Create a test file
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"test pdf content")
    
    hash1 = compute_pdf_hash(test_file)
    hash2 = compute_pdf_hash(test_file)
    
    # Same file should produce same hash
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest length


def test_cache_manager(tmp_path):
    """Test cache manager operations."""
    cache_dir = tmp_path / "cache"
    cache_manager = CacheManager(cache_dir=cache_dir)
    
    # Verify cache directory created
    assert cache_dir.exists()
    assert (cache_dir / "cache.db").exists()


def test_cache_lookup_miss(tmp_path):
    """Test cache lookup for non-existent entry."""
    cache_dir = tmp_path / "cache"
    cache_manager = CacheManager(cache_dir=cache_dir)
    
    result = cache_manager.lookup("nonexistent_hash")
    assert result is None







