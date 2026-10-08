"""
Step 6e: Make Bins from Break Lines (DEEP RUN)

Converts break lines into bins. If LTV break lines are at [50%, 60%, 75%, 85%],
then LTV bins are [(0-50%), (50-60%), (60-75%), (75-85%), (85%+)].

The bins define the regions where discount is expected to be uniform. For each
(LTV_bin, VOL_bin, maturity) slice, the discount must be uniform:
    discount[ltv_bin, vol_bin, maturity].unique() has exactly one element.

Different maturities may have different discount values in the same (LTV_bin, VOL_bin).

INPUTS:
    - Break lines from step 6d
      dict: {'ltv_breaks': set of floats, 'vol_breaks': set of ints}

OUTPUTS:
    - dict: {
        'LTV_BINS': list of floats (bin edges, including 0 and 1),
        'VOL_BINS': list of ints (bin edges, including 0 and inf),
        'LTV_LABELS': list of strings (human-readable labels),
        'VOL_LABELS': list of strings (human-readable labels)
      }

I/O CONTRACT (from io_contracts.py):
    Input:  assert_break_lines(break_lines)
    Output: assert_bins(bins)

LABEL FORMAT (must match discount_surfaces.csv conventions):
    LTV: "(0-50)%", "(50-60)%", "(60-65)%", ..., "(85+)%"
    VOL: "(0-0.5)M", "(0.5-0.6)M", "(0.6-0.7)M", ..., "(5+)M"

CONTEXT:
    - This is step 5 of the DEEP RUN ONLY section
    - Output feeds into 6g (create new discount surface rows)
    - These bins also implicitly define what boundaries_minimal.yaml should contain
"""
from io_contracts import assert_break_lines, assert_bins, SENTINEL_VOL


def make_ltv_labels(ltv_bins):
    """
    Generate human-readable LTV bin labels.

    Format: "(0-50)%", "(50-60)%", ..., "(85+)%"
    """
    labels = []
    for i in range(len(ltv_bins) - 1):
        low = ltv_bins[i]
        high = ltv_bins[i + 1]

        # Convert to percentage integers
        # round, not int: int(0.58 * 100) is 57 (floating point)
        low_pct = round(low * 100)
        high_pct = round(high * 100)

        if high >= 1.0:  # Last bin is "X+%"
            labels.append(f"({low_pct}+)%")
        else:
            labels.append(f"({low_pct}-{high_pct})%")

    return labels


def make_vol_labels(vol_bins):
    """
    Generate human-readable VOL bin labels.

    Format: "(0-0.5)M", "(0.5-0.6)M", ..., "(5+)M"
    """
    labels = []
    for i in range(len(vol_bins) - 1):
        low = vol_bins[i]
        high = vol_bins[i + 1]

        # Convert to millions
        low_m = low / 1_000_000
        high_m = high / 1_000_000

        if high >= SENTINEL_VOL:  # Last bin is "X+M"
            labels.append(f"({low_m:g}+)M")
        else:
            labels.append(f"({low_m:g}-{high_m:g})M")

    return labels


def make_bins_from_break_lines(break_lines):
    """
    Convert break lines into bins with edges and labels.

    Args:
        break_lines: dict with 'ltv_breaks' and 'vol_breaks' sets

    Returns:
        dict: {
            'LTV_BINS': list of floats,
            'VOL_BINS': list of ints,
            'LTV_LABELS': list of strings,
            'VOL_LABELS': list of strings
        }
    """
    assert_break_lines(break_lines)

    # Sort break lines and add endpoints
    ltv_breaks = sorted(break_lines['ltv_breaks'])
    vol_breaks = sorted(break_lines['vol_breaks'])

    # LTV bins: 0 at start, 1 at end (representing 100%)
    ltv_bins = [0.0] + ltv_breaks + [1.0]

    # VOL bins: 0 at start, large number at end (representing infinity)
    vol_bins = [0] + vol_breaks + [SENTINEL_VOL]

    # Remove duplicates while preserving order
    ltv_bins = sorted(set(ltv_bins))
    vol_bins = sorted(set(vol_bins))

    # Generate labels
    ltv_labels = make_ltv_labels(ltv_bins)
    vol_labels = make_vol_labels(vol_bins)

    bins = {
        'LTV_BINS': ltv_bins,
        'VOL_BINS': vol_bins,
        'LTV_LABELS': ltv_labels,
        'VOL_LABELS': vol_labels
    }

    assert_bins(bins)
    return bins
