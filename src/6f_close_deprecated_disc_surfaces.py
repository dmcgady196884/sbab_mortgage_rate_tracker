"""
Step 6f: Close Deprecated Discount Surfaces (DEEP RUN)

Updates discount_surfaces.csv: for all rows where valid_to is empty (i.e.,
the "current" surface), sets valid_to = yesterday. This "closes" the old surface,
marking it as no longer current.

WHY YESTERDAY: If we discover today that prices changed, the old surface was
valid through yesterday. Today is when the new surface becomes valid. This
ensures no overlap or gap in validity periods.

After this step runs, there will be NO current discount surface in the CSV.
Step 6g must run immediately after to create the new current surface.

INPUTS:
    - data/discount_surfaces.csv

OUTPUTS:
    - Modified discount_surfaces.csv (old rows now have valid_to set to yesterday)
    - Returns count of rows closed (int)

I/O CONTRACT (from io_contracts.py):
    Input:  File must exist
    Output: All previously-current rows now have valid_to set

FILE FORMAT (discount_surfaces.csv):
    columns: [ltv_bin, vol_bin, discount, valid_from, valid_to,
              discount_pattern_id, used_for_3m, used_for_12m, ..., used_for_120m]
    - valid_from: YYYY-MM-DD string, date surface became active
    - valid_to: YYYY-MM-DD string or empty, date surface was superseded

CONTEXT:
    - This is step 6 of the DEEP RUN ONLY section
    - Must be followed immediately by 6g (create new surface)
    - Together, 6f + 6g implement atomic "close old, open new" transition
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from io_contracts import data_dir


def close_deprecated_disc_surfaces(csv_path=None):
    """
    Close all current discount surfaces by setting valid_to = yesterday.

    Args:
        csv_path: Optional path to discount_surfaces.csv

    Returns:
        int: Number of rows closed
    """
    if csv_path is None:
        csv_path = data_dir() / 'discount_surfaces.csv'

    df = pd.read_csv(csv_path)
    df['valid_to'] = df['valid_to'].astype('object')  # Allow string assignment

    yesterday_str = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Find rows where valid_to is empty (current surfaces)
    current_mask = df['valid_to'].isna() | (df['valid_to'] == '')
    rows_to_close = current_mask.sum()

    # Set valid_to = yesterday for all current rows
    df.loc[current_mask, 'valid_to'] = yesterday_str

    df.to_csv(csv_path, index=False)

    return rows_to_close
