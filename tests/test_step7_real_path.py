"""
Unit tests for step 7's real (non-test) path: no network, no git, no PRs.

conftest.py sets IS_TEST=true for every test, and step 7 skips its "inject
fixture TODOs" block when IS_TEST is true. That block once shipped with an
UnboundLocalError and broke real deep runs on 2026-09-25/26, so these tests
run step 7 with IS_TEST unset and every side effect mocked. The fixture-TODO
injection itself is tested separately against a temp directory.

Run: pytest tests/test_step7_real_path.py -v
"""
import subprocess
from datetime import date
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent
PR_URL = 'https://github.com/someone/some_repo/pull/1'
TODAY = '2026-01-02'
CORE_FILES = ['data/discount_surfaces.csv', 'data/list_rates.csv', 'data/boundaries_minimal.yaml', 'src/io_contracts.py']

step_7 = import_module('7_open_PR_with_updates_to_main')


class FixedDate(date):
    """date.today() frozen, so the test and step 7 can never disagree about the day."""

    @classmethod
    def today(cls):
        return date.fromisoformat(TODAY)


def _calls(events, tokens):
    """The recorded git/gh commands containing every token in `tokens` as an element --
    not necessarily as a prefix. (The commit call's shape is `git -c user.name=... -c
    user.email=... commit -m msg` now that identity is scoped per-command instead of a
    separate `git config` step, so a strict ['git', 'commit'] prefix wouldn't match it.)"""
    return [e for e in events if isinstance(e, list) and all(t in e for t in tokens)]


def _run_step_7(monkeypatch, fail_on=None, is_test=False, events=None):
    """
    Run step 7 with git/gh mocked. Returns (result, events).

    events is one ordered list of everything step 7 did: each git/gh command as a
    list, and the fixture-TODO injection as an ('inject', repo_root, today_str) tuple.
    Pass an `events` list in to inspect it even when fail_on makes step 7 raise.
    fail_on is a command prefix, e.g. ['git', 'push'] or ['git', 'config', 'user.name'],
    or a full command like ['git', 'add', 'data/list_rates.csv'] to fail just one file's
    staging without affecting the others.
    """
    monkeypatch.delenv('SBAB_DATA_DIR', raising=False)
    monkeypatch.setattr(step_7, 'date', FixedDate)

    if events is None:
        events = []
    monkeypatch.setattr(step_7, '_inject_fixture_todo',
                        lambda repo_root, today_str: events.append(('inject', repo_root, today_str)))

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        """Behaves like subprocess.run for the arguments step 7 uses."""
        events.append(cmd)
        failing_call = bool(fail_on) and all(token in cmd for token in fail_on)
        returncode = 1 if failing_call else 0
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, cmd)
        if failing_call:
            return subprocess.CompletedProcess(cmd, returncode, stdout='', stderr='simulated failure')
        if cmd[:2] == ['git', 'diff']:
            # Simulate `git diff --cached --name-only`: every `git add` that didn't fail
            # shows up as staged, same as the real index would report.
            staged = [e[2] for e in events if isinstance(e, list) and e[:2] == ['git', 'add']
                      and not (bool(fail_on) and all(token in e for token in fail_on))]
            return subprocess.CompletedProcess(cmd, 0, stdout='\n'.join(staged), stderr='')
        stdout = PR_URL + '\n' if (capture_output and text) else None
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr='' if capture_output else None)

    # Patch only step 7's view of subprocess, not the whole process
    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(run=fake_run))

    result = step_7.open_PR_with_updates_to_main({'passed': True, 'reason': None}, 'grid-update-test', is_test=is_test)
    return result, events


def test_real_path_injects_todo_and_returns_pr_url(monkeypatch):
    """IS_TEST unset: step 7 injects the fixture TODO, stages it, commits, pushes and opens a non-test PR."""
    url, events = _run_step_7(monkeypatch)

    assert url == PR_URL

    # The TODO is injected once, into this repo, with the date, before the files it edits are staged
    injections = [e for e in events if isinstance(e, tuple)]
    assert len(injections) == 1
    _, repo_root, today_str = injections[0]
    assert (Path(repo_root).resolve(), today_str) == (REPO_ROOT.resolve(), TODAY)
    inject_at = events.index(injections[0])
    assert inject_at < events.index(['git', 'add', 'README.md'])
    assert inject_at < events.index(['git', 'add', 'data/test_fixtures/generate_fixtures.py'])

    # Identity is scoped to the commit call itself (-c flags), never a separate step
    steps = [_calls(events, prefix)[0] for prefix in (['git', 'commit'], ['git', 'push'], ['gh', 'pr', 'create'])]
    commit_at, push_at, pr_at = [events.index(step) for step in steps]
    assert commit_at < push_at < pr_at
    commit_call = steps[0]
    assert f'user.name={step_7.GIT_IDENTITY_NAME}' in commit_call
    assert f'user.email={step_7.GIT_IDENTITY_EMAIL}' in commit_call
    assert not any(e[:2] == ['git', 'config'] for e in events if isinstance(e, list))  # never written to .git/config
    assert ['git', 'push', '-u', 'origin', 'grid-update-test'] in events

    # The core data files are staged before the commit
    for core_file in CORE_FILES:
        assert events.index(['git', 'add', core_file]) < commit_at

    # Old heatmap PNGs are untracked first; only discount_surface PNGs are staged, all before the commit
    png_rm_at = events.index(['git', 'rm', '--cached', '--ignore-unmatch', '--quiet', 'data/visualizations/discount_surface_*.png'])
    png_adds = [e for e in _calls(events, ['git', 'add']) if e[2].startswith('data/visualizations/')]
    assert png_adds and all(Path(e[2]).name.startswith('discount_surface_') for e in png_adds)
    assert png_rm_at < min(events.index(e) for e in png_adds) < commit_at

    # A real (non-test) PR into main from the branch: exact title, and no DO NOT MERGE banner in the body
    pr_create = steps[2]
    assert pr_create[pr_create.index('--base') + 1] == 'main'
    assert pr_create[pr_create.index('--head') + 1] == 'grid-update-test'
    assert pr_create[pr_create.index('--title') + 1] == f'SBAB Pricing Update - {TODAY}'
    assert 'DO NOT MERGE' not in pr_create[pr_create.index('--body') + 1]

    # The commit message's "Changes" section reflects everything actually staged this run
    # (via the real git-diff-based _get_staged_files, not a static guess -- see fake_run's
    # handling of the 'git diff' call above)
    commit_call = steps[0]
    commit_message = commit_call[commit_call.index('-m') + 1]
    for expected in ['`discount_surfaces.csv`', '`list_rates.csv`', '`boundaries_minimal.yaml`',
                      '`io_contracts.py`', '`generate_fixtures.py`', '`README.md`', 'discount_surface_*.png']:
        assert expected in commit_message


@pytest.mark.parametrize('failing', [['git', 'commit'], ['git', 'push'], ['gh', 'pr']],
                         ids=['commit', 'push', 'gh-pr-create'])
def test_real_path_raises_with_the_real_output_when_a_step_fails(monkeypatch, failing):
    """A failed commit, push or gh pr create raises with the command's actual output (never swallowed to None)."""
    events = []
    with pytest.raises(RuntimeError, match='simulated failure'):
        _run_step_7(monkeypatch, fail_on=failing, events=events)

    steps = [['git', 'commit'], ['git', 'push'], ['gh', 'pr']]
    attempted = [step for step in steps if _calls(events, step)]
    assert attempted == steps[:steps.index(failing) + 1]  # nothing after the failing step ran


def test_run_or_raise_redacts_a_detected_secret_before_raising(monkeypatch):
    """The redaction is actually wired into _run_or_raise's failure path, not just
    tested in isolation."""
    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 1, stdout='', stderr='remote: - Push cannot contain secrets: ghp_1234567890abcdefghijklmnopqrstuvwxyz')))

    with pytest.raises(RuntimeError) as excinfo:
        step_7._run_or_raise(['git', 'push'], 'git push')

    assert 'ghp_1234567890abcdefghijklmnopqrstuvwxyz' not in str(excinfo.value)


def test_run_or_raise_surfaces_a_stdout_only_failure(monkeypatch):
    """
    Exercises the exact scenario that motivated capturing stdout in the first place
    ("nothing to commit" writes to stdout, not stderr) -- every other test here only
    simulates a stderr-only failure, so this path was never actually proven to work.
    """
    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='nothing to commit', stderr='')))

    with pytest.raises(RuntimeError, match='nothing to commit'):
        step_7._run_or_raise(['git', 'commit'], 'git commit')


def test_run_or_raise_joins_stdout_and_stderr_with_a_separator(monkeypatch):
    """Mixed stdout+stderr output must not run together illegibly."""
    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='Running checks...', stderr='error: cannot lock ref')))

    with pytest.raises(RuntimeError) as excinfo:
        step_7._run_or_raise(['git', 'commit'], 'git commit')

    assert 'Running checks...error' not in str(excinfo.value)  # must not be glued together
    assert 'Running checks...' in str(excinfo.value)
    assert 'error: cannot lock ref' in str(excinfo.value)


def test_test_mode_marks_the_pr_and_skips_the_fixture_reminders(monkeypatch):
    """IS_TEST=true: DO NOT MERGE in the PR title and body, and no fixture TODO injected or staged."""
    url, events = _run_step_7(monkeypatch, is_test=True)

    pr_create = _calls(events, ['gh', 'pr', 'create'])[0]
    assert url == PR_URL
    assert 'DO NOT MERGE' in pr_create[pr_create.index('--title') + 1]
    assert 'DO NOT MERGE' in pr_create[pr_create.index('--body') + 1]
    assert not [e for e in events if isinstance(e, tuple)]
    assert ['git', 'add', 'README.md'] not in events
    assert ['git', 'add', 'data/test_fixtures/generate_fixtures.py'] not in events


def test_all_git_and_gh_calls_run_with_repo_root_as_cwd(monkeypatch):
    """
    Every git/gh call in this step must pass cwd=repo_root explicitly, not rely on the
    process's ambient working directory -- otherwise staging would silently (mis)target
    whatever directory the process happens to be running from (e.g. src/ instead of the
    repo root) rather than crashing loudly.
    """
    monkeypatch.delenv('IS_TEST', raising=False)
    monkeypatch.delenv('SBAB_DATA_DIR', raising=False)
    monkeypatch.setattr(step_7, 'date', FixedDate)
    monkeypatch.setattr(step_7, '_inject_fixture_todo', lambda repo_root, today_str: None)

    seen_cwds = []

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        seen_cwds.append(kwargs.get('cwd'))
        stdout = PR_URL + '\n' if (capture_output and text) else None
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr='' if capture_output else None)

    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(run=fake_run))

    step_7.open_PR_with_updates_to_main({'passed': True, 'reason': None}, 'grid-update-test', is_test=False)

    assert seen_cwds, "no subprocess calls were recorded"
    assert all(Path(cwd).resolve() == REPO_ROOT.resolve() for cwd in seen_cwds), seen_cwds


def test_git_rm_cached_failure_warns_but_continues(monkeypatch, capsys):
    """A failed git rm --cached (clearing old discount_surface PNGs) must not abort the PR -- it's
    expected to no-op via --ignore-unmatch; a real failure there is unusual but still non-fatal,
    same policy as the per-file git add warnings. It must not be silently swallowed, though."""
    url, events = _run_step_7(monkeypatch, fail_on=['git', 'rm'])

    assert url == PR_URL
    assert 'git rm' in capsys.readouterr().out.lower()


def test_git_rm_cached_failure_redacts_a_detected_secret(monkeypatch, capsys):
    """The git rm --cached warning must not leak a secret either -- consistent with every
    other failure message in this file (_run_or_raise already proven elsewhere)."""
    monkeypatch.delenv('SBAB_DATA_DIR', raising=False)
    monkeypatch.setattr(step_7, 'date', FixedDate)
    monkeypatch.setattr(step_7, '_inject_fixture_todo', lambda repo_root, today_str: None)

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        if cmd[:3] == ['git', 'rm', '--cached']:
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='AKIAABCDEFGHIJKLMN12 leaked')
        if cmd[:2] == ['git', 'diff']:
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        stdout = PR_URL + '\n' if (capture_output and text) else None
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr='' if capture_output else None)

    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(run=fake_run))

    step_7.open_PR_with_updates_to_main({'passed': True, 'reason': None}, 'grid-update-test', is_test=False)

    out = capsys.readouterr().out
    assert 'AKIAABCDEFGHIJKLMN12' not in out
    assert '[REDACTED]' in out


def test_git_rm_cached_failure_combines_stdout_and_stderr(monkeypatch, capsys):
    """Same 'nothing to commit goes to stdout, not stderr' lesson _run_or_raise already
    learned must apply here too -- stderr alone would silently drop a stdout-only detail."""
    monkeypatch.delenv('SBAB_DATA_DIR', raising=False)
    monkeypatch.setattr(step_7, 'date', FixedDate)
    monkeypatch.setattr(step_7, '_inject_fixture_todo', lambda repo_root, today_str: None)

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        if cmd[:3] == ['git', 'rm', '--cached']:
            return subprocess.CompletedProcess(cmd, 1, stdout='diagnostic on stdout', stderr='')
        if cmd[:2] == ['git', 'diff']:
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        stdout = PR_URL + '\n' if (capture_output and text) else None
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr='' if capture_output else None)

    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(run=fake_run))

    step_7.open_PR_with_updates_to_main({'passed': True, 'reason': None}, 'grid-update-test', is_test=False)

    assert 'diagnostic on stdout' in capsys.readouterr().out


def test_git_add_failure_redacts_a_detected_secret(monkeypatch, capsys):
    """The per-file staging warning must not leak a secret either -- it's the one
    subprocess-output print in this function that wasn't covered until now."""
    monkeypatch.delenv('SBAB_DATA_DIR', raising=False)
    monkeypatch.setattr(step_7, 'date', FixedDate)
    monkeypatch.setattr(step_7, '_inject_fixture_todo', lambda repo_root, today_str: None)

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        if cmd[:2] == ['git', 'add'] and cmd[2] == 'data/list_rates.csv':
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='AKIAABCDEFGHIJKLMN12 leaked')
        if cmd[:2] == ['git', 'diff']:
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        stdout = PR_URL + '\n' if (capture_output and text) else None
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr='' if capture_output else None)

    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(run=fake_run))

    step_7.open_PR_with_updates_to_main({'passed': True, 'reason': None}, 'grid-update-test', is_test=False)

    out = capsys.readouterr().out
    assert 'AKIAABCDEFGHIJKLMN12' not in out
    assert '[REDACTED]' in out


def test_get_staged_files_handles_filenames_with_spaces(monkeypatch):
    """.splitlines(), not .split(): a staged path containing a space must stay one
    token, not silently become two bogus fragments that then fail every membership
    check in _describe_changes."""
    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout='data/a file.csv\ndata/other.csv\n', stderr='')))

    assert step_7._get_staged_files(REPO_ROOT) == ['data/a file.csv', 'data/other.csv']


def test_get_staged_files_warns_and_returns_empty_list_on_failure(monkeypatch, capsys):
    """A failed `git diff --cached --name-only` must not silently render an empty/wrong
    Changes section -- it's non-fatal (like the git-add and git-rm-cached warnings in
    this same file), but must be visible, not silent."""
    monkeypatch.setattr(step_7, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='', stderr='simulated failure')))

    result = step_7._get_staged_files(REPO_ROOT)

    assert result == []
    assert 'simulated failure' in capsys.readouterr().out


def test_is_test_argument_is_required():
    """No default, no env-var fallback: a caller must pass is_test explicitly -- this is
    the whole point of the fix (step 7 used to silently re-read IS_TEST itself)."""
    with pytest.raises(TypeError):
        step_7.open_PR_with_updates_to_main({'passed': True, 'reason': None}, 'grid-update-test')


def test_describe_changes_omits_a_file_whose_staging_failed(monkeypatch):
    """
    Integration-level proof of the real fix: a file listed in files_to_add but whose
    `git add` failed must not appear in the Changes section, because _get_staged_files
    reads the actual git index (via `git diff --cached --name-only`), not files_to_add.
    """
    url, events = _run_step_7(monkeypatch, fail_on=['git', 'add', 'data/list_rates.csv'])

    commit_call = _calls(events, ['git', 'commit'])[0]
    commit_message = commit_call[commit_call.index('-m') + 1]
    assert '`list_rates.csv`' not in commit_message
    assert '`discount_surfaces.csv`' in commit_message  # unaffected files still show up


def test_data_files_all_have_change_descriptions():
    """
    _DATA_FILES (fixture copy-back targets) and _CHANGE_DESCRIPTIONS (PR-body text) are two
    separately-maintained lists for two different purposes (not every _CHANGE_DESCRIPTIONS
    entry is a _DATA_FILES entry -- io_contracts.py, generate_fixtures.py and README.md
    aren't copied back from a fixture dir). But every _DATA_FILES entry SHOULD have a
    description, or its bullet would silently vanish from the PR body the day it's staged.
    """
    missing = [f for f in step_7._DATA_FILES if f'data/{f}' not in step_7._CHANGE_DESCRIPTIONS]
    assert not missing, f"_DATA_FILES entries with no _CHANGE_DESCRIPTIONS bullet: {missing}"


def test_describe_changes_lists_only_what_was_staged():
    """The PR body/commit message's 'Changes' section must reflect what this run actually
    staged, not a static guess that silently omits files like list_rates.csv or io_contracts.py."""
    result = step_7._describe_changes(['data/discount_surfaces.csv', 'data/boundaries_minimal.yaml'])

    assert 'discount_surfaces.csv' in result
    assert 'boundaries_minimal.yaml' in result
    assert 'list_rates.csv' not in result
    assert 'io_contracts.py' not in result
    assert 'generate_fixtures.py' not in result


def test_describe_changes_includes_every_staged_file_and_the_png_bullet():
    files = [
        'data/discount_surfaces.csv', 'data/list_rates.csv', 'data/boundaries_minimal.yaml',
        'src/io_contracts.py', 'data/test_fixtures/generate_fixtures.py', 'README.md',
        'data/visualizations/discount_surface_LTV_50-60_VOL_1-1.5M.png',
    ]
    result = step_7._describe_changes(files)

    for expected in ['discount_surfaces.csv', 'list_rates.csv', 'boundaries_minimal.yaml',
                      'io_contracts.py', 'generate_fixtures.py', 'README.md', 'discount_surface_*.png']:
        assert expected in result


def _fake_repo(tmp_path):
    """A minimal repo root holding the two files _inject_fixture_todo edits."""
    (tmp_path / 'data' / 'test_fixtures').mkdir(parents=True)
    generator = tmp_path / 'data' / 'test_fixtures' / 'generate_fixtures.py'
    generator.write_text('"""Fixture generator."""\n')
    readme = tmp_path / 'README.md'
    readme.write_text('# Title\n\n## Known TODOs\n\n- existing item\n')
    return generator, readme


def test_inject_fixture_todo_edits_both_files(tmp_path):
    """The TODO lands at the top of generate_fixtures.py and under '## Known TODOs' in the README."""
    generator, readme = _fake_repo(tmp_path)

    step_7._inject_fixture_todo(tmp_path, TODAY)

    assert generator.read_text().startswith(f'# TODO ({TODAY}): Regenerate test fixtures')
    assert 'then delete this line' in generator.read_text()  # the injected comment names its own removal
    assert f'## Known TODOs\n\n- **Test fixtures may be stale ({TODAY})' in readme.read_text()
    assert '- existing item' in readme.read_text()


def test_inject_fixture_todo_does_not_stack_on_a_later_run(tmp_path):
    """A second deep run on another date leaves one reminder in each file (the first date stays)."""
    generator, readme = _fake_repo(tmp_path)

    step_7._inject_fixture_todo(tmp_path, TODAY)
    step_7._inject_fixture_todo(tmp_path, '2026-02-03')

    assert generator.read_text().count('TODO') == 1
    assert readme.read_text().count('Test fixtures may be stale') == 1
    assert '2026-02-03' not in generator.read_text() + readme.read_text()


def test_inject_fixture_todo_survives_a_missing_readme_heading(tmp_path, capsys):
    """A stale README must never block a deep-run PR (main would not update, so the deep scrape would repeat daily)."""
    _, readme = _fake_repo(tmp_path)
    readme.write_text('# Title\n\n## Open Items\n')

    step_7._inject_fixture_todo(tmp_path, TODAY)  # must not raise

    assert readme.read_text() == '# Title\n\n## Open Items\n'
    assert 'Known TODOs' in capsys.readouterr().out  # the skipped reminder is at least announced in the log


def test_real_files_step_7_edits_are_where_it_expects():
    """If the README heading or generate_fixtures.py moves, the reminders silently stop; catch it here."""
    assert '## Known TODOs\n' in (REPO_ROOT / 'README.md').read_text()
    assert (REPO_ROOT / 'data' / 'test_fixtures' / 'generate_fixtures.py').exists()
