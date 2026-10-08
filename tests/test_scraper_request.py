"""
Unit tests for what the scraper actually sends (no network, no sleep).

Every API request must identify itself (User-Agent), and the request URL must follow
from the probe point: asset value in whole SEK (truncated), then the loan amount.

Run: pytest tests/test_scraper_request.py -v
"""
import json
from importlib import import_module

import io_contracts

scraper = import_module('extract_API_results_on_config_grid')

VALID_ITEM = {'LoptidText': '2026-12-29', 'Rantesats': 3.15, 'Rantebindningstid': 3, 'EffektivRantesats': 0.0}


class FakeResponse:
    """Enough of urlopen's return value for json.load() to read it."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _scrape_one_probe(monkeypatch, probe):
    """Run scrape_on_grid on exactly one probe point; return the Request objects sent."""
    monkeypatch.setattr(scraper, 'load_boundaries', lambda config_file: ([], []))
    monkeypatch.setattr(scraper, 'generate_probe_points', lambda ltv_bins, vol_bins: [probe])
    sent = []

    def fake_urlopen(req, timeout):
        sent.append(req)
        return FakeResponse([VALID_ITEM])

    monkeypatch.setattr(scraper.urllib.request, 'urlopen', fake_urlopen)
    scraper.scrape_on_grid('boundaries_minimal.yaml')
    return sent


def test_every_request_identifies_the_scraper(monkeypatch):
    sent = _scrape_one_probe(monkeypatch, (0.5, 500_000))
    assert len(sent) == 1
    assert sent[0].get_header('User-agent') == io_contracts.SCRAPER_USER_AGENT


def test_url_uses_truncated_whole_sek_asset_value(monkeypatch):
    """LTV 0.75 on a 500,000 SEK loan: asset = 500000 / 0.75 = 666666.67, sent as 666666."""
    sent = _scrape_one_probe(monkeypatch, (0.75, 500_000))
    assert sent[0].full_url.endswith('/666666/500000')
