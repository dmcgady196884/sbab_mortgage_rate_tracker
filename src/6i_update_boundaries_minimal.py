"""
Step 6i: Update Boundaries (DEEP RUN)

Updates boundaries_minimal.yaml with the newly discovered bin structure.
This ensures future light runs (step 1) probe the right points to detect
any subsequent pricing changes.

The updated boundaries_minimal.yaml will be committed as part of the PR,
so future daily runs use the correct probe grid.

INPUTS:
    - Bins from step 6e
      dict: {'LTV_BINS': [...], 'VOL_BINS': [...], 'LTV_LABELS': [...], 'VOL_LABELS': [...]}

OUTPUTS:
    - Updated boundaries_minimal.yaml
    - bool: whether the bin structure (ltv_bins/vol_bins) actually changed
      from what was previously on file. True if boundaries_minimal.yaml
      didn't exist yet (nothing to compare against) or the bins genuinely
      differ; False only if the new bins are identical to the old ones
      (e.g. a deep run triggered by a pure value mismatch, not a new break).

I/O CONTRACT (from io_contracts.py):
    Input:  assert_bins(bins)
    Output: YAML file with correct structure

YAML FORMAT (boundaries_minimal.yaml):
    metadata:
      last_updated: 'YYYY-MM-DD'
      source: deep_scraper
      notes: Auto-updated from deep run on YYYYMMDD
    vol_bins: [0, 500000, 1000000, ...]
    vol_labels: ['(0-0.5)M', '(0.5-1)M', ...]
    ltv_bins: [0, 0.5, 0.6, ...]
    ltv_labels: ['(0-50)%', '(50-60)%', ...]

CONTEXT:
    - This is step 9 of the DEEP RUN ONLY section
    - The updated YAML becomes part of the PR opened in step 7
    - Step 1 reads this file to generate its probe grid
"""
from datetime import date
from pathlib import Path

import yaml

from io_contracts import assert_bins, SENTINEL_LTV, data_dir


def update_boundaries_minimal(bins, yaml_path=None):
    """
    Update boundaries_minimal.yaml with new bin structure.

    Args:
        bins: Dict from step 6e with LTV_BINS, VOL_BINS, LTV_LABELS, VOL_LABELS
        yaml_path: Optional path to boundaries_minimal.yaml

    Returns:
        bool: True if ltv_bins/vol_bins differ from what was previously on
        file (or the file didn't exist yet), False if this deep run
        rediscovered the exact same bin structure.
    """
    assert_bins(bins)

    if yaml_path is None:
        yaml_path = data_dir() / 'boundaries_minimal.yaml'
    yaml_path = Path(yaml_path)

    today_str = date.today().strftime('%Y-%m-%d')
    today_compact = date.today().strftime('%Y%m%d')

    # Convert numpy types to native Python types for YAML serialization
    ltv_bins = [float(x) for x in bins['LTV_BINS']]
    vol_bins = [int(x) for x in bins['VOL_BINS']]

    # Replace 1.0 with SENTINEL_LTV for LTV (matches existing convention)
    ltv_bins = [SENTINEL_LTV if x == 1.0 else x for x in ltv_bins]

    # Compare against what's currently on file, before overwriting it
    if yaml_path.exists():
        with open(yaml_path) as f:
            old_content = yaml.safe_load(f) or {}
        bins_changed = (old_content.get('ltv_bins') != ltv_bins
                         or old_content.get('vol_bins') != vol_bins)
    else:
        bins_changed = True

    yaml_content = {
        'metadata': {
            'last_updated': today_str,
            'source': 'deep_scraper',
            'notes': f'Auto-updated from deep run on {today_compact}'
        },
        'vol_bins': vol_bins,
        'vol_labels': bins['VOL_LABELS'],
        'ltv_bins': ltv_bins,
        'ltv_labels': bins['LTV_LABELS'],
    }

    with open(yaml_path, 'w') as f:
        yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False)

    return bins_changed
