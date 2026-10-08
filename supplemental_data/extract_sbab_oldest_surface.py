"""
extract_sbab_oldest_surface.py
==============================
Generates three progressively richer CSV representations of the
2022-09-26 SBAB discount surface, building from simple to full.

  out/sbab_3col.csv  –  ltv_bin | vol_bin | discount
  out/sbab_5col.csv  –  ltv_bin_idx | ltv_bin | vol_bin_idx | vol_bin | discount
  out/sbab_7col.csv  –  ... + ltv_lower | ltv_upper | vol_lower | vol_upper
"""

import csv
import math
import os

OUT = "out"
os.makedirs(OUT, exist_ok=True)

INF = math.inf

# ── Bin definitions ───────────────────────────────────────────────────────────

VOL_BINS = [
    # idx  label               lower   upper
    ( 1,  "0-0.499M",          0,         499_000),
    ( 2,  "0.5M-0.599M",       500_000,   599_000),
    ( 3,  "0.6M-0.699M",       600_000,   699_000),
    ( 4,  "0.7M-0.799M",       700_000,   799_000),
    ( 5,  "0.8M-0.899M",       800_000,   899_000),
    ( 6,  "0.9M-0.999M",       900_000,   999_000),
    ( 7,  "1.0M-1.499M",     1_000_000, 1_499_000),
    ( 8,  "1.5M-1.999M",     1_500_000, 1_999_000),
    ( 9,  "2.0M-2.499M",     2_000_000, 2_499_000),
    (10,  "2.5M-2.999M",     2_500_000, 2_999_000),
    (11,  "3.0M-3.499M",     3_000_000, 3_499_000),
    (12,  "3.5M-3.999M",     3_500_000, 3_999_000),
    (13,  "4.0M-4.499M",     4_000_000, 4_499_000),
    (14,  "4.5M-4.999M",     4_500_000, 4_999_000),
    (15,  "5.0M-6.999M",     5_000_000, 6_999_000),
    (16,  "7.0M+",           7_000_000, INF),
]

LTV_BINS = [
    # idx  label        lower   upper
    ( 1,  "0-49.99%",    0,     49.99),
    ( 2,  "50-59.99%",  50,     59.99),
    ( 3,  "60-64.99%",  60,     64.99),
    ( 4,  "65-69.99%",  65,     69.99),
    ( 5,  "70-74.99%",  70,     74.99),
    ( 6,  "75-75.99%",  75,     75.99),
    ( 7,  "76-76.99%",  76,     76.99),
    ( 8,  "77-77.99%",  77,     77.99),
    ( 9,  "78-78.99%",  78,     78.99),
    (10,  "79-79.99%",  79,     79.99),
    (11,  "80-84.99%",  80,     84.99),
    (12,  "85%+",       85,     INF),
]

# ── Discount matrix (rows = Vol, cols = LTV) ──────────────────────────────────
# Values from the author's 2022-09-26 extraction with the 2022 scraper; 0 = no discount.

DISCOUNTS = [
    #  1      2      3      4      5      6      7      8      9     10     11     12
    [ 0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00],  #  1
    [-0.06, -0.06, -0.03,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00],  #  2
    [-0.12, -0.12, -0.06, -0.03,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00],  #  3
    [-0.18, -0.18, -0.12, -0.07, -0.03,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.00],  #  4
    [-0.23, -0.23, -0.18, -0.13, -0.08, -0.05, -0.03,  0.00,  0.00,  0.00,  0.00,  0.00],  #  5
    [-0.29, -0.29, -0.24, -0.19, -0.14, -0.11, -0.08, -0.06, -0.03,  0.00,  0.00,  0.00],  #  6
    [-0.35, -0.35, -0.30, -0.25, -0.20, -0.17, -0.14, -0.11, -0.08, -0.05,  0.00,  0.00],  #  7
    [-0.37, -0.37, -0.32, -0.27, -0.22, -0.17, -0.14, -0.11, -0.08, -0.05,  0.00,  0.00],  #  8
    [-0.40, -0.40, -0.37, -0.32, -0.27, -0.22, -0.17, -0.14, -0.11, -0.08,  0.00,  0.00],  #  9
    [-0.40, -0.40, -0.40, -0.35, -0.32, -0.27, -0.22, -0.17, -0.13, -0.10, -0.05,  0.00],  # 10
    [-0.40, -0.40, -0.40, -0.40, -0.35, -0.30, -0.25, -0.20, -0.15, -0.10, -0.05,  0.00],  # 11
    [-0.43, -0.43, -0.43, -0.43, -0.37, -0.32, -0.27, -0.22, -0.18, -0.13, -0.10,  0.00],  # 12
    [-0.43, -0.43, -0.43, -0.43, -0.37, -0.32, -0.27, -0.22, -0.18, -0.13, -0.10,  0.00],  # 13
    [-0.45, -0.45, -0.45, -0.45, -0.40, -0.35, -0.30, -0.25, -0.20, -0.15, -0.12,  0.00],  # 14
    [-0.45, -0.45, -0.45, -0.45, -0.40, -0.35, -0.30, -0.25, -0.20, -0.15, -0.12,  0.00],  # 15
    [-0.45, -0.45, -0.45, -0.45, -0.40, -0.35, -0.30, -0.25, -0.20, -0.15, -0.12,  0.00],  # 16
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt(v):
    """Format a bound: 'inf' for infinity, otherwise a plain number."""
    return "inf" if math.isinf(v) else v


def all_cells():
    """Yield one dict per (ltv_bin, vol_bin) cell with every field."""
    for (vi, vl, vlo, vhi), disc_row in zip(VOL_BINS, DISCOUNTS):
        for (li, ll, llo, lhi), discount in zip(LTV_BINS, disc_row):
            yield {
                "ltv_bin_idx": li,
                "ltv_bin":     ll,
                "ltv_lower":   llo,
                "ltv_upper":   fmt(lhi),
                "vol_bin_idx": vi,
                "vol_bin":     vl,
                "vol_lower":   vlo,
                "vol_upper":   fmt(vhi),
                "discount":    discount,
            }


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path}  ({sum(1 for _ in open(path)) - 1} data rows)")


# ── Write the three files ─────────────────────────────────────────────────────

cells = list(all_cells())

print("Generating CSVs …")

write_csv(
    f"{OUT}/sbab_3col.csv",
    ["ltv_bin", "vol_bin", "discount"],
    cells,
)

write_csv(
    f"{OUT}/sbab_5col.csv",
    ["ltv_bin_idx", "ltv_bin", "vol_bin_idx", "vol_bin", "discount"],
    cells,
)

write_csv(
    f"{OUT}/sbab_7col.csv",
    ["ltv_bin_idx", "ltv_bin", "ltv_lower", "ltv_upper",
     "vol_bin_idx", "vol_bin", "vol_lower",  "vol_upper", "discount"],
    cells,
)

print("Done.")
