"""
Unit tests for update_boundaries_minimal()'s bins-changed detection (no network, no git).

The email reports whether SBAB's break lines actually changed, not just whether
discount values shifted. These tests pin that the comparison is a real list
comparison (catches both a count change and a same-count relocation), and that
"no file yet" counts as changed.

Run: pytest tests/test_update_boundaries_minimal.py -v
"""
from importlib import import_module

step_6i = import_module('6i_update_boundaries_minimal')
update_boundaries_minimal = step_6i.update_boundaries_minimal

BINS = {
    'LTV_BINS': [0.0, 0.5, 0.6, 0.85, 1.0],
    'VOL_BINS': [0, 500000, 1000000, 999_999_999],
    'LTV_LABELS': ['(0-50)%', '(50-60)%', '(60-85)%', '(85+)%'],
    'VOL_LABELS': ['(0-0.5)M', '(0.5-1)M', '(1+)M'],
}


def test_no_prior_file_is_treated_as_changed(tmp_path):
    """First-ever deep run (or a fresh checkout): nothing to compare against -- changed=True."""
    yaml_path = tmp_path / 'boundaries_minimal.yaml'
    changed = update_boundaries_minimal(BINS, yaml_path=yaml_path)
    assert changed is True
    assert yaml_path.exists()


def test_identical_bins_are_not_changed(tmp_path):
    """Re-running with the exact same bins (e.g. a pure value-mismatch deep run): changed=False."""
    yaml_path = tmp_path / 'boundaries_minimal.yaml'
    update_boundaries_minimal(BINS, yaml_path=yaml_path)
    changed = update_boundaries_minimal(BINS, yaml_path=yaml_path)
    assert changed is False


def test_extra_break_line_is_changed(tmp_path):
    """A new break line (one more bin edge than before): changed=True."""
    yaml_path = tmp_path / 'boundaries_minimal.yaml'
    update_boundaries_minimal(BINS, yaml_path=yaml_path)

    more_bins = dict(BINS)
    more_bins['LTV_BINS'] = [0.0, 0.5, 0.6, 0.75, 0.85, 1.0]
    more_bins['LTV_LABELS'] = ['(0-50)%', '(50-60)%', '(60-75)%', '(75-85)%', '(85+)%']
    changed = update_boundaries_minimal(more_bins, yaml_path=yaml_path)
    assert changed is True


def test_same_count_relocated_break_is_changed(tmp_path):
    """A break line moved (60% -> 65%) with the SAME number of bins as before -- must still
    register as changed. A len()-only comparison would wrongly say False here."""
    yaml_path = tmp_path / 'boundaries_minimal.yaml'
    update_boundaries_minimal(BINS, yaml_path=yaml_path)

    relocated = dict(BINS)
    relocated['LTV_BINS'] = [0.0, 0.5, 0.65, 0.85, 1.0]
    relocated['LTV_LABELS'] = ['(0-50)%', '(50-65)%', '(65-85)%', '(85+)%']
    changed = update_boundaries_minimal(relocated, yaml_path=yaml_path)
    assert changed is True


def test_vol_only_change_is_detected_independently_of_ltv(tmp_path):
    """A VOL-only change must also register, even with LTV_BINS held identical."""
    yaml_path = tmp_path / 'boundaries_minimal.yaml'
    update_boundaries_minimal(BINS, yaml_path=yaml_path)

    vol_changed = dict(BINS)
    vol_changed['VOL_BINS'] = [0, 500000, 1500000, 999_999_999]
    vol_changed['VOL_LABELS'] = ['(0-0.5)M', '(0.5-1.5)M', '(1.5+)M']
    changed = update_boundaries_minimal(vol_changed, yaml_path=yaml_path)
    assert changed is True
