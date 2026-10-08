"""
Step 6g: Create Minimal New Discount Surface (DEEP RUN)

Creates new rows in discount_surfaces.csv representing the newly discovered
discount structure. Uses the bins from 6e to define the grid, and extracts
one discount value per bin from the rasterized surfaces.

NOTE: Uniformity validation (ensuring each (LTV_bin, VOL_bin, maturity) slice
has exactly one unique discount value) is performed by step 6j, not here.
This step assumes the bins from 6e are correct.

INPUTS:
    1. Bins from step 6e
       dict: {'LTV_BINS': [...], 'VOL_BINS': [...], 'LTV_LABELS': [...], 'VOL_LABELS': [...]}
    2. Rasterized surfaces from step 6c
       tuple: (rasterized_surfaces, ltv_probes, vol_probes)

OUTPUTS:
    - New rows appended to discount_surfaces.csv
    - valid_from = today, valid_to = empty (marks as current)
    - Returns count of rows created (int)

I/O CONTRACT (from io_contracts.py):
    Input:  assert_bins(bins)
            assert_rasterized_surfaces(rasterized_surfaces)
    Output: assert_discount_surfaces_df(new_rows_df)

FILE FORMAT (new rows in discount_surfaces.csv):
    columns: [ltv_bin, vol_bin, discount, valid_from, valid_to,
              discount_pattern_id, used_for_3m, used_for_12m, ..., used_for_120m]
    - ltv_bin: "(0-50)%", "(50-60)%", ..., "(85+)%"
    - vol_bin: "(0-0.5)M", "(0.5-0.6)M", ..., "(5+)M"
    - discount: float64, 2 decimal places
    - valid_from: today's date (YYYY-MM-DD)
    - valid_to: empty string (marks as current)
    - discount_pattern_id: "uniform" or "maturity_specific"
    - used_for_Xm: 1 if this discount applies to maturity X, else 0

CONTEXT:
    - This is step 7 of the DEEP RUN ONLY section
    - Must follow immediately after 6f (close old surfaces)
    - The new surface is validated by 6j before PR is opened
"""
from datetime import date
from pathlib import Path

import pandas as pd

from io_contracts import (
    assert_bins,
    assert_rasterized_surfaces,
    assert_discount_surfaces_df,
    VALID_MATURITIES,
    rate_precision,
    data_dir,
)


def assert_probe_not_on_edge(probe_value, bin_edges, probe_type):
    """
    Assert that a probe value does not land exactly on a bin edge.

    Probes should be offset from edges (e.g., 0.499 or 0.501, not 0.50).
    If a probe lands on an edge, it's ambiguous which bin it belongs to.
    """
    for edge in bin_edges:
        if probe_value == edge:
            raise AssertionError(
                f"{probe_type} probe {probe_value} lands exactly on bin edge {edge}. "
                f"Probes should be offset from edges."
            )


def extract_discount_for_bin(rasterized_surfaces, ltv_probes, vol_probes,
                              ltv_bins, vol_bins, ltv_bin_idx, vol_bin_idx, maturity):
    """
    Extract the discount value for a specific (ltv_bin, vol_bin, maturity).

    Finds all probe points within the bin and returns their discount.
    Assumes uniformity within bin (validated later by 6j).
    """
    surface = rasterized_surfaces[maturity]

    ltv_low = ltv_bins[ltv_bin_idx]
    ltv_high = ltv_bins[ltv_bin_idx + 1]
    vol_low = vol_bins[vol_bin_idx]
    vol_high = vol_bins[vol_bin_idx + 1]

    # Find probe points within this bin and collect their discounts
    discounts = []

    for ltv_probe_idx, ltv_probe in enumerate(ltv_probes):
        # Skip probes outside this LTV bin
        if not (ltv_low < ltv_probe < ltv_high):
            continue

        for vol_probe_idx, vol_probe in enumerate(vol_probes):
            # Skip probes outside this VOL bin
            if not (vol_low < vol_probe < vol_high):
                continue

            discount_value = surface[ltv_probe_idx, vol_probe_idx]
            discounts.append(discount_value)

    # Every bin must have at least one probe - if not, the grid design is broken
    assert len(discounts) > 0, \
        f"No probes found in bin LTV=({ltv_low}, {ltv_high}), VOL=({vol_low}, {vol_high}). " \
        f"This indicates a bug in the probe grid design."

    # Return the first value (should all be same if uniform)
    dp = rate_precision(discounts)
    return round(discounts[0], dp)


def create_new_disc_surface(bins, rasterized_surfaces, ltv_probes, vol_probes, csv_path=None):
    """
    Create new discount surface rows and append to CSV.

    Args:
        bins: Dict from step 6e
        rasterized_surfaces: Dict of {maturity: 2D np.ndarray} from step 6c
        ltv_probes: List of LTV probe values from step 6c
        vol_probes: List of VOL probe values from step 6c
        csv_path: Optional path to discount_surfaces.csv

    Returns:
        int: Number of rows created
    """
    assert_bins(bins)
    assert_rasterized_surfaces(rasterized_surfaces)

    if csv_path is None:
        csv_path = data_dir() / 'discount_surfaces.csv'

    today_str = date.today().strftime('%Y-%m-%d')

    ltv_bins = bins['LTV_BINS']
    vol_bins = bins['VOL_BINS']
    ltv_labels = bins['LTV_LABELS']
    vol_labels = bins['VOL_LABELS']

    # Validate no probes land on bin edges
    for ltv_probe in ltv_probes:
        assert_probe_not_on_edge(ltv_probe, ltv_bins, "LTV")
    for vol_probe in vol_probes:
        assert_probe_not_on_edge(vol_probe, vol_bins, "VOL")

    new_rows = []

    for ltv_bin_idx, ltv_label in enumerate(ltv_labels):
        for vol_bin_idx, vol_label in enumerate(vol_labels):
            # Extract discount for each maturity
            discounts_by_maturity = {}
            for maturity in VALID_MATURITIES:
                discount = extract_discount_for_bin(
                    rasterized_surfaces, ltv_probes, vol_probes,
                    ltv_bins, vol_bins, ltv_bin_idx, vol_bin_idx, maturity
                )
                discounts_by_maturity[maturity] = discount

            # Group maturities by discount value
            discount_to_maturities = {}
            for maturity, discount in discounts_by_maturity.items():
                if discount not in discount_to_maturities:
                    discount_to_maturities[discount] = []
                discount_to_maturities[discount].append(maturity)

            # Create one row per unique discount value
            for discount, maturities in discount_to_maturities.items():
                pattern_id = "uniform" if len(discount_to_maturities) == 1 else "maturity_specific"

                row = {
                    'ltv_bin': ltv_label,
                    'vol_bin': vol_label,
                    'discount': discount,
                    'valid_from': today_str,
                    'valid_to': '',
                    'discount_pattern_id': pattern_id,
                }

                # Set used_for_Xm flags
                for maturity in VALID_MATURITIES:
                    row[f'used_for_{maturity}m'] = 1 if maturity in maturities else 0

                new_rows.append(row)

    new_df = pd.DataFrame(new_rows)

    # Ensure correct dtypes
    for maturity in VALID_MATURITIES:
        new_df[f'used_for_{maturity}m'] = new_df[f'used_for_{maturity}m'].astype('int64')

    assert_discount_surfaces_df(new_df)

    # Append to existing CSV
    existing_df = pd.read_csv(csv_path)
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)

    # Fill NaN in used_for_*m columns with 0 (handles maturity add/remove:
    # old rows may lack new maturity columns, new rows may lack old ones)
    for col in [c for c in combined_df.columns if c.startswith('used_for_')]:
        combined_df[col] = combined_df[col].fillna(0).astype('int64')

    combined_df.to_csv(csv_path, index=False)

    return len(new_rows)
