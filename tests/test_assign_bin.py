"""
Unit tests for assign_bin()'s boundary behavior (no network, no files).

The bug this guards against already shipped once undetected: assign_bin assumed
[low, high) for both LTV and VOL, which is backwards for LTV (confirmed empirically
2026-09-29 by probing exact bin-edge values against the live API). These tests pin
the fix so a future change can't flip it back, "simplify" it, or migrate to pd.cut
incorrectly without being caught here first.

Run: pytest tests/test_assign_bin.py -v
"""
from importlib import import_module

import pandas as pd
import pytest
import yaml

from io_contracts import LTV_BIN_RIGHT_CLOSED, VOL_BIN_RIGHT_CLOSED

mod = import_module('3a_convert_csv_to_nice_pd_df')
assign_bin = mod.assign_bin

LTV_BINS = [0.0, 0.5, 0.6, 0.65, 0.7, 0.75, 0.76, 0.77, 0.78, 0.79, 0.8, 0.85, 0.9, 999.0]
LTV_LABELS = ['(0-50)%', '(50-60)%', '(60-65)%', '(65-70)%', '(70-75)%', '(75-76)%', '(76-77)%',
             '(77-78)%', '(78-79)%', '(79-80)%', '(80-85)%', '(85-90)%', '(90+)%']
VOL_BINS = [0, 500000, 600000, 700000, 800000, 900000, 1000000, 1500000, 2000000,
           2500000, 3000000, 3500000, 4000000, 4500000, 5000000, 999_999_999]
VOL_LABELS = ['(0-0.5)M', '(0.5-0.6)M', '(0.6-0.7)M', '(0.7-0.8)M', '(0.8-0.9)M', '(0.9-1)M',
             '(1-1.5)M', '(1.5-2)M', '(2-2.5)M', '(2.5-3)M', '(3-3.5)M', '(3.5-4)M',
             '(4-4.5)M', '(4.5-5)M', '(5+)M']


@pytest.mark.parametrize('ltv, expected', [(0.60, '(50-60)%'), (0.70, '(65-70)%'), (0.80, '(79-80)%')])
def test_ltv_exact_boundary_matches_the_band_below(ltv, expected):
    """Empirically confirmed 2026-09-29: an exact LTV boundary prices with the band below it."""
    assert assign_bin(ltv, LTV_BINS, LTV_LABELS, right=True) == expected


@pytest.mark.parametrize('vol, expected', [(500000, '(0.5-0.6)M'), (1000000, '(1-1.5)M'), (1500000, '(1.5-2)M')])
def test_vol_exact_boundary_matches_the_assigned_band(vol, expected):
    """Empirically confirmed 2026-09-29: an exact VOL boundary prices with the band it's the lower edge of."""
    assert assign_bin(vol, VOL_BINS, VOL_LABELS, right=False) == expected


def test_ltv_exactly_zero_matches_the_first_bin_not_the_last():
    """The global lower edge has no bin below it to claim it -- it must stay in the first bin."""
    assert assign_bin(0.0, LTV_BINS, LTV_LABELS, right=True) == '(0-50)%'


def test_vol_exactly_zero_matches_the_first_bin():
    """[low, high) already includes its own lower edge, so this never had the LTV-side bug -- pinned anyway."""
    assert assign_bin(0, VOL_BINS, VOL_LABELS, right=False) == '(0-0.5)M'


def test_interior_values_are_unaffected():
    """A value nowhere near a boundary lands in the obviously correct bin, either convention."""
    assert assign_bin(0.55, LTV_BINS, LTV_LABELS, right=True) == '(50-60)%'
    assert assign_bin(750000, VOL_BINS, VOL_LABELS, right=False) == '(0.7-0.8)M'


def test_right_is_keyword_only():
    """A bare positional boolean must fail loudly, not silently pick a convention."""
    with pytest.raises(TypeError):
        assign_bin(0.5, LTV_BINS, LTV_LABELS, True)


def test_right_has_no_default():
    """Every caller must state which axis they're binning -- no silent guess."""
    with pytest.raises(TypeError):
        assign_bin(0.5, LTV_BINS, LTV_LABELS)


# The tests above pin assign_bin's own right=True/False behavior directly. None of them
# would catch a swap of LTV_BIN_RIGHT_CLOSED/VOL_BIN_RIGHT_CLOSED's values in
# io_contracts.py, or a swap of which constant feeds which axis at the real call sites in
# convert_scraper_to_analysis_dfs -- this is the exact bug class that already shipped once
# undetected (see module docstring), so these tests exercise the real constants and the
# real wiring, not just assign_bin in isolation.

def test_ltv_bin_right_closed_constant_matches_the_real_convention():
    """LTV_BIN_RIGHT_CLOSED itself must be True -- confirmed against the same empirical
    boundary values as test_ltv_exact_boundary_matches_the_band_below."""
    assert assign_bin(0.60, LTV_BINS, LTV_LABELS, right=LTV_BIN_RIGHT_CLOSED) == '(50-60)%'
    assert assign_bin(0.80, LTV_BINS, LTV_LABELS, right=LTV_BIN_RIGHT_CLOSED) == '(79-80)%'


def test_vol_bin_right_closed_constant_matches_the_real_convention():
    """VOL_BIN_RIGHT_CLOSED itself must be False -- confirmed against the same empirical
    boundary values as test_vol_exact_boundary_matches_the_assigned_band."""
    assert assign_bin(500000, VOL_BINS, VOL_LABELS, right=VOL_BIN_RIGHT_CLOSED) == '(0.5-0.6)M'
    assert assign_bin(1500000, VOL_BINS, VOL_LABELS, right=VOL_BIN_RIGHT_CLOSED) == '(1.5-2)M'


def test_ltv_and_vol_bin_right_closed_constants_are_opposite():
    """A copy-paste/swap bug would likely leave both equal (or both flipped together);
    the real convention requires them to be opposite."""
    assert LTV_BIN_RIGHT_CLOSED is True
    assert VOL_BIN_RIGHT_CLOSED is False
    assert LTV_BIN_RIGHT_CLOSED != VOL_BIN_RIGHT_CLOSED


def test_convert_scraper_to_analysis_dfs_binds_the_correct_constant_to_each_axis(tmp_path, monkeypatch):
    """
    Integration-level check that the real call sites in convert_scraper_to_analysis_dfs
    use LTV_BIN_RIGHT_CLOSED for ltv_bin and VOL_BIN_RIGHT_CLOSED for vol_bin -- not just
    that assign_bin behaves correctly when called directly with each constant (the tests
    above). A future edit that swapped which constant feeds which axis at the real call
    site would not be caught by those tests, but is caught here. Uses a self-contained
    fixture config (not the real boundaries_minimal.yaml) so this test doesn't become
    fragile to real boundary changes, which this project exists to make.
    """
    config = {'ltv_bins': LTV_BINS, 'ltv_labels': LTV_LABELS, 'vol_bins': VOL_BINS, 'vol_labels': VOL_LABELS}
    (tmp_path / 'boundaries_minimal.yaml').write_text(yaml.dump(config))
    list_rates_path = tmp_path / 'list_rates.csv'
    pd.DataFrame([{'maturity': 3, 'list_rate': 2.50, 'valid_to': ''}]).to_csv(list_rates_path, index=False)
    monkeypatch.setattr(mod, 'data_dir', lambda: tmp_path)

    # ltv=0.60 and loan_amount=500000 are both exact boundaries, one per axis, so a swap
    # would flip at least one of the two assertions below.
    scraper_df = pd.DataFrame([{
        'url': 'x', 'loan_amount': 500000, 'ltv': 0.60, 'period': 3,
        'offered_interest_rate': 2.0, 'scraped_at': '2026-01-01T00:00:00', 'bank': 'SBAB', 'json': '{}',
    }])
    scraper_df['loan_amount'] = scraper_df['loan_amount'].astype('int64')
    scraper_df['ltv'] = scraper_df['ltv'].astype('float64')
    scraper_df['period'] = scraper_df['period'].astype('int64')
    scraper_df['offered_interest_rate'] = scraper_df['offered_interest_rate'].astype('float64')

    _, bin_uniform_df, _ = mod.convert_scraper_to_analysis_dfs(scraper_df, list_rates_path=str(list_rates_path))

    assert bin_uniform_df.iloc[0]['ltv_bin'] == '(50-60)%'    # right-closed: boundary bands with the row below
    assert bin_uniform_df.iloc[0]['vol_bin'] == '(0.5-0.6)M'  # right-open: boundary bands with the row it's the floor of
