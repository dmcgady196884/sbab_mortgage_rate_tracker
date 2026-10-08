"""
Unit tests for the deep-run steps that turn scraped surfaces into stored ones, on tiny
synthetic data (no network, no git): break-line extraction (6d), bin construction (6e),
closing the old surface (6f), writing the new one (6g) and validation (6j).

Run: pytest tests/test_surface_pipeline.py -v
"""
from datetime import date, timedelta
from importlib import import_module

import numpy as np
import pandas as pd
import pytest

import io_contracts
from io_contracts import SENTINEL_VOL, VALID_MATURITIES

step_6d = import_module('6d_extract_minimal_break_lines')
step_6e = import_module('6e_make_bins_from_break_lines')
step_6f = import_module('6f_close_deprecated_disc_surfaces')
step_6g = import_module('6g_create_minimal_new_disc_surface')
step_6j = import_module('6j_validate_deep_run')

TODAY = date.today().strftime('%Y-%m-%d')
YESTERDAY = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

# 3 LTV probes x 3 VOL probes. The discount steps down between LTV 0.4 and 0.6, and steps
# up between VOL 700,000 and 1,300,000.
LTV_PROBES = [0.4, 0.6, 0.8]
VOL_PROBES = [100_000, 700_000, 1_300_000]
STEPPED = np.array([[0.10, 0.10, 0.30],
                    [0.05, 0.05, 0.25],
                    [0.05, 0.05, 0.25]])


def _all_maturities(array):
    return {m: array.copy() for m in VALID_MATURITIES}


# ---- 6d: break lines ---------------------------------------------------------------------

def test_break_lines_sit_at_the_midpoints_where_the_discount_changes():
    result = step_6d.extract_minimal_break_lines(_all_maturities(STEPPED), LTV_PROBES, VOL_PROBES)
    assert result == {'ltv_breaks': {0.5}, 'vol_breaks': {1_000_000}}


def test_a_flat_surface_has_no_break_lines():
    flat = np.full((3, 3), 0.25)
    result = step_6d.extract_minimal_break_lines(_all_maturities(flat), LTV_PROBES, VOL_PROBES)
    assert result == {'ltv_breaks': set(), 'vol_breaks': set()}


def test_a_break_in_any_one_maturity_counts():
    surfaces = _all_maturities(np.full((3, 3), 0.25))
    surfaces[84] = STEPPED.copy()
    result = step_6d.extract_minimal_break_lines(surfaces, LTV_PROBES, VOL_PROBES)
    assert result == {'ltv_breaks': {0.5}, 'vol_breaks': {1_000_000}}


def test_configured_prominent_boundaries_are_added_even_without_a_price_break(monkeypatch):
    for module in (step_6d, io_contracts):
        monkeypatch.setattr(module, 'PROMINENT_LTV_BREAKS', frozenset({0.85}))
        monkeypatch.setattr(module, 'PROMINENT_VOL_BREAKS', frozenset({750_000}))
    flat = np.full((3, 3), 0.25)
    result = step_6d.extract_minimal_break_lines(_all_maturities(flat), LTV_PROBES, VOL_PROBES)
    assert result == {'ltv_breaks': {0.85}, 'vol_breaks': {750_000}}


# ---- 6e: bins ----------------------------------------------------------------------------

def test_bins_and_labels_follow_the_break_lines():
    bins = step_6e.make_bins_from_break_lines({'ltv_breaks': {0.5, 0.6}, 'vol_breaks': {500_000, 1_000_000}})
    assert bins['LTV_BINS'] == [0.0, 0.5, 0.6, 1.0]
    assert bins['LTV_LABELS'] == ['(0-50)%', '(50-60)%', '(60+)%']
    assert bins['VOL_BINS'] == [0, 500_000, 1_000_000, SENTINEL_VOL]
    assert bins['VOL_LABELS'] == ['(0-0.5)M', '(0.5-1)M', '(1+)M']


@pytest.mark.parametrize('ltv', [0.29, 0.57, 0.58])
def test_percent_labels_survive_floating_point(ltv):
    """int(0.58 * 100) is 57; the label must still say 58."""
    bins = step_6e.make_bins_from_break_lines({'ltv_breaks': {ltv}, 'vol_breaks': set()})
    pct = round(ltv * 100)
    assert bins['LTV_LABELS'] == [f'(0-{pct})%', f'({pct}+)%']


# ---- 6f: close the old surface -----------------------------------------------------------

def test_closing_sets_valid_to_yesterday_on_open_rows_only(tmp_path):
    path = tmp_path / 'discount_surfaces.csv'
    pd.DataFrame([
        {'ltv_bin': 'a', 'vol_bin': 'x', 'valid_from': '2025-01-01', 'valid_to': '2025-12-31'},
        {'ltv_bin': 'b', 'vol_bin': 'x', 'valid_from': '2026-01-01', 'valid_to': ''},
        {'ltv_bin': 'c', 'vol_bin': 'x', 'valid_from': '2026-01-01', 'valid_to': ''},
    ]).to_csv(path, index=False)

    closed = step_6f.close_deprecated_disc_surfaces(csv_path=path)

    rows = pd.read_csv(path, keep_default_na=False)
    assert closed == 2
    assert list(rows.valid_to) == ['2025-12-31', YESTERDAY, YESTERDAY]


# ---- 6g: write the new surface -----------------------------------------------------------

BINS = {
    'LTV_BINS': [0.0, 0.5, 1.0], 'VOL_BINS': [0, 1_000_000, SENTINEL_VOL],
    'LTV_LABELS': ['(0-50)%', '(50+)%'], 'VOL_LABELS': ['(0-1)M', '(1+)M'],
}
PROBES_LTV = [0.4, 0.6]
PROBES_VOL = [500_000, 1_500_000]


def _existing_surface_csv(tmp_path):
    path = tmp_path / 'discount_surfaces.csv'
    old = {'ltv_bin': '(0-50)%', 'vol_bin': '(0-1)M', 'discount': 0.0, 'valid_from': '2025-01-01',
           'valid_to': YESTERDAY, 'discount_pattern_id': 'uniform'}
    old.update({f'used_for_{m}m': 1 for m in VALID_MATURITIES})
    pd.DataFrame([old]).to_csv(path, index=False)
    return path


def test_new_surface_rows_are_appended_open_and_uniform(tmp_path):
    path = _existing_surface_csv(tmp_path)
    surface = np.array([[0.10, 0.20], [0.30, 0.40]])

    created = step_6g.create_new_disc_surface(BINS, _all_maturities(surface), PROBES_LTV, PROBES_VOL, csv_path=path)

    rows = pd.read_csv(path, keep_default_na=False)
    new = rows.iloc[1:]
    assert created == 4 and len(rows) == 5
    assert set(new.valid_from) == {TODAY} and set(new.valid_to) == {''}
    assert set(new.discount_pattern_id) == {'uniform'}
    assert all(new[f'used_for_{m}m'].eq(1).all() for m in VALID_MATURITIES)
    by_bin = {(r.ltv_bin, r.vol_bin): r.discount for r in new.itertuples()}
    assert by_bin == {('(0-50)%', '(0-1)M'): 0.10, ('(0-50)%', '(1+)M'): 0.20,
                      ('(50+)%', '(0-1)M'): 0.30, ('(50+)%', '(1+)M'): 0.40}


def test_a_maturity_with_a_different_discount_gets_its_own_row(tmp_path):
    path = _existing_surface_csv(tmp_path)
    surfaces = _all_maturities(np.full((2, 2), 0.20))
    surfaces[120] = np.full((2, 2), 0.15)

    step_6g.create_new_disc_surface(BINS, surfaces, PROBES_LTV, PROBES_VOL, csv_path=path)

    new = pd.read_csv(path, keep_default_na=False).iloc[1:]
    one_bin = new[(new.ltv_bin == '(0-50)%') & (new.vol_bin == '(0-1)M')]
    assert len(one_bin) == 2
    assert set(one_bin.discount_pattern_id) == {'maturity_specific'}
    assert one_bin[one_bin.discount == 0.15].iloc[0].used_for_120m == 1
    assert one_bin[one_bin.discount == 0.20].iloc[0].used_for_120m == 0


def test_probe_on_a_bin_edge_is_rejected(tmp_path):
    path = _existing_surface_csv(tmp_path)
    with pytest.raises(AssertionError, match='lands exactly on bin edge'):
        step_6g.create_new_disc_surface(BINS, _all_maturities(np.full((2, 2), 0.2)), [0.5, 0.6], PROBES_VOL, csv_path=path)


# ---- 6j: validation ----------------------------------------------------------------------

def _scraper_df():
    df = pd.DataFrame([{
        'url': 'u', 'loan_amount': 500_000, 'ltv': 0.5, 'period': 3, 'offered_interest_rate': 3.6,
        'scraped_at': '2026-01-01T00:00:00', 'bank': 'SBAB', 'json': '{}',
    }])
    return df.astype({'loan_amount': 'int64', 'ltv': 'float64', 'period': 'int64', 'offered_interest_rate': 'float64'})


def _stub_steps(monkeypatch, signal):
    step_3a = import_module('3a_convert_csv_to_nice_pd_df')
    step_4 = import_module('4_analyze_shape')
    monkeypatch.setattr(step_3a, 'convert_scraper_to_analysis_dfs', lambda df: (None, None, None))
    monkeypatch.setattr(step_4, 'analyze_shape', lambda uniform, mean: signal)


def test_validation_passes_when_a_fresh_scrape_shows_no_change(monkeypatch):
    _stub_steps(monkeypatch, {'trigger_deep_run': False, 'reason': None})
    assert step_6j.validate_deep_run(_scraper_df()) == {'passed': True, 'reason': None}


def test_validation_fails_with_the_reason_when_a_fresh_scrape_still_differs(monkeypatch):
    _stub_steps(monkeypatch, {'trigger_deep_run': True, 'reason': 'Discount value mismatch in 3 bin/maturity combinations'})
    result = step_6j.validate_deep_run(_scraper_df())
    assert result['passed'] is False
    assert result['reason'] == 'Validation failed: Discount value mismatch in 3 bin/maturity combinations'
