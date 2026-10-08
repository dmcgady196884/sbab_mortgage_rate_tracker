"""
Fast unit tests for aleph_null._commit_list_rates (no network, no real git):
the stdout+stderr-combine-and-redact failure logging, and the git identity/cwd
handling.

_commit_list_rates deliberately never raises -- a transient git hiccup here
must not abort the more important discount-structure detection steps that
run after it. See the function's own docstring for why warn-and-continue is
correct here, unlike step 7's _run_or_raise.

Run: pytest tests/test_commit_list_rates.py -v
"""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import aleph_null

REPO_ROOT = Path(__file__).parent.parent


def test_failure_log_combines_stdout_and_stderr(monkeypatch, capsys):
    """A failing step's stdout AND stderr must both reach the warning, not stderr alone --
    e.g. git prints 'nothing to commit' to stdout, not stderr."""
    monkeypatch.setattr(aleph_null, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='nothing to commit', stderr='')))

    aleph_null._commit_list_rates()  # must not raise

    out = capsys.readouterr().out
    assert 'nothing to commit' in out


def test_failure_log_joins_mixed_output_with_a_separator(monkeypatch, capsys):
    """Mixed stdout+stderr must not run together illegibly (same lesson as step 7's _run_or_raise)."""
    monkeypatch.setattr(aleph_null, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='Running checks...', stderr='error: cannot lock ref')))

    aleph_null._commit_list_rates()

    out = capsys.readouterr().out
    assert 'Running checks...error' not in out
    assert 'Running checks...' in out
    assert 'error: cannot lock ref' in out


def test_success_path_is_unaffected(monkeypatch, capsys):
    """All steps succeeding still prints the normal success message, not a warning."""
    monkeypatch.setattr(aleph_null, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')))

    aleph_null._commit_list_rates()

    out = capsys.readouterr().out
    assert 'Committed and pushed list_rates.csv' in out
    assert 'Warning' not in out


def test_failure_log_redacts_a_detected_secret(monkeypatch, capsys):
    """
    This function pushes straight to main (not a throwaway feature branch), so a secret
    leaking into its failure log is more exposed than the equivalent in step 7, not less.
    Must use the same shared redact_secrets() step 7 uses, not print the raw output.
    """
    monkeypatch.setattr(aleph_null, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='', stderr='AKIAABCDEFGHIJKLMN12 leaked')))

    aleph_null._commit_list_rates()

    out = capsys.readouterr().out
    assert 'AKIAABCDEFGHIJKLMN12' not in out
    assert '[REDACTED]' in out


def test_identity_is_scoped_to_the_commit_call_not_git_config(monkeypatch):
    """Identity must come via `git -c user.name=... -c user.email=...` on the commit
    call itself, never a separate `git config` step that would persist to .git/config
    (same reasoning as step 7's own identity handling)."""
    events = []

    def fake_run(cmd, **kwargs):
        events.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(aleph_null, 'subprocess', SimpleNamespace(run=fake_run))

    aleph_null._commit_list_rates()

    assert not any(e[:2] == ['git', 'config'] for e in events)
    commit_calls = [e for e in events if 'commit' in e]
    assert len(commit_calls) == 1
    assert f'user.name={aleph_null.GIT_IDENTITY_NAME}' in commit_calls[0]
    assert f'user.email={aleph_null.GIT_IDENTITY_EMAIL}' in commit_calls[0]


def test_every_git_call_runs_with_repo_root_as_cwd(monkeypatch):
    """Must not rely on the process's ambient working directory."""
    seen_cwds = []

    def fake_run(cmd, **kwargs):
        seen_cwds.append(kwargs.get('cwd'))
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(aleph_null, 'subprocess', SimpleNamespace(run=fake_run))

    aleph_null._commit_list_rates()

    assert seen_cwds, "no subprocess calls were recorded"
    assert all(Path(cwd).resolve() == REPO_ROOT.resolve() for cwd in seen_cwds), seen_cwds


def test_a_failing_step_still_warns_and_does_not_raise(monkeypatch, capsys):
    """Policy unchanged by this fix: any step failing still warns and returns, never raises."""
    monkeypatch.setattr(aleph_null, 'subprocess', SimpleNamespace(
        run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout='', stderr='simulated failure')))

    aleph_null._commit_list_rates()  # must not raise

    assert 'simulated failure' in capsys.readouterr().out


def test_git_identity_is_the_same_object_as_step_7s_not_an_independent_copy():
    """
    GIT_IDENTITY_NAME/GIT_IDENTITY_EMAIL live in io_contracts.py and are imported by
    both this module and step 7, not independently redefined in each -- if the bot
    identity ever changes, an edit to only one copy would otherwise leave commits
    from the two call sites attributed to two different identities with nothing to
    catch the mismatch.
    """
    from importlib import import_module
    step_7 = import_module('7_open_PR_with_updates_to_main')
    import io_contracts

    assert aleph_null.GIT_IDENTITY_NAME is io_contracts.GIT_IDENTITY_NAME is step_7.GIT_IDENTITY_NAME
    assert aleph_null.GIT_IDENTITY_EMAIL is io_contracts.GIT_IDENTITY_EMAIL is step_7.GIT_IDENTITY_EMAIL
