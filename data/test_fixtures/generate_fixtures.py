"""
Generate test fixture CSVs from current production data.

Each fixture directory simulates a specific scenario by modifying the
production CSVs so the pipeline sees a diff when it scrapes real SBAB data.

All values are derived dynamically from current production data and
VALID_MATURITIES — nothing is hardcoded.

IMPORTANT: list_rates.csv and discount_surfaces.csv must stay consistent.
If a maturity is present in one, it must be present in the other. The
validate_fixture_consistency() check at the end enforces this.

Run from repo root:
    python3 data/test_fixtures/generate_fixtures.py

Regenerate whenever production CSVs change (e.g., after merging a deep run PR).
"""
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

# Add src/ to path so we can import io_contracts
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
from io_contracts import VALID_MATURITIES, rate_precision

DATA_DIR = Path(__file__).parent.parent  # data/
FIXTURES_DIR = Path(__file__).parent     # data/test_fixtures/


def _copy_boundaries(out_dir):
    """Copy boundaries_minimal.yaml into fixture dir (lives in data/ alongside CSVs)."""
    shutil.copy(DATA_DIR / 'boundaries_minimal.yaml', out_dir / 'boundaries_minimal.yaml')


def _first_prime_not_in(start, exclude):
    """Find the first prime >= start not in exclude."""
    def is_prime(n):
        if n < 2:
            return False
        for i in range(2, int(n**0.5) + 1):
            if n % i == 0:
                return False
        return True
    candidate = start
    while candidate in exclude or not is_prime(candidate):
        candidate += 1
    return candidate


def generate_discount_surface_change():
    """Scale current discounts to 10% of their value. Pipeline will detect mismatch."""
    out = FIXTURES_DIR / 'discount_surface_change'
    out.mkdir(exist_ok=True)
    (out / 'visualizations').mkdir(exist_ok=True)

    disc = pd.read_csv(DATA_DIR / 'discount_surfaces.csv')
    current = disc['valid_to'].isna() | (disc['valid_to'] == '')

    # Detect precision from current discount values
    dp = rate_precision(disc.loc[current, 'discount'])

    # Scale to 10% of current value (e.g., 0.58 → 0.06)
    disc.loc[current, 'discount'] = disc.loc[current, 'discount'].apply(
        lambda x: round(x * 0.1, dp) if x > 0 else x
    )
    disc.to_csv(out / 'discount_surfaces.csv', index=False)
    shutil.copy(DATA_DIR / 'list_rates.csv', out / 'list_rates.csv')
    _copy_boundaries(out)
    print("  discount_surface_change/")


def generate_list_rate_change():
    """Multiply current list rates by 20x. Pipeline will detect the diff."""
    out = FIXTURES_DIR / 'list_rate_change'
    out.mkdir(exist_ok=True)
    (out / 'visualizations').mkdir(exist_ok=True)

    lr = pd.read_csv(DATA_DIR / 'list_rates.csv')
    lr['valid_to'] = lr['valid_to'].astype('object')
    current = lr['valid_to'].isna() | (lr['valid_to'] == '')
    lr.loc[current, 'list_rate'] = lr.loc[current, 'list_rate'] * 20
    lr.to_csv(out / 'list_rates.csv', index=False)
    shutil.copy(DATA_DIR / 'discount_surfaces.csv', out / 'discount_surfaces.csv')
    _copy_boundaries(out)
    print("  list_rate_change/")


def generate_maturity_discovered():
    """Remove 2nd shortest maturity from BOTH CSVs. Pipeline scrapes it from API → 'new'."""
    out = FIXTURES_DIR / 'maturity_discovered'
    out.mkdir(exist_ok=True)
    (out / 'visualizations').mkdir(exist_ok=True)

    remove_mat = sorted(VALID_MATURITIES)[1]  # 2nd shortest (e.g., 12m)
    remaining = sorted(m for m in VALID_MATURITIES if m != remove_mat)

    # Remove rows for this maturity from list_rates
    lr = pd.read_csv(DATA_DIR / 'list_rates.csv')
    lr[lr['maturity'] != remove_mat].to_csv(out / 'list_rates.csv', index=False)

    # Remove used_for_Xm column from discount_surfaces
    disc = pd.read_csv(DATA_DIR / 'discount_surfaces.csv')
    col = f'used_for_{remove_mat}m'
    if col in disc.columns:
        disc.drop(columns=[col]).to_csv(out / 'discount_surfaces.csv', index=False)
    else:
        disc.to_csv(out / 'discount_surfaces.csv', index=False)

    with open(out / 'valid_maturities.json', 'w') as f:
        json.dump(remaining, f)
    _copy_boundaries(out)
    print(f"  maturity_discovered/ (removed {remove_mat}m)")


def generate_maturity_closed():
    """Add a fake prime-numbered maturity. Pipeline finds it missing from API → 'removed'."""
    out = FIXTURES_DIR / 'maturity_closed'
    out.mkdir(exist_ok=True)
    (out / 'visualizations').mkdir(exist_ok=True)

    fake_mat = _first_prime_not_in(691, set(VALID_MATURITIES))

    # Add fake maturity row to list_rates with rate=0.05%, valid_from=earliest date
    lr = pd.read_csv(DATA_DIR / 'list_rates.csv')
    lr['valid_to'] = lr['valid_to'].astype('object')
    earliest_date = lr['valid_from'].min()
    new_row = pd.DataFrame([{
        'maturity': fake_mat, 'list_rate': 0.05,
        'valid_from': earliest_date, 'valid_to': '',
    }])
    pd.concat([lr, new_row], ignore_index=True).to_csv(out / 'list_rates.csv', index=False)

    # Add used_for_Xm column to discount_surfaces
    disc = pd.read_csv(DATA_DIR / 'discount_surfaces.csv')
    col = f'used_for_{fake_mat}m'
    disc[col] = 0
    current = disc['valid_to'].isna() | (disc['valid_to'] == '')
    disc.loc[current, col] = 1
    disc.to_csv(out / 'discount_surfaces.csv', index=False)

    with open(out / 'valid_maturities.json', 'w') as f:
        json.dump(sorted(list(VALID_MATURITIES) + [fake_mat]), f)
    _copy_boundaries(out)
    print(f"  maturity_closed/ (added fake {fake_mat}m)")


def validate_fixture_consistency():
    """Verify that list_rates and discount_surfaces agree on which maturities exist."""
    errors = []

    for scenario in ['discount_surface_change', 'list_rate_change',
                     'maturity_discovered', 'maturity_closed']:
        out = FIXTURES_DIR / scenario
        lr = pd.read_csv(out / 'list_rates.csv')
        disc = pd.read_csv(out / 'discount_surfaces.csv')

        # Maturities in list_rates (from the maturity column)
        lr_maturities = set(lr['maturity'].unique())

        # Maturities in discount_surfaces (from used_for_*m columns)
        disc_maturities = set()
        for col in disc.columns:
            if col.startswith('used_for_') and col.endswith('m'):
                m = int(col.replace('used_for_', '').replace('m', ''))
                disc_maturities.add(m)

        # Check valid_maturities.json if present
        vm_file = out / 'valid_maturities.json'
        if vm_file.exists():
            with open(vm_file) as f:
                vm_maturities = set(json.load(f))
            if vm_maturities != disc_maturities:
                errors.append(
                    f"{scenario}: valid_maturities.json {sorted(vm_maturities)} "
                    f"!= discount_surfaces columns {sorted(disc_maturities)}"
                )
            if vm_maturities != lr_maturities:
                errors.append(
                    f"{scenario}: valid_maturities.json {sorted(vm_maturities)} "
                    f"!= list_rates maturities {sorted(lr_maturities)}"
                )

    if errors:
        print("\nCONSISTENCY ERRORS:")
        for e in errors:
            print(f"  {e}")
        raise AssertionError(f"{len(errors)} fixture consistency error(s)")
    else:
        print("\nAll fixtures consistent.")


print("Generating test fixtures from current production data...")
generate_discount_surface_change()
generate_list_rate_change()
generate_maturity_discovered()
generate_maturity_closed()
validate_fixture_consistency()
print("Done.")
