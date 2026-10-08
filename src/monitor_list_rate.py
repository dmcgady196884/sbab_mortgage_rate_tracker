"""
Shared Module: Monitor List Rates

Core logic for detecting and updating list rate changes. Called by:
    - Step 2: 2_analyze_list.py (minimal grid)
    - Step 6b: 6b_analyze_list.py (refined grid)

List rate = max(offered_interest_rate) for each maturity in scraper output.
This is the rate SBAB offers with zero discount (the smallest loan sizes, or LTV above 90%).

NOTE: Both step 2 and 6b may update list_rates.csv in the same run:
    - Step 2 updates based on minimal grid
    - 6b may find higher max rates in refined grid (more probe points)
    - If step 2 already created a row with valid_from=today, 6b OVERWRITES it
    - Step 6j (validation) is the real gatekeeper

I/O CONTRACT:
    Input: assert_scraper_output(scraper_df)
    Output: assert_list_rate_changes(result)
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from io_contracts import assert_scraper_output, assert_list_rate_changes, VALID_MATURITIES, rate_precision, data_dir


def extract_list_rates_from_scraper(scraper_df):
    """Extract list rates (max offered rate per maturity) from scraper output."""
    return scraper_df.groupby('period')['offered_interest_rate'].max().to_dict()


def load_current_list_rates(csv_path=None):
    """
    Load current list rates from CSV.

    For each maturity, finds the row with max(valid_from).
    This allows 6b to overwrite 2's update if both run on the same day.

    Returns:
        tuple: (dict of {maturity: rate}, dict of {maturity: valid_from}, csv_path, full_df)
    """
    if csv_path is None:
        csv_path = data_dir() / 'list_rates.csv'
    df = pd.read_csv(csv_path)
    df['valid_to'] = df['valid_to'].astype('object')  # Allow string assignment

    # For each maturity, get the one with max valid_from
    rates = {}
    valid_froms = {}
    for maturity in VALID_MATURITIES:
        mat_rows = df[df['maturity'] == maturity]
        if len(mat_rows) > 0:
            idx = mat_rows['valid_from'].idxmax()
            rates[maturity] = mat_rows.loc[idx, 'list_rate']
            valid_froms[maturity] = mat_rows.loc[idx, 'valid_from']

    return rates, valid_froms, csv_path, df


def compare_list_rates(scraped_rates, on_file_rates):
    """Compare scraped list rates to rates on file. Returns changes dict or None."""
    dp = rate_precision(list(scraped_rates.values()))
    changes = {}

    for maturity in VALID_MATURITIES:
        old_rate = on_file_rates.get(maturity)
        new_rate = scraped_rates.get(maturity)

        if old_rate is None or new_rate is None:
            continue

        if round(old_rate, dp) != round(new_rate, dp):
            changes[maturity] = {
                'old': round(old_rate, dp),
                'new': round(new_rate, dp),
                'delta': round(new_rate - old_rate, dp)
            }

    return changes if changes else None


def update_list_rates_csv(changes, valid_froms, csv_path, full_df):
    """
    Update list_rates.csv.

    If valid_from == today for a maturity, overwrite that row's list_rate.
    Otherwise, close old row (set valid_to=yesterday) and create new row.
    """
    today = date.today()
    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    for maturity in changes:
        mat_valid_from = valid_froms.get(maturity)

        if mat_valid_from == today_str:
            # Overwrite today's row (6b overwriting 2)
            mask = (full_df['maturity'] == maturity) & (full_df['valid_from'] == today_str)
            full_df.loc[mask, 'list_rate'] = changes[maturity]['new']
        else:
            # Close old row (valid until yesterday, new row starts today)
            mask = (full_df['maturity'] == maturity) & (full_df['valid_from'] == mat_valid_from)
            full_df.loc[mask, 'valid_to'] = yesterday

            # Create new row
            new_row = pd.DataFrame([{
                'maturity': maturity,
                'list_rate': changes[maturity]['new'],
                'valid_from': today_str,
                'valid_to': ''
            }])
            full_df = pd.concat([full_df, new_row], ignore_index=True)

    full_df.to_csv(csv_path, index=False)
    return full_df


def analyze_list_rates(scraper_df, list_rates_path=None, update_csv=True):
    """
    Full analysis: extract, compare, optionally update.

    Returns:
        dict of changes or None
    """
    assert_scraper_output(scraper_df)

    on_file_rates, valid_froms, csv_path, full_df = load_current_list_rates(list_rates_path)
    scraped_rates = extract_list_rates_from_scraper(scraper_df)

    changes = compare_list_rates(scraped_rates, on_file_rates)

    if changes and update_csv:
        update_list_rates_csv(changes, valid_froms, csv_path, full_df)

    assert_list_rate_changes(changes)
    return changes


def handle_maturity_change_list_rates(maturity_changes, scraper_df, list_rates_path=None):
    """Handle list_rates.csv bookkeeping when maturities are added or removed.

    - Removed maturities: close current row (set valid_to = yesterday)
    - Added maturities: create new row from scraped data (valid_from = today)

    Returns:
        dict summary: {'closed': [...], 'added': [...]}
    """
    if list_rates_path is None:
        list_rates_path = data_dir() / 'list_rates.csv'

    df = pd.read_csv(list_rates_path)
    df['valid_to'] = df['valid_to'].astype('object')

    today = date.today()
    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    closed = []
    added = []

    # Close rows for removed maturities
    for m in maturity_changes.get('removed', []):
        current_mask = (df['maturity'] == m) & (df['valid_to'].isna() | (df['valid_to'] == ''))
        n = current_mask.sum()
        if n > 0:
            df.loc[current_mask, 'valid_to'] = yesterday
            closed.append(m)
            print(f"  Closed {n} list_rate row(s) for {m}m")
        else:
            print(f"  Warning: no current list_rate row found for removed maturity {m}m")

    # Add rows for new maturities
    scraped_rates = extract_list_rates_from_scraper(scraper_df)
    for m in maturity_changes.get('added', []):
        rate = scraped_rates.get(m)
        if rate is None:
            print(f"  Warning: no scraped rate found for new maturity {m}m")
            continue
        new_row = pd.DataFrame([{
            'maturity': m,
            'list_rate': rate,
            'valid_from': today_str,
            'valid_to': '',
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        added.append(m)
        print(f"  Added list_rate row for {m}m: {rate}")

    df.to_csv(list_rates_path, index=False)
    return {'closed': closed, 'added': added}
