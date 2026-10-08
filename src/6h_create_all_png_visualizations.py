"""
Step 6h: Create All PNG Visualizations (DEEP RUN)

Identical to step 3b. Regenerates ALL visualization PNGs from the current
state of the CSV files. This ensures visualizations reflect the newly
created discount surface.

Regenerates:
    - ALL discount surface visualizations (for every (valid_from, valid_to) pair)
    - ALL current pricing visualizations (for the valid_to = empty surface only)

INPUTS:
    - data/discount_surfaces.csv
    - data/list_rates.csv

OUTPUTS:
    - Discount surface heatmap PNGs for ALL historical surfaces
    - 8 pricing surface heatmap PNGs (one per maturity) for CURRENT surface only
      Filename: pricing_surface_YYYYMMDD_for_Xm.png (date = today, preserves snapshots)
    - No return value (side effect: file creation)

I/O CONTRACT:
    Input:  data/discount_surfaces.csv and data/list_rates.csv, read as-is
            (no io_contracts validator is called here)
    Output: N/A (creates PNG files)

OUTPUT LOCATION:
    data/visualizations/ (FLAT structure, all files in one folder)

IMPLEMENTATION:
    This is a thin wrapper. The actual visualization logic lives in:
        create_price_visualizations.py :: regenerate_vital_visualizations()

CONTEXT:
    - This is step 8 of the DEEP RUN ONLY section
    - Identical to step 3b (KISS principle - same code path)
"""
from create_price_visualizations import regenerate_vital_visualizations


def create_all_png_visualizations():
    """Regenerate all visualization PNGs from current CSV state."""
    regenerate_vital_visualizations()
