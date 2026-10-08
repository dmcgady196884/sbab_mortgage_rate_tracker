"""
Shared fixtures for the SBAB pipeline test suite.

This conftest is shared by two kinds of tests:
  - Fast, fixture-based unit tests (test_assign_bin.py, test_failure_email.py,
    test_scraper_retry.py, test_step7_real_path.py) -- no network, no git, no PRs.
  - Slow/very_slow live-API integration tests, which hit the real SBAB API and
    create real GitHub PRs via the run_pipeline_on_fixture fixture below. Every
    test that triggers a deep run will:
      - Create a feature branch (grid-update-YYYYMMDD-HHMM)
      - Push it to origin
      - Open a PR with "DO NOT MERGE" prefix
    Cleanup closes PRs, deletes branches, and restores data/.

The two autouse fixtures (pipeline_env, save_restore_maturities) apply to
every test in the suite, not just the live-API ones.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'src'))


@pytest.fixture(autouse=True)
def pipeline_env(monkeypatch):
    """Set IS_TEST=true for all tests so PRs/emails get DO NOT MERGE prefix."""
    monkeypatch.setenv('IS_TEST', 'true')


@pytest.fixture(autouse=True)
def save_restore_maturities():
    """Save VALID_MATURITIES before each test, restore after."""
    from io_contracts import VALID_MATURITIES
    original = list(VALID_MATURITIES)
    yield
    VALID_MATURITIES[:] = original


@pytest.fixture()
def run_pipeline_on_fixture():
    """
    Factory fixture: runs the pipeline against a fixture directory.

    Returns a callable: run(scenario_name) -> state dict.
    Handles cleanup: close PR, delete branch, restore data/, switch back.
    """
    original_branch = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    ).stdout.strip()

    created_branches = []
    created_pr_urls = []

    def run(scenario):
        fixture_dir = str(REPO_ROOT / 'data' / 'test_fixtures' / scenario)
        from aleph_null import run_pipeline
        try:
            state = run_pipeline(is_test=True, force_shallow=False, data_dir_override=fixture_dir)
        finally:
            # Always capture branch/PR info for cleanup, even if pipeline crashed.
            # Step 5b may have created a branch and step 7 may have pushed a PR
            # before the crash.
            current = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, cwd=str(REPO_ROOT)
            ).stdout.strip()
            if current != original_branch:
                created_branches.append(current)

            # Check for open PRs from this branch
            if current != original_branch:
                result = subprocess.run(
                    ['gh', 'pr', 'view', current, '--json', 'url'],
                    capture_output=True, text=True, cwd=str(REPO_ROOT)
                )
                if result.returncode == 0:
                    pr_url = json.loads(result.stdout).get('url')
                    if pr_url:
                        created_pr_urls.append(pr_url)

        # Also capture from state if pipeline succeeded
        if state.get('pr_url') and 'github.com' in str(state.get('pr_url', '')):
            if state['pr_url'] not in created_pr_urls:
                created_pr_urls.append(state['pr_url'])

        return state

    yield run

    # === CLEANUP ===

    # Switch back to original branch
    subprocess.run(
        ['git', 'checkout', original_branch],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )

    # Restore data/ to clean state
    subprocess.run(
        ['git', 'checkout', '--', 'data/'],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )

    # Also restore src/io_contracts.py (maturity tests rewrite VALID_MATURITIES on disk)
    subprocess.run(
        ['git', 'checkout', '--', 'src/io_contracts.py'],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )

    # Close PRs
    for pr_url in created_pr_urls:
        subprocess.run(
            ['gh', 'pr', 'close', pr_url, '--delete-branch'],
            capture_output=True, text=True, cwd=str(REPO_ROOT)
        )

    # Delete local branches
    for branch in created_branches:
        subprocess.run(
            ['git', 'branch', '-D', branch],
            capture_output=True, text=True, cwd=str(REPO_ROOT)
        )

    # Delete remote branches (in case gh pr close --delete-branch missed any)
    for branch in created_branches:
        subprocess.run(
            ['git', 'push', 'origin', '--delete', branch],
            capture_output=True, text=True, cwd=str(REPO_ROOT)
        )
