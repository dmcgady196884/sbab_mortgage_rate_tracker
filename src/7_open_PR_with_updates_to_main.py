"""
Step 7: Open PR with Updates to Main (DEEP RUN)

If deep run completed successfully (step 6j passed), opens a PR from the
feature branch to main. If 6j failed (catastrophic), this step is skipped
and the branch is abandoned.

INPUTS:
    - Feature branch from step 5b (e.g., "grid-update-YYYYMMDD-HHMM")
    - Validation result from step 6j

OUTPUTS:
    - If validation passed: GitHub PR URL
    - If validation failed: None (step skipped, not an error)
    - If commit/push/gh pr create fails: raises RuntimeError with the real output
      (not swallowed to None -- see _run_pipeline_or_email_failure in aleph_null.py)
    - Side effect: PR created on GitHub (if passed)

I/O CONTRACT (from io_contracts.py):
    Input:  assert_validation_result(validation_result)
    Output: str (PR URL) or None (validation failed); raises RuntimeError on
            a git/gh operation failure

PR CONTENTS (files modified on feature branch):
    - data/discount_surfaces.csv (old rows closed, new rows added)
    - data/list_rates.csv (if list rates changed)
    - boundaries_minimal.yaml (updated break lines)
    - data/visualizations/*.png (regenerated)
    - src/io_contracts.py (if VALID_MATURITIES changed)
    - data/test_fixtures/generate_fixtures.py, README.md (fixture-regen TODO,
      non-test runs only -- see _inject_fixture_todo)
    The commit message / PR body's "Changes" section is generated from what
    actually got staged (see _describe_changes), not a static list.

PR DESCRIPTION TEMPLATE:
    ## SBAB Pricing Update - {date}

    Detected changes in SBAB's discount structure.

    ### Changes
    - [auto-generated summary of what changed]

    ### Validation
    - Light re-scrape: PASSED
    - Uniformity check: PASSED

CONTEXT:
    - This is the final step of the DEEP RUN ONLY section
    - Only runs if 6j validation passed
    - After this step, flow rejoins at step 8 (send email)
"""
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

from io_contracts import assert_validation_result, GIT_IDENTITY_NAME, GIT_IDENTITY_EMAIL
from redact_secrets import combined_output


def _run_or_raise(cmd, action, **kwargs):
    """Run a git/gh command; raise with its full output (not just stderr) if it fails.

    kwargs forwards to subprocess.run -- in practice always cwd=repo_root, so this
    doesn't silently break if ever invoked with a different working directory
    (e.g. from src/ instead of the repo root)."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed: {combined_output(result)}")
    return result


# Named once here instead of being repeated across the fixture copy-back loop,
# the staging list and the git-rm/glob calls below.
_DATA_FILES = ['discount_surfaces.csv', 'list_rates.csv', 'boundaries_minimal.yaml']  # relative to data/
_DISCOUNT_SURFACE_GLOB = 'discount_surface_*.png'

# One-line description per file for the commit message / PR body's "Changes"
# section, keyed by git pathspec. Only files this run actually staged are
# listed (see _describe_changes) -- so the message doesn't claim a file is
# part of the change when this run never touched it.
_CHANGE_DESCRIPTIONS = {
    'data/discount_surfaces.csv': '`discount_surfaces.csv`: Old rows closed, new rows added',
    'data/list_rates.csv': '`list_rates.csv`: Committed alongside the discount update',
    'data/boundaries_minimal.yaml': '`boundaries_minimal.yaml`: Updated bin boundaries',
    'src/io_contracts.py': '`io_contracts.py`: Included in case VALID_MATURITIES changed',
    'data/test_fixtures/generate_fixtures.py': '`generate_fixtures.py`: TODO injected to regenerate test fixtures',
    'README.md': '`README.md`: TODO injected to regenerate test fixtures',
}


def _get_staged_files(repo_root):
    """
    Files with a real staged diff from HEAD, right now.

    Deliberately NOT files_to_add: that list is "files this run attempted to
    add", which isn't the same thing. list_rates.csv and io_contracts.py are
    unconditionally in files_to_add every deep run (the comment next to
    files_to_add says as much), so using it directly would claim they changed
    even on a run where they're byte-identical to HEAD -- git add on an
    unmodified tracked file stages nothing, so it correctly never shows up
    here. A failed `git add` (see the staging loop's per-file warning) also
    never shows up here, for the same reason.
    """
    result = subprocess.run(['git', 'diff', '--cached', '--name-only'], capture_output=True, text=True, cwd=repo_root)
    if result.returncode != 0:
        # Non-fatal, like the other warnings in this file: an empty/wrong Changes
        # section shouldn't block the PR, but it must not fail silently either.
        print(f"  Warning: git diff --cached --name-only failed: {combined_output(result)}")
        return []
    return result.stdout.splitlines()  # not .split(): a path containing a space must stay one token


def _describe_changes(staged_files):
    """Build the 'Changes' bullet list from what's actually staged (see _get_staged_files)."""
    lines = [desc for path, desc in _CHANGE_DESCRIPTIONS.items() if path in staged_files]
    if any(f.startswith('data/visualizations/') for f in staged_files):
        lines.append('`visualizations/discount_surface_*.png`: Regenerated discount surface heatmaps')
    return '\n'.join(f'- {line}' for line in lines)


def _inject_fixture_todo(repo_root, today_str):
    """Inject TODO reminders so the PR diff nags reviewers to regenerate test fixtures."""
    todo_line = f"# TODO ({today_str}): Regenerate test fixtures — run: python3 data/test_fixtures/generate_fixtures.py, then delete this line\n"

    # Inject at top of generate_fixtures.py (before the opening docstring)
    gen_path = repo_root / 'data' / 'test_fixtures' / 'generate_fixtures.py'
    if gen_path.exists():
        content = gen_path.read_text()
        if 'TODO' not in content.split('\n')[0]:  # Don't stack TODOs
            # Insert before the first line (the opening triple-quote)
            lines = content.split('\n')
            lines.insert(0, todo_line.rstrip())
            gen_path.write_text('\n'.join(lines))

    # Append reminder to README.md Known TODOs section
    readme_path = repo_root / 'README.md'
    if readme_path.exists():
        content = readme_path.read_text()
        stale_marker = 'Test fixtures may be stale'
        reminder = f"\n- **{stale_marker} ({today_str}):** A deep run PR was created. Run `python3 data/test_fixtures/generate_fixtures.py` after merging, then delete this TODO.\n"
        if stale_marker not in content:  # Don't stack reminders (the date differs run to run)
            if '## Known TODOs\n' in content:
                content = content.replace('## Known TODOs\n', f'## Known TODOs\n{reminder}', 1)
                readme_path.write_text(content)
            else:
                # A reminder is cosmetic: never let a stale README block the PR (main would not update, and every daily run would repeat the deep scrape)
                print("  Warning: README.md has no '## Known TODOs' heading; skipping the fixture reminder (the PR still opens)")


def open_PR_with_updates_to_main(validation_result, branch_name, is_test):
    """
    Open a PR with updates to main if validation passed.

    Args:
        validation_result: Dict from step 6j with 'passed' and 'reason'
        branch_name: Feature branch name (e.g., "grid-update-20260129-1430")
        is_test: If True, mark the PR/commit as a test run (DO NOT MERGE
                 warning, skip fixture-regen TODO injection). Required, not
                 defaulted: the caller (aleph_null.py) always has an explicit
                 is_test value in `state` already, and this step used to
                 silently re-read the IS_TEST env var itself at 3 separate
                 call sites instead of trusting its own argument -- making it
                 required (no env-var fallback) closes that gap for good.

    Returns:
        str: PR URL if successful, None if validation failed.
        Raises RuntimeError (with the git/gh command's full output) if commit,
        push, or PR creation fails -- these are unexpected operational failures,
        not the "validation failed, nothing to do" case that returns None.
    """
    assert_validation_result(validation_result)

    if not validation_result['passed']:
        print(f"SKIPPING PR: Validation failed - {validation_result['reason']}")
        return None

    today_str = date.today().strftime('%Y-%m-%d')
    code_dir = Path(__file__).parent
    repo_root = code_dir.parent
    repo_data_dir = repo_root / 'data'

    # When running with --data-dir, deep run wrote files to the fixture dir.
    # Copy them back to repo's data/ so git can stage them.
    if os.environ.get('SBAB_DATA_DIR'):
        fixture_dir = Path(os.environ['SBAB_DATA_DIR'])
        for f in _DATA_FILES:
            src = fixture_dir / f
            if src.exists():
                shutil.copy(src, repo_data_dir / f)
        fixture_viz = fixture_dir / 'visualizations'
        if fixture_viz.exists():
            for png in fixture_viz.glob(_DISCOUNT_SURFACE_GLOB):
                shutil.copy(png, repo_data_dir / 'visualizations' / png.name)

    # Files to commit (relative to repo root for git)
    # NOTE: Only discount_surface PNGs are version-tracked (not pricing_surface)
    #       to keep repo lightweight. Pricing surfaces are attached to emails only.
    files_to_add = [f'data/{f}' for f in _DATA_FILES] + [
        'src/io_contracts.py',  # Included for maturity changes (rewritten VALID_MATURITIES)
    ]

    # Add discount surface PNGs (NOT pricing_surface PNGs - keep repo light)
    # First, git rm any tracked PNGs that step 6h deleted (prevents zombie PNGs
    # from persisting in the repo after a deep run closes a validity era).
    viz_dir = repo_data_dir / 'visualizations'
    rm_result = subprocess.run(
        ['git', 'rm', '--cached', '--ignore-unmatch', '--quiet',
         f'data/visualizations/{_DISCOUNT_SURFACE_GLOB}'],
        capture_output=True, text=True, cwd=repo_root
    )
    if rm_result.returncode != 0:
        print(f"  Warning: git rm --cached (old discount_surface PNGs) failed: {combined_output(rm_result)}")
    # Then re-add the current set (git add on a git-rm'd file restores it)
    if viz_dir.exists():
        for png_file in viz_dir.glob(_DISCOUNT_SURFACE_GLOB):
            files_to_add.append(f'data/visualizations/{png_file.name}')

    # Inject TODO reminders into generate_fixtures.py and README.md
    # so the PR diff nags the reviewer to regenerate test fixtures.
    # Skip for test runs — those PRs are throwaway.
    if not is_test:
        _inject_fixture_todo(repo_root, today_str)
        files_to_add.append('data/test_fixtures/generate_fixtures.py')
        files_to_add.append('README.md')

    # Stage files
    for filepath in files_to_add:
        result = subprocess.run(
            ['git', 'add', filepath],
            capture_output=True,
            text=True,
            cwd=repo_root
        )
        if result.returncode != 0:
            print(f"Warning: Could not stage {filepath}: {combined_output(result)}")

    changes_block = _describe_changes(_get_staged_files(repo_root))

    # Create commit
    commit_message = f"SBAB pricing update {today_str}\n\nDetected changes in discount structure.\nValidation passed - light re-scrape confirms new boundaries.\n\nChanges:\n{changes_block}"

    # Identity scoped to this one command (-c, not `git config`) so it's never
    # written to .git/config -- see GIT_IDENTITY_NAME/GIT_IDENTITY_EMAIL in io_contracts.py.
    _run_or_raise(
        ['git', '-c', f'user.name={GIT_IDENTITY_NAME}', '-c', f'user.email={GIT_IDENTITY_EMAIL}',
         'commit', '-m', commit_message],
        'git commit', cwd=repo_root
    )

    # Push branch to origin
    _run_or_raise(['git', 'push', '-u', 'origin', branch_name], 'git push', cwd=repo_root)

    # Create PR using gh CLI
    pr_title = f"SBAB Pricing Update - {today_str}"

    # Add DO NOT MERGE warning for test runs
    if is_test:
        pr_title = f"⚠️ DO NOT MERGE — TEST RUN: {pr_title}"

    pr_body = f"""## Summary
- Detected changes in SBAB's discount structure
- Deep scraper ran to discover new boundaries
- Validation passed (light re-scrape confirms consistency)

## Changes
{changes_block}

## Validation
- Light re-scrape: PASSED
- Uniformity check: PASSED

---
🤖 Auto-generated by SBAB Rate Monitor
"""

    # Add DO NOT MERGE warning to PR body for test runs
    if is_test:
        pr_body = f"⚠️ **DO NOT MERGE** — This PR was created from a test run.\n\n{pr_body}"

    result = _run_or_raise(
        ['gh', 'pr', 'create',
         '--base', 'main',
         '--head', branch_name,
         '--title', pr_title,
         '--body', pr_body],
        'gh pr create', cwd=repo_root
    )

    # gh pr create outputs the PR URL on success
    pr_url = result.stdout.strip()
    print(f"PR created: {pr_url}")

    return pr_url
