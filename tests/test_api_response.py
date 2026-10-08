"""
Unit tests for the API-response sanity bounds and the optional pause between probes
(no network, no real sleep).

A single implausible Rantesats would otherwise become a false "list rate change"
(list rate = max over the grid), so such a response must stop the scrape.

Run: pytest tests/test_api_response.py -v
"""
import json
from importlib import import_module

import pytest

from io_contracts import RATE_MAX, RATE_MIN, assert_api_response

scraper = import_module('extract_API_results_on_config_grid')


def _item(rate):
    return {'LoptidText': '2026-12-29', 'Rantesats': rate, 'Rantebindningstid': 3, 'EffektivRantesats': 0.0}


def test_a_plausible_rate_passes():
    assert_api_response([_item(3.15)])


@pytest.mark.parametrize('rate', [99.0, -5.0, 0.0, RATE_MAX])
def test_an_implausible_rate_is_rejected(rate):
    with pytest.raises(AssertionError, match='outside the plausible range'):
        assert_api_response([_item(rate)])


def test_bounds_bracket_real_swedish_mortgage_rates():
    assert RATE_MIN < 0.5 and 15.0 < RATE_MAX


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_optional_pause_runs_once_per_probe(monkeypatch):
    monkeypatch.setattr(scraper, 'load_boundaries', lambda config_file: ([], []))
    monkeypatch.setattr(scraper, 'generate_probe_points', lambda ltv_bins, vol_bins: [(0.5, 500_000), (0.6, 500_000)])
    monkeypatch.setattr(scraper.urllib.request, 'urlopen', lambda req, timeout: FakeResponse([_item(3.15)]))
    monkeypatch.setattr(scraper, 'SCRAPER_PAUSE_SECONDS', 0.25)
    sleeps = []
    monkeypatch.setattr(scraper.time, 'sleep', lambda seconds: sleeps.append(seconds))

    scraper.scrape_on_grid('boundaries_minimal.yaml')

    assert sleeps == [0.25, 0.25]


def test_no_pause_by_default(monkeypatch):
    monkeypatch.setattr(scraper, 'load_boundaries', lambda config_file: ([], []))
    monkeypatch.setattr(scraper, 'generate_probe_points', lambda ltv_bins, vol_bins: [(0.5, 500_000)])
    monkeypatch.setattr(scraper.urllib.request, 'urlopen', lambda req, timeout: FakeResponse([_item(3.15)]))
    sleeps = []
    monkeypatch.setattr(scraper.time, 'sleep', lambda seconds: sleeps.append(seconds))

    scraper.scrape_on_grid('boundaries_minimal.yaml')

    assert sleeps == []
