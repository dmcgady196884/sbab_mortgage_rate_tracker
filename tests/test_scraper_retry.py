"""
Unit tests for the scraper's retry-then-fail-loudly behavior (no network, no sleep).

The 2026-09-27 deep run hit a transient SSL handshake timeout on one probe point.
The scraper logged it and moved on, leaving a hole in the grid that step 6c only
caught by chance (a NaN in the rasterized surface) -- and a light run wouldn't have
caught it at all, since assert_scraper_output only checks schema, not row count.

Run: pytest tests/test_scraper_retry.py -v
"""
from importlib import import_module

import pytest

scraper = import_module('extract_API_results_on_config_grid')

VALID_ITEM = {'LoptidText': '2026-12-29', 'Rantesats': 3.15, 'Rantebindningstid': 3, 'EffektivRantesats': 0.0}


class FakeResponse:
    """Enough of urlopen's return value for json.load() to read it."""

    def __init__(self, payload):
        import json
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _patch_single_probe(monkeypatch):
    """Force exactly one probe point, so each test controls exactly how many API calls happen."""
    monkeypatch.setattr(scraper, 'load_boundaries', lambda config_file: ([], []))
    monkeypatch.setattr(scraper, 'generate_probe_points', lambda ltv_bins, vol_bins: [(0.5, 500000)])
    monkeypatch.setattr(scraper.time, 'sleep', lambda seconds: None)  # tests run instantly


def test_scrape_on_grid_retries_a_transient_error_then_succeeds(monkeypatch):
    """One failure followed by success: the probe is retried, not dropped, and the row is kept."""
    _patch_single_probe(monkeypatch)
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise TimeoutError("SSL handshake timed out")
        return FakeResponse([VALID_ITEM])

    monkeypatch.setattr(scraper.urllib.request, 'urlopen', fake_urlopen)

    df = scraper.scrape_on_grid('boundaries_minimal.yaml')

    assert len(calls) == 2  # one failed attempt, one that succeeded
    assert len(df) == 1
    assert df.iloc[0]['offered_interest_rate'] == 3.15


def test_scrape_on_grid_raises_after_exhausting_retries(monkeypatch):
    """A probe that never succeeds fails loudly (no silent hole in the grid)."""
    _patch_single_probe(monkeypatch)
    calls = []
    sleeps = []
    monkeypatch.setattr(scraper.time, 'sleep', lambda seconds: sleeps.append(seconds))

    def always_fails(req, timeout):
        calls.append(req)
        raise TimeoutError("SSL handshake timed out")

    monkeypatch.setattr(scraper.urllib.request, 'urlopen', always_fails)

    with pytest.raises(RuntimeError, match="failed after .* attempts"):
        scraper.scrape_on_grid('boundaries_minimal.yaml')

    assert len(calls) == scraper.SCRAPER_MAX_RETRIES
    assert len(sleeps) == scraper.SCRAPER_MAX_RETRIES - 1  # no sleep after the final, unretried failure


def test_scrape_on_grid_succeeds_first_try_without_retrying(monkeypatch):
    """The common case: no retry machinery kicks in when the first attempt just works."""
    _patch_single_probe(monkeypatch)
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        return FakeResponse([VALID_ITEM])

    monkeypatch.setattr(scraper.urllib.request, 'urlopen', fake_urlopen)

    df = scraper.scrape_on_grid('boundaries_minimal.yaml')

    assert len(calls) == 1
    assert len(df) == 1


def test_scrape_on_grid_raises_when_the_response_is_structurally_invalid(monkeypatch):
    """
    A response that reads successfully (no socket/timeout exception) but fails
    assert_api_response (e.g. SBAB returns a degraded HTTP 200 with an empty body)
    must still raise, not silently leave a stale rejected payload in `data`.

    This is the exact case that shipped broken: `data = json.load(response)` ran
    before validation, so `data` ended up `[]` (not None) even though validation
    failed, and the `if data is None: raise` guard never fired -- the function
    went on to build an empty DataFrame and crash later with an unrelated
    KeyError instead of a clear error. Fixed two ways at once: `data` is now
    only ever assigned after validation succeeds, AND assert_api_response's
    AssertionError isn't retried at all (see the next test) -- so this now
    fails immediately on the first attempt, not after exhausting retries.
    """
    _patch_single_probe(monkeypatch)
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        return FakeResponse([])  # valid JSON, fails assert_api_response's "non-empty" check

    monkeypatch.setattr(scraper.urllib.request, 'urlopen', fake_urlopen)

    with pytest.raises(AssertionError, match="empty list"):
        scraper.scrape_on_grid('boundaries_minimal.yaml')

    assert len(calls) == 1  # failed on the first attempt, never retried


def test_scrape_on_grid_does_not_retry_a_structural_validation_failure(monkeypatch):
    """A schema/structure break (SBAB changed the API shape) is not retried -- it's
    permanent, so retrying just burns time and misleads the log into looking like a
    transient blip."""
    _patch_single_probe(monkeypatch)
    calls = []
    sleeps = []
    monkeypatch.setattr(scraper.time, 'sleep', lambda seconds: sleeps.append(seconds))

    def fake_urlopen(req, timeout):
        calls.append(req)
        return FakeResponse({'not': 'a list'})  # structurally wrong, not just empty

    monkeypatch.setattr(scraper.urllib.request, 'urlopen', fake_urlopen)

    with pytest.raises(AssertionError):
        scraper.scrape_on_grid('boundaries_minimal.yaml')

    assert len(calls) == 1  # failed immediately, no retries attempted
    assert sleeps == []
