"""
Unit tests for step 4's change detection (analyze_shape) and the prominent-boundary
check, on tiny synthetic data (no network, no git, no real CSVs).

These pin the decision the whole pipeline hangs on: does today's scrape differ from
the stored discount surface? Integer basis points are the resolution (a 1 bp change
must trigger a deep run; sub-bp noise must not), and non-uniform bins always trigger.

Run: pytest tests/test_change_detection.py -v
"""
from importlib import import_module

import pandas as pd
import pytest

import io_contracts
from io_contracts import VALID_MATURITIES

step_4 = import_module('4_analyze_shape')

LTV = '(0-50)%'
VOL = '(0.5-1)M'


def _stored_surface_csv(tmp_path, discount=0.30):
    """A one-bin stored surface, current (valid_to empty), used for every maturity."""
    row = {'ltv_bin': LTV, 'vol_bin': VOL, 'discount': discount,
           'valid_from': '2026-01-01', 'valid_to': ''}
    row.update({f'used_for_{m}m': 1 for m in VALID_MATURITIES})
    path = tmp_path / 'discount_surfaces.csv'
    pd.DataFrame([row]).to_csv(path, index=False)
    return path


def _scrape(discount=0.30, flat=True, ltv=LTV, vol=VOL):
    """Step 3a's two outputs for a one-bin scrape: (bin_uniform_df, bin_mean_df)."""
    uniform = pd.DataFrame([{'ltv_bin': ltv, 'vol_bin': vol,
                             **{f'flat_{m}m': flat for m in VALID_MATURITIES}}])
    mean = pd.DataFrame([{'ltv_bin': ltv, 'vol_bin': vol,
                          **{f'mean_discount_{m}m': float(discount) for m in VALID_MATURITIES}}])
    return uniform, mean


def test_identical_scrape_triggers_nothing(tmp_path):
    csv = _stored_surface_csv(tmp_path, discount=0.30)
    result = step_4.analyze_shape(*_scrape(discount=0.30), disc_csv_path=csv)
    assert result['trigger_deep_run'] is False
    assert result['reason'] is None


def test_one_basis_point_change_triggers_deep_run(tmp_path):
    csv = _stored_surface_csv(tmp_path, discount=0.30)
    result = step_4.analyze_shape(*_scrape(discount=0.31), disc_csv_path=csv)
    assert result['trigger_deep_run'] is True
    assert 'mismatch' in result['reason']


def test_non_uniform_bin_triggers_deep_run(tmp_path):
    csv = _stored_surface_csv(tmp_path, discount=0.30)
    uniform, mean = _scrape(discount=0.30)
    uniform.loc[0, 'flat_12m'] = False
    result = step_4.analyze_shape(uniform, mean, disc_csv_path=csv)
    assert result['trigger_deep_run'] is True
    assert 'Non-uniformity' in result['reason']


def test_a_scrape_matching_no_stored_bin_fails_loudly(tmp_path):
    """Different bin labels than the stored surface must not be reported as 'no change'."""
    csv = _stored_surface_csv(tmp_path, discount=0.30)
    with pytest.raises(AssertionError, match='no scraped bin matches'):
        step_4.analyze_shape(*_scrape(discount=0.99, ltv='(85-90)%'), disc_csv_path=csv)


def test_one_unmatched_bin_among_matching_ones_is_skipped_not_flagged(tmp_path):
    """Bins come from the stored boundaries, so a single stray bin is skipped (see the comment
    in check_value_mismatch); the matching bins are still compared."""
    csv = _stored_surface_csv(tmp_path, discount=0.30)
    (uniform_a, mean_a), (uniform_b, mean_b) = _scrape(discount=0.30), _scrape(discount=0.99, ltv='(85-90)%')
    uniform, mean = pd.concat([uniform_a, uniform_b], ignore_index=True), pd.concat([mean_a, mean_b], ignore_index=True)
    result = step_4.analyze_shape(uniform, mean, disc_csv_path=csv)
    assert result['trigger_deep_run'] is False


def test_prominent_boundaries_are_empty_by_default():
    assert io_contracts.PROMINENT_LTV_BREAKS == frozenset()
    assert io_contracts.PROMINENT_VOL_BREAKS == frozenset()
    # With nothing configured, any break lines pass.
    io_contracts.assert_prominent_boundaries_included({'ltv_breaks': {0.5}, 'vol_breaks': {1_000_000}})


def test_configured_prominent_boundaries_are_enforced(monkeypatch):
    monkeypatch.setattr(io_contracts, 'PROMINENT_LTV_BREAKS', frozenset({0.85}))
    monkeypatch.setattr(io_contracts, 'PROMINENT_VOL_BREAKS', frozenset({750_000}))
    io_contracts.assert_prominent_boundaries_included({'ltv_breaks': {0.85, 0.5}, 'vol_breaks': {750_000}})
    with pytest.raises(AssertionError, match='prominent LTV'):
        io_contracts.assert_prominent_boundaries_included({'ltv_breaks': {0.5}, 'vol_breaks': {750_000}})
    with pytest.raises(AssertionError, match='prominent VOL'):
        io_contracts.assert_prominent_boundaries_included({'ltv_breaks': {0.85}, 'vol_breaks': {1_000_000}})
