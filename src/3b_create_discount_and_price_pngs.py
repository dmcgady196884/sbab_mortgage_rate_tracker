"""
Step 3b: Create Discount and Price Surface PNGs

Regenerates:
    - ALL discount surface visualizations (for every (valid_from, valid_to) pair)
    - ALL current pricing visualizations (for the valid_to = empty surface only)

No conditional logic - always regenerates. (KISS principle.)

INPUTS:
    - data/discount_surfaces.csv
    - data/list_rates.csv

OUTPUTS:
    - Discount surface heatmap PNGs for ALL (valid_from, valid_to) pairs
      Filename: discount_surface_{valid_from}_{valid_to}_{maturities}_months.png
    - 8 pricing surface heatmap PNGs (one per maturity) for CURRENT surface only
      Filename: pricing_surface_YYYYMMDD_for_Xm.png (date = today, preserves snapshots)
    - List rate history line plots (email-only, not version-tracked)
      Filename: list_rate_history_full.png, list_rate_history_1yr.png,
               list_rate_history_{m}m.png

I/O CONTRACT (from io_contracts.py):
    Inputs are CSV files, not DataFrames passed in memory.
    No formal contract assertion - this step reads from disk and writes PNGs.

IMPLEMENTATION:
    This is a thin wrapper. The actual logic lives in create_price_visualizations.py.
    Both step 3b and step 6h call the SAME function from that module.

NOTES:
1. This step runs on EVERY daily run, not just deep runs.
2. Step 6h is IDENTICAL to this step - both call the same underlying function.
3. The "if_needed" in the old filename was misleading - we always regenerate. KISS.
"""
from create_price_visualizations import regenerate_vital_visualizations, generate_list_rate_history_plots


def create_all_png_visualizations_shallow():
    """Regenerate all discount/pricing surface PNGs and list rate history plots."""
    regenerate_vital_visualizations()
    generate_list_rate_history_plots()
