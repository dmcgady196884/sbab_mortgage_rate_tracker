"""
Visualization Module: Discount/Price Surface PNGs + List Rate History Plots

This module contains the core visualization logic. It is called by:
    - Step 3b: 3b_create_discount_and_price_pngs.py
    - Step 6h: 6h_create_all_png_visualizations.py

ENTRY POINTS:
    regenerate_vital_visualizations()
        - Regenerates ALL discount surface PNGs (for every (valid_from, valid_to) pair)
        - Regenerates ALL current pricing PNGs (for valid_to = empty surface only)

    generate_list_rate_history_plots()
        - Generates temporal step-function plots of list rates + best available rates
        - Email-only (not version-tracked in git)

OUTPUT FILE STRUCTURE (FLAT - all files in data/visualizations/):
    Discount surfaces (one per (valid_from, valid_to) pair, possibly split by maturity):
        discount_surface_from_20870322_to_20931029_for_3_12_24_36_months.png

    Pricing surfaces (one per maturity, dated to preserve snapshots):
        pricing_surface_20250516_for_3m.png
        ...
        pricing_surface_20250516_for_120m.png

    List rate history (temporal, email-only):
        list_rate_history_full.png         All maturities, full history
        list_rate_history_1yr.png          All maturities, last 365 days
        list_rate_history_{m}m.png         Per-maturity: list rate + best rate

DATA INTEGRITY:
    Surfaces coming out of the pipeline are expected to be complete. The one
    exception is fill_sparse_surface(), which fills gaps by propagating the
    nearest populated cells so that sparse test-fixture surfaces still render.

NOTE: One discount surface is plotted per validity period (valid_from, valid_to);
the filename lists the maturities that period applies to. This assumes all maturities
share one surface per period (discount_pattern_id is always 'uniform' today). If SBAB
ever prices maturities differently, they would need to be plotted separately.
The main fragility is if SBAB's API changes format or adds pricing dimensions
beyond (LTV, VOL) - step 1 should catch that.
"""
import shutil

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

from io_contracts import VALID_MATURITIES, CURRENT_DISCOUNT_SURFACE_PNG, data_dir


def fill_sparse_surface(df):
    """
    Fill NaN values in a sparse surface DataFrame using bi-directional propagation.

    Strategy: For sparse data (test fixtures), fill empty cells by propagating
    values from nearest populated cells along both axes.

    Args:
        df: DataFrame with possible NaN values

    Returns:
        DataFrame with NaN values filled
    """
    if df.isna().sum().sum() == 0:
        return df  # No NaN values, return as-is

    filled = df.copy()

    # First fill along columns (within each row) - forward then backward
    filled = filled.ffill(axis=1).bfill(axis=1)

    # Then fill along rows (within each column) - forward then backward
    filled = filled.ffill(axis=0).bfill(axis=0)

    return filled


def generate_discount_surface_plot(discount_df, valid_from, valid_to, save_dir, maturities=None, is_uniform=True):
    """
    Generate heatmap for a single discount surface pattern.

    BIJECTION: One call to this function → one PNG file
    Filename format: discount_surface_from_{date}_to_{date}_for_{maturities}_months.png
    Example: discount_surface_from_20251210_to_current_for_3_12_24_36_48_60_84_120_months.png

    Args:
        discount_df: DataFrame with VOLUME bins as index (rows), LTV bins as columns
        valid_from: str, start date of validity period
        valid_to: str, end date ('current' or date)
        save_dir: Path object for the surface's visualization folder
        maturities: List of maturity months that use this discount surface
        is_uniform: If True, all maturities use this pattern (use simple filename)

    Returns:
        Path to saved PNG file
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 8))

    # Fill sparse data (for test fixtures with limited data points)
    discount_df_filled = fill_sparse_surface(discount_df)

    # Round to 2 decimal places for display
    discount_df_rounded = np.round(discount_df_filled, 2)

    sns.heatmap(
        discount_df_rounded,
        annot=True,
        fmt='.2f',
        cmap='RdYlGn',  # Green=high discount (good), Red=low discount (bad)
        cbar_kws={'label': 'Discount (percentage points)'},
        ax=ax
    )

    # Build title with validity and maturity info
    validity_str = f"{valid_from} to {valid_to}"
    title = f'SBAB Discount Surface\nValid: {validity_str}'

    # Add maturity info as subtitle (shows which maturities use this pattern)
    if maturities:
        maturity_str = ', '.join(f'{m}m' for m in sorted(maturities))
        title += f'\nApplies to: {maturity_str}'

    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel('LTV Ratio', fontsize=12)
    ax.set_ylabel('Loan Amount (Volume Bin)', fontsize=12)

    # Generate filename matching docstring format exactly
    valid_from_nodash = valid_from.replace('-', '')
    valid_to_nodash = valid_to.replace('-', '') if valid_to != 'current' else 'current'
    mat_suffix = '_'.join(str(m) for m in sorted(maturities))
    filename = f'discount_surface_from_{valid_from_nodash}_to_{valid_to_nodash}_for_{mat_suffix}_months.png'

    plt.tight_layout()
    save_path = save_dir / filename
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

    if valid_to == 'current':
        # Stable-named copy for the README, which can't follow the dated filename
        shutil.copyfile(save_path, save_dir / CURRENT_DISCOUNT_SURFACE_PNG)

    return save_path


def generate_price_plot(price_df, maturity_months, valid_from, valid_to, save_dir):
    """
    Generate heatmap for actual prices at a specific maturity.

    Args:
        price_df: DataFrame with VOLUME bins as index (rows), LTV bins as columns
                 Upper-left = smallest volume & LTV
                 Lower-right = largest volume & LTV
        maturity_months: int (e.g., 3, 12, 24)
        valid_from, valid_to: validity period
        save_dir: Path object for the surface's visualization folder

    Returns:
        Path to saved PNG file
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 8))

    # Fill sparse data (for test fixtures with limited data points)
    price_df_filled = fill_sparse_surface(price_df)

    # Round to 2 decimal places for display
    price_df_rounded = np.round(price_df_filled, 2)

    sns.heatmap(
        price_df_rounded,
        annot=True,
        fmt='.2f',
        cmap='RdYlGn_r',  # Red=high rates (bad), Green=low rates (good)
        cbar_kws={'label': 'Interest Rate (%)'},
        ax=ax
    )

    validity_str = f"{valid_from} to {valid_to}"
    ax.set_title(f'SBAB Interest Rates - {maturity_months} Month Maturity\nValid: {validity_str}',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('LTV Ratio', fontsize=12)  # LTV on X-axis (columns)
    ax.set_ylabel('Loan Amount (Volume Bin)', fontsize=12)  # Volume on Y-axis (rows)

    plt.tight_layout()
    # Date in filename = TODAY (when snapshot was taken), preserves history
    date_str = date.today().strftime('%Y%m%d')
    save_path = save_dir / f'pricing_surface_{date_str}_for_{maturity_months}m.png'
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()

    return save_path


def generate_surface_visualizations(surface_record):
    """
    Generate all visualizations for a surface record.

    BIJECTION: len(discount_surfaces) == number of discount surface PNGs generated

    Args:
        surface_record: dict with structure:
            {
                'valid_from': '2025-01-08',
                'valid_to': 'current',
                'discount_surfaces': [  # One entry per unique pattern
                    {'df': discount_df, 'maturities': [3, 12, 24, ...]},
                    # ... more if non-uniform
                ],
                'prices': {
                    3: price_df_3m,
                    12: price_df_12m,
                    # ... for all 8 maturities
                }
            }

    Returns:
        Path to the visualizations directory
    """
    valid_from = surface_record['valid_from']
    valid_to = surface_record['valid_to']

    # FLAT structure - all visualizations in data/visualizations/
    save_dir = data_dir() / 'visualizations'

    print(f"  Generating visualizations in {save_dir}")

    # Handle both old format (single 'discount_surface') and new format (list 'discount_surfaces')
    discount_surfaces = surface_record.get('discount_surfaces')
    if discount_surfaces is None:
        # Legacy format - single discount surface
        discount_surfaces = [{
            'df': surface_record['discount_surface'],
            'maturities': list(surface_record['prices'].keys())
        }]

    is_uniform = len(discount_surfaces) == 1

    # Generate one PNG per unique discount pattern (BIJECTION)
    for ds in discount_surfaces:
        discount_path = generate_discount_surface_plot(
            ds['df'],
            valid_from,
            valid_to,
            save_dir,
            maturities=ds['maturities'],
            is_uniform=is_uniform
        )
        mat_str = ', '.join(f'{m}m' for m in sorted(ds['maturities']))
        print(f"    ✓ Discount surface ({mat_str}): {discount_path.name}")

    # Generate price plots for all maturities
    for maturity, price_df in surface_record['prices'].items():
        price_path = generate_price_plot(
            price_df,
            maturity,
            valid_from,
            valid_to,
            save_dir
        )
        print(f"    ✓ Price {maturity:3d}m: {price_path.name}")

    return save_dir


def regenerate_vital_visualizations(disc_csv_path=None, list_rates_csv_path=None):
    """
    Regenerate all visualization PNGs from CSV data.

    Main entry point for steps 3b and 6h.

    Args:
        disc_csv_path: Path to discount_surfaces.csv (default: data/discount_surfaces.csv)
        list_rates_csv_path: Path to list_rates.csv (default: data/list_rates.csv)
    """

    if disc_csv_path is None:
        disc_csv_path = data_dir() / 'discount_surfaces.csv'
    if list_rates_csv_path is None:
        list_rates_csv_path = data_dir() / 'list_rates.csv'

    disc_df = pd.read_csv(disc_csv_path)
    list_rates_df = pd.read_csv(list_rates_csv_path)

    # Clean viz directory before regeneration. This function recreates ALL PNGs
    # from CSV state, so any pre-existing PNG not regenerated is stale.
    viz_dir = data_dir() / 'visualizations'
    if viz_dir.exists():
        stale_pngs = list(viz_dir.glob('*.png'))
        if stale_pngs:
            print(f"  Cleaning {len(stale_pngs)} existing PNGs before regeneration")
            for png in stale_pngs:
                png.unlink()

    # Get current list rates (valid_to is empty)
    current_rates = list_rates_df[list_rates_df['valid_to'].isna() | (list_rates_df['valid_to'] == '')]
    list_rates = dict(zip(current_rates['maturity'], current_rates['list_rate']))

    # Group by validity period
    disc_df['valid_to_filled'] = disc_df['valid_to'].fillna('').replace('', 'current')
    grouped = disc_df.groupby(['valid_from', 'valid_to_filled'])

    print(f"Generating visualizations for {len(grouped)} validity periods...")

    for (valid_from, valid_to), group_df in grouped:
        print(f"\nProcessing: {valid_from} to {valid_to}")

        # Pivot to get discount surface as DataFrame (rows=vol_bin, cols=ltv_bin)
        pivot_df = group_df.pivot_table(
            index='vol_bin',
            columns='ltv_bin',
            values='discount',
            aggfunc='first'
        )

        # Determine which maturities use this surface
        maturities_used = []
        for m in VALID_MATURITIES:
            col = f'used_for_{m}m'
            if col in group_df.columns and group_df[col].any():
                maturities_used.append(m)

        # Build price surfaces ONLY for current period (we don't have historical list rates)
        prices = {}
        if valid_to == 'current':
            for m in maturities_used:
                if m in list_rates:
                    prices[m] = list_rates[m] - pivot_df

        surface_record = {
            'valid_from': valid_from,
            'valid_to': valid_to,
            'discount_surfaces': [{'df': pivot_df, 'maturities': maturities_used}],
            'prices': prices
        }

        generate_surface_visualizations(surface_record)

    print("\nDone.")


# =============================================================================
# List Rate History Plots (temporal line plots, email-only)
# =============================================================================

def _build_daily_rate_df(list_df, disc_df, start, end):
    """Build a daily-resolution DataFrame with list rates and max discounts.

    One row per day in [start, end]. For each maturity, two columns:
        list_{m}m  — the list rate in effect that day
        disc_{m}m  — the max discount in effect that day

    Rates and discounts are forward-filled from their valid_from dates.
    """

    days = pd.date_range(start, end, freq='D')
    df = pd.DataFrame(index=days)

    # List rates: for each maturity, set rate at valid_from, forward-fill
    for m in VALID_MATURITIES:
        rows = list_df[list_df['maturity'] == m].copy()
        rows['vf'] = pd.to_datetime(rows['valid_from'])
        col = f'list_{m}m'
        df[col] = np.nan
        for _, row in rows.iterrows():
            if row['vf'] <= df.index[-1]:
                df.loc[df.index >= row['vf'], col] = row['list_rate']

    # Max discount per maturity per era
    disc = disc_df.copy()
    disc['vf'] = pd.to_datetime(disc['valid_from'])
    for vf, era_df in disc.groupby('vf'):
        for m in VALID_MATURITIES:
            col_flag = f'used_for_{m}m'
            col_disc = f'disc_{m}m'
            if col_disc not in df.columns:
                df[col_disc] = np.nan
            if col_flag in era_df.columns:
                applicable = era_df[era_df[col_flag] == 1]
                if not applicable.empty:
                    max_disc = applicable['discount'].max()
                    if vf <= df.index[-1]:
                        df.loc[df.index >= vf, col_disc] = max_disc

    return df


def _plot_all_maturities(df, save_dir, suffix, title):
    """Plot list rates for all maturities on one chart.

    Filename: list_rate_history_{suffix}.png
    """

    fig, ax = plt.subplots(figsize=(12, 6))

    for i, m in enumerate(VALID_MATURITIES):
        col = f'list_{m}m'
        if col in df.columns and df[col].notna().any():
            ax.plot(df.index, df[col], label=f'{m}m', color=f'C{i}', linewidth=1.5)

    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Interest Rate (%)')
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()

    plt.tight_layout()
    save_path = save_dir / f'list_rate_history_{suffix}.png'
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"    list_rate_history_{suffix}.png")
    return save_path


def _plot_single_maturity(df, maturity, save_dir):
    """Plot list rate, best available rate, and max discount for a single maturity.

    Three lines:
        - List Rate (solid blue, left y-axis)
        - Best Rate = list_rate - max_discount (dashed green, left y-axis)
        - Max Discount (dotted orange, right y-axis)

    Filename: list_rate_history_{maturity}m.png
    """
    list_col = f'list_{maturity}m'
    disc_col = f'disc_{maturity}m'

    if list_col not in df.columns or df[list_col].isna().all():
        return None

    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(df.index, df[list_col], label='List Rate',
            color='tab:blue', linewidth=2)

    if disc_col in df.columns and df[disc_col].notna().any():
        best_rate = df[list_col] - df[disc_col]
        ax.plot(df.index, best_rate, label='Best Rate (after max discount)',
                color='tab:green', linewidth=2, linestyle='--')

        # Max discount on secondary y-axis (different scale)
        ax2 = ax.twinx()
        ax2.plot(df.index, df[disc_col], label='Max Discount',
                 color='tab:orange', linewidth=1.5, linestyle=':')
        ax2.set_ylabel('Max Discount (%)', color='tab:orange')
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.2f}'))
        ax2.tick_params(axis='y', labelcolor='tab:orange')

        # Combine legends from both axes
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9)

    # Add headroom so legend doesn't overlap data
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(ymin, ymax + (ymax - ymin) * 0.2)
    if disc_col in df.columns and df[disc_col].notna().any():
        y2min, y2max = ax2.get_ylim()
        ax2.set_ylim(y2min, y2max + (y2max - y2min) * 0.2)

    ax.set_title(f'SBAB {maturity}m \u2014 List Rate vs Best Available Rate',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Interest Rate (%)')
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()

    plt.tight_layout()
    save_path = save_dir / f'list_rate_history_{maturity}m.png'
    plt.savefig(save_path, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"    list_rate_history_{maturity}m.png")
    return save_path


def generate_list_rate_history_plots(list_rates_csv_path=None, disc_csv_path=None):
    """Generate temporal line plots of list rates and best available rates.

    Produces (all email-only, not version-tracked):
        - list_rate_history_full.png: All maturities, full history to today
        - list_rate_history_1yr.png: All maturities, last 365 days
        - list_rate_history_{m}m.png: Per-maturity with list rate + best rate
    """

    if list_rates_csv_path is None:
        list_rates_csv_path = data_dir() / 'list_rates.csv'
    if disc_csv_path is None:
        disc_csv_path = data_dir() / 'discount_surfaces.csv'

    save_dir = data_dir() / 'visualizations'
    save_dir.mkdir(parents=True, exist_ok=True)

    list_df = pd.read_csv(list_rates_csv_path)
    disc_df = pd.read_csv(disc_csv_path)

    today = date.today()
    earliest = pd.to_datetime(list_df['valid_from']).min().date()

    # Build daily DataFrames for each date range
    df_full = _build_daily_rate_df(list_df, disc_df, earliest, today)

    start_1yr = today - timedelta(days=364)
    df_1yr = df_full.loc[df_full.index >= pd.Timestamp(start_1yr)]

    print("\nGenerating list rate history plots...")

    # Plot A: Full history
    _plot_all_maturities(df_full, save_dir, 'full', 'SBAB List Rates — Full History')

    # Plot B: Last 365 days
    _plot_all_maturities(df_1yr, save_dir, '1yr', 'SBAB List Rates \u2014 Last 12 Months')

    # Plot C: Per-maturity with best rate (full history)
    for m in VALID_MATURITIES:
        _plot_single_maturity(df_full, m, save_dir)

    print("  List rate history plots: done")
