"""
Integration tests for the SBAB pipeline.

Each test runs the full pipeline against fixture CSVs with the real SBAB API.
Tests that trigger deep runs create real PRs (with DO NOT MERGE prefix).
Cleanup happens automatically via the run_pipeline_on_fixture fixture.

Run all:       pytest tests/ -v -m ""
Light only:    pytest tests/ -v -m "slow and not very_slow"
Skip all slow: pytest tests/ -v   (the default, set in pytest.ini)

Timing:
  list_rate_change:        ~5 min  (light run only, no deep run)
  discount_surface_change: ~50 min (triggers deep run + PR)
  maturity_discovered:     ~50 min (triggers deep run + PR)
  maturity_closed:         ~50 min (triggers deep run + PR)
"""
import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / 'data' / 'test_fixtures'


@pytest.mark.slow
def test_list_rate_change(run_pipeline_on_fixture):
    """Fixture has list rates at 20x. Pipeline should detect the diff."""
    state = run_pipeline_on_fixture('list_rate_change')

    assert state['email_type'] == 'list_rate_change'
    assert state['list_rate_changes'] is not None
    assert len(state['list_rate_changes']) > 0

    # No deep run, no PR
    assert state['pr_url'] is None


@pytest.mark.very_slow
def test_discount_surface_change(run_pipeline_on_fixture):
    """Fixture has discounts at 10% of real values. Pipeline should detect mismatch and deep run."""
    state = run_pipeline_on_fixture('discount_surface_change')

    assert state['email_type'] == 'deep_run_started'
    assert state['pr_url'] is not None
    assert 'github.com' in state['pr_url']


@pytest.mark.very_slow
def test_maturity_discovered(run_pipeline_on_fixture):
    """Fixture is missing a maturity. Pipeline scrapes it from API -> 'new' maturity."""
    # Read which maturity was removed from the fixture's valid_maturities.json
    vm_file = FIXTURES_DIR / 'maturity_discovered' / 'valid_maturities.json'
    with open(vm_file) as f:
        fixture_maturities = set(json.load(f))

    state = run_pipeline_on_fixture('maturity_discovered')

    assert state['email_type'] == 'maturity_change'
    assert state['maturity_changes'] is not None
    # The added maturity is whatever SBAB offers that the fixture was missing
    assert len(state['maturity_changes']['added']) > 0
    for m in state['maturity_changes']['added']:
        assert m not in fixture_maturities
    assert state['pr_url'] is not None
    assert 'github.com' in state['pr_url']


@pytest.mark.very_slow
def test_maturity_closed(run_pipeline_on_fixture):
    """Fixture has a fake prime maturity. Pipeline finds it missing from API -> 'removed'."""
    # Read which fake maturity was added from the fixture's valid_maturities.json
    vm_file = FIXTURES_DIR / 'maturity_closed' / 'valid_maturities.json'
    with open(vm_file) as f:
        fixture_maturities = set(json.load(f))

    state = run_pipeline_on_fixture('maturity_closed')

    assert state['email_type'] == 'maturity_change'
    assert state['maturity_changes'] is not None
    # The removed maturity is the fake one that SBAB doesn't actually offer
    assert len(state['maturity_changes']['removed']) > 0
    for m in state['maturity_changes']['removed']:
        assert m in fixture_maturities
    assert state['pr_url'] is not None
    assert 'github.com' in state['pr_url']
