"""
Unit tests for the list-rate monitor (monitor_list_rate.py): change detection and the
CSV bookkeeping that keeps each maturity's rate intervals contiguous (no overlaps, no
gaps). No network, no git; files live in tmp_path.

Run: pytest tests/test_list_rates.py -v
"""
from datetime import date, timedelta

import pandas as pd

import monitor_list_rate as monitor

TODAY = date.today().strftime('%Y-%m-%d')
YESTERDAY = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')


def _write_csv(tmp_path, rows):
    path = tmp_path / 'list_rates.csv'
    pd.DataFrame(rows, columns=['maturity', 'list_rate', 'valid_from', 'valid_to']).to_csv(path, index=False)
    return path


def _scraper_df(rates):
    """Scraper output (schema-valid) whose max offered rate per maturity is the given list rate."""
    df = pd.DataFrame([{
        'url': 'u', 'loan_amount': 500_000, 'ltv': 0.5, 'period': m, 'offered_interest_rate': r,
        'scraped_at': '2026-01-01T00:00:00', 'bank': 'SBAB', 'json': '{}',
    } for m, r in rates.items()])
    return df.astype({'loan_amount': 'int64', 'ltv': 'float64', 'period': 'int64', 'offered_interest_rate': 'float64'})


def test_unchanged_rates_report_no_change():
    assert monitor.compare_list_rates({3: 3.62, 12: 3.70}, {3: 3.62, 12: 3.70}) is None


def test_a_changed_rate_is_reported_with_old_new_and_delta():
    changes = monitor.compare_list_rates({3: 3.62, 12: 3.70}, {3: 3.60, 12: 3.70})
    assert set(changes) == {3}
    assert changes[3] == {'old': 3.6, 'new': 3.62, 'delta': 0.02}


def test_update_closes_the_old_row_and_opens_a_contiguous_new_one(tmp_path):
    path = _write_csv(tmp_path, [[3, 3.60, '2026-01-01', '']])
    _, valid_froms, _, full_df = monitor.load_current_list_rates(path)
    monitor.update_list_rates_csv({3: {'old': 3.6, 'new': 3.62, 'delta': 0.02}}, valid_froms, path, full_df)

    rows = pd.read_csv(path, keep_default_na=False).to_dict('records')
    assert len(rows) == 2
    old, new = rows
    assert (old['list_rate'], old['valid_from'], old['valid_to']) == (3.6, '2026-01-01', YESTERDAY)
    assert (new['list_rate'], new['valid_from'], new['valid_to']) == (3.62, TODAY, '')


def test_a_second_change_on_the_same_day_overwrites_instead_of_adding(tmp_path):
    """Step 2 and step 6b can both update list rates in one run; the later one wins."""
    path = _write_csv(tmp_path, [[3, 3.60, '2026-01-01', YESTERDAY], [3, 3.62, TODAY, '']])
    _, valid_froms, _, full_df = monitor.load_current_list_rates(path)
    monitor.update_list_rates_csv({3: {'old': 3.62, 'new': 3.65, 'delta': 0.03}}, valid_froms, path, full_df)

    rows = pd.read_csv(path, keep_default_na=False).to_dict('records')
    assert len(rows) == 2
    assert rows[1]['list_rate'] == 3.65


def test_analyze_list_rates_end_to_end(tmp_path):
    path = _write_csv(tmp_path, [[3, 3.60, '2026-01-01', ''], [12, 3.70, '2026-01-01', '']])
    changes = monitor.analyze_list_rates(_scraper_df({3: 3.62, 12: 3.70}), list_rates_path=path)
    assert set(changes) == {3}
    still_open = pd.read_csv(path, keep_default_na=False).query("valid_to == ''")
    assert dict(zip(still_open.maturity, still_open.list_rate)) == {3: 3.62, 12: 3.70}


def test_removed_maturity_is_closed_and_added_maturity_is_opened(tmp_path):
    path = _write_csv(tmp_path, [[3, 3.60, '2026-01-01', ''], [12, 3.70, '2026-01-01', '']])
    summary = monitor.handle_maturity_change_list_rates(
        {'removed': [12], 'added': [24]}, _scraper_df({3: 3.60, 24: 3.80}), list_rates_path=path)
    assert summary == {'closed': [12], 'added': [24]}

    rows = pd.read_csv(path, keep_default_na=False)
    closed = rows[rows.maturity == 12].iloc[0]
    opened = rows[rows.maturity == 24].iloc[0]
    assert closed.valid_to == YESTERDAY
    assert (opened.list_rate, opened.valid_from, opened.valid_to) == (3.80, TODAY, '')
