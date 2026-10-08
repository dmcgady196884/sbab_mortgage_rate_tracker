"""
Step 5b: Open Feature Branch (if deep run triggered)

If step 4 signaled trigger_deep_run = True, this step creates a new git
feature branch. All subsequent file modifications during the deep run
(steps 6e, 6f, 6h) happen on this branch.

This is the FIRST STEP of the DEEP RUN ONLY section.

INPUTS:
    - deep_run_signal from step 4: {'trigger_deep_run': bool, 'reason': str or None}

OUTPUTS:
    - If trigger_deep_run = False: no-op, returns None
    - If trigger_deep_run = True:
        - Creates new git branch: "grid-update-YYYYMMDD-HHMMSS"
        - Returns branch name (str)

I/O CONTRACT (from io_contracts.py):
    Input:  assert_deep_run_signal(deep_run_signal)
    Output: str (branch name) or None

IMPLEMENTATION:
    Uses subprocess to run git commands:
        git checkout -b grid-update-{timestamp}  (YYYYMMDD-HHMMSS)

CONTEXT:
    - If this step creates a branch, steps 6a-6j execute on that branch
    - Step 7 will open a PR from this branch to main (if 6j validates successfully)
    - If 6j fails, step 7 abandons the branch
"""
import subprocess
from datetime import datetime

from io_contracts import assert_deep_run_signal


def open_feature_branch(deep_run_signal):
    """
    Create feature branch if deep run is triggered.

    Args:
        deep_run_signal: from step 4 (dict with 'trigger_deep_run' bool)

    Returns:
        Branch name (str) if created, None otherwise
    """
    assert_deep_run_signal(deep_run_signal)

    if not deep_run_signal['trigger_deep_run']:
        return None

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    branch_name = f'grid-update-{timestamp}'

    subprocess.run(['git', 'checkout', '-b', branch_name], check=True)

    return branch_name
