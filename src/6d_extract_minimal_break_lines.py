"""
Step 6d: Extract Minimal Break Lines (DEEP RUN)

Analyzes the rasterized discount surfaces to find where prices change. A
"break line" is an LTV or VOL value where the discount changes on one side
vs the other.

Takes the UNION across all 8 maturities: if ANY maturity has a break at
LTV=75%, that's a break line even if other maturities don't break there.

Also adds any PROMINENT BOUNDARIES set in io_contracts.py (none by default); these
are always included, even if SBAB doesn't have a price break there. Prominent
boundaries are user-input proxies for LTV/VOL break-lines that are important to
the user's goals.

INPUTS:
    - Tuple from step 6c: (rasterized_surfaces, ltv_probes, vol_probes)
        - rasterized_surfaces: Dict of {maturity: 2D np.ndarray}
        - ltv_probes: sorted list of LTV values
        - vol_probes: sorted list of VOL values

OUTPUTS:
    - dict: {'ltv_breaks': set of floats, 'vol_breaks': set of ints}
    - These break lines define where bin boundaries should be

I/O CONTRACT (from io_contracts.py):
    Input:  assert_rasterized_surfaces(rasterized_surfaces)
    Output: assert_break_lines(break_lines)
    Note:   assert_break_lines validates prominent boundaries are included

PROMINENT BOUNDARIES (from io_contracts.py):
    PROMINENT_LTV_BREAKS and PROMINENT_VOL_BREAKS, both empty by default

BREAK DETECTION ALGORITHM:
    For each adjacent pair of probe points, check if discounts differ.
    If discount[i] != discount[i+1], the midpoint between them is a break line.

CONTEXT:
    - This is step 4 of the DEEP RUN ONLY section
    - Output feeds into 6e (make bins) and 6i (update boundaries_minimal.yaml)
"""
from io_contracts import (
    assert_rasterized_surfaces,
    assert_break_lines,
    VALID_MATURITIES,
    PROMINENT_LTV_BREAKS,
    PROMINENT_VOL_BREAKS,
    rate_precision,
)


def find_ltv_breaks(rasterized_surfaces, ltv_probes, vol_probes):
    """
    Find LTV values where discounts change (scanning vertically down each column).

    Returns set of LTV values where breaks occur (midpoint between probe pairs).
    """
    # Detect precision from surface values
    all_vals = [v for m in VALID_MATURITIES for v in rasterized_surfaces[m].ravel()]
    dp = rate_precision(all_vals)
    ltv_breaks = set()

    for maturity in VALID_MATURITIES:
        surface = rasterized_surfaces[maturity]

        # For each VOL column, scan down the LTV rows
        for vol_idx in range(len(vol_probes)):
            for ltv_idx in range(len(ltv_probes) - 1):
                val_curr = surface[ltv_idx, vol_idx]
                val_next = surface[ltv_idx + 1, vol_idx]

                # If values differ, there's a break between these probes
                if round(val_curr, dp) != round(val_next, dp):
                    # Break is at the midpoint between the two probe LTV values
                    break_ltv = (ltv_probes[ltv_idx] + ltv_probes[ltv_idx + 1]) / 2
                    ltv_breaks.add(round(break_ltv, 4))

    return ltv_breaks


def find_vol_breaks(rasterized_surfaces, ltv_probes, vol_probes):
    """
    Find VOL values where discounts change (scanning horizontally across each row).

    Returns set of VOL values where breaks occur (midpoint between probe pairs).
    """
    # Detect precision from surface values
    all_vals = [v for m in VALID_MATURITIES for v in rasterized_surfaces[m].ravel()]
    dp = rate_precision(all_vals)
    vol_breaks = set()

    for maturity in VALID_MATURITIES:
        surface = rasterized_surfaces[maturity]

        # For each LTV row, scan across the VOL columns
        for ltv_idx in range(len(ltv_probes)):
            for vol_idx in range(len(vol_probes) - 1):
                val_curr = surface[ltv_idx, vol_idx]
                val_next = surface[ltv_idx, vol_idx + 1]

                # If values differ, there's a break between these probes
                if round(val_curr, dp) != round(val_next, dp):
                    # Break is at the midpoint between the two probe VOL values
                    break_vol = (vol_probes[vol_idx] + vol_probes[vol_idx + 1]) / 2
                    vol_breaks.add(int(round(break_vol)))

    return vol_breaks


def extract_minimal_break_lines(rasterized_surfaces, ltv_probes, vol_probes):
    """
    Extract minimal break lines from rasterized discount surfaces.

    Args:
        rasterized_surfaces: Dict of {maturity: 2D np.ndarray}
        ltv_probes: sorted list of LTV values
        vol_probes: sorted list of VOL values

    Returns:
        dict: {'ltv_breaks': set of floats, 'vol_breaks': set of ints}
    """
    assert_rasterized_surfaces(rasterized_surfaces)

    # Find data-driven breaks
    ltv_breaks = find_ltv_breaks(rasterized_surfaces, ltv_probes, vol_probes)
    vol_breaks = find_vol_breaks(rasterized_surfaces, ltv_probes, vol_probes)

    # Add prominent boundaries (none by default)
    ltv_breaks = ltv_breaks | PROMINENT_LTV_BREAKS
    vol_breaks = vol_breaks | PROMINENT_VOL_BREAKS

    break_lines = {
        'ltv_breaks': ltv_breaks,
        'vol_breaks': vol_breaks
    }

    assert_break_lines(break_lines)
    return break_lines
