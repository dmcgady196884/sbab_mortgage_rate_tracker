"""
Fast unit tests for whole-pipeline failure alerting (no network, no git, no PRs).

If the pipeline crashes anywhere -- light run, the maturity-change bookkeeping,
or the deep run -- aleph_null must email the failure and then re-raise, so a red
job is never the only signal. state['trigger_reason'] is only set once a deep
run has actually started, so the alert can tell a deep-run crash apart from a
pure light-run crash.

Run: pytest tests/test_failure_email.py -v
"""
import json
from importlib import import_module
from traceback import FrameSummary

import pytest

import aleph_null

step_8 = import_module('8_send_email_with_report')


def test_deep_run_crash_emails_failure_with_trigger_reason_then_reraises(monkeypatch):
    """A crash after a deep run started: pipeline_failed, trigger_reason set, alert sent, still raises."""

    def crash(state, force_shallow):
        state['trigger_reason'] = 'test trigger'  # set by _run_pipeline_steps before a real deep run starts
        raise RuntimeError("boom")

    finalized = []
    monkeypatch.setattr(aleph_null, '_run_pipeline_steps', crash)
    monkeypatch.setattr(aleph_null, '_finalize_and_send_email', lambda state, is_test: finalized.append(dict(state)))

    state = {'email_type': 'no_change', 'pr_url': None, 'list_rate_changes': None}
    with pytest.raises(RuntimeError, match="boom"):
        aleph_null._run_pipeline_or_email_failure(state, is_test=True, force_shallow=False)

    assert len(finalized) == 1
    assert finalized[0]['email_type'] == 'pipeline_failed'
    assert finalized[0]['failure_reason'] == "RuntimeError: boom"
    assert finalized[0]['trigger_reason'] == 'test trigger'
    # crash() lives in the test file, so the last frame of our own code is the wrapper itself
    assert finalized[0]['failure_location'].startswith('aleph_null.py:')
    assert finalized[0]['failure_location'].endswith(' in _run_pipeline_or_email_failure')


def test_light_run_crash_emails_failure_with_no_trigger_reason_then_reraises(monkeypatch):
    """A crash before any deep run started: pipeline_failed, no trigger_reason, alert sent, still raises."""

    def crash(state, force_shallow):
        raise RuntimeError("boom")  # trigger_reason never set: no deep run was ever triggered

    finalized = []
    monkeypatch.setattr(aleph_null, '_run_pipeline_steps', crash)
    monkeypatch.setattr(aleph_null, '_finalize_and_send_email', lambda state, is_test: finalized.append(dict(state)))

    state = {'email_type': 'no_change', 'pr_url': None, 'list_rate_changes': None}
    with pytest.raises(RuntimeError, match="boom"):
        aleph_null._run_pipeline_or_email_failure(state, is_test=True, force_shallow=False)

    assert len(finalized) == 1
    assert finalized[0]['email_type'] == 'pipeline_failed'
    assert finalized[0]['failure_reason'] == "RuntimeError: boom"
    assert 'trigger_reason' not in finalized[0]


def test_pipeline_success_is_left_alone(monkeypatch):
    """When the pipeline succeeds the wrapper sends nothing itself (the caller sends the normal email)."""
    finalized = []
    monkeypatch.setattr(aleph_null, '_run_pipeline_steps',
                        lambda state, force_shallow: state.update(email_type='deep_run_started'))
    monkeypatch.setattr(aleph_null, '_finalize_and_send_email', lambda state, is_test: finalized.append(dict(state)))

    state = {'email_type': 'no_change'}
    aleph_null._run_pipeline_or_email_failure(state, is_test=True, force_shallow=False)

    assert finalized == []
    assert state['email_type'] == 'deep_run_started'


def test_pipeline_failed_email_with_trigger_reason_describes_a_deep_run_crash(monkeypatch):
    """With a trigger_reason (a deep run had started), the email keeps the deep-run-specific narrative."""
    sent = {}
    monkeypatch.setattr(step_8, 'send_email',
                        lambda subject, body, attachments=None: sent.update(subject=subject, body=body, attachments=attachments))
    monkeypatch.setattr(step_8, '_collect_all_visualizations', lambda viz_dir: ['surface.png'])
    monkeypatch.setenv('GITHUB_SERVER_URL', 'https://github.com')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'someone/some_repo')
    monkeypatch.setenv('GITHUB_RUN_ID', '12345')

    step_8.send_email_with_report(
        'pipeline_failed', is_test=True,
        trigger_reason='Discount value mismatch in 792 bin/maturity combinations',
        failure_reason='UnboundLocalError: boom',
        failure_location='7_open_PR_with_updates_to_main.py:138 in open_PR_with_updates_to_main',
    )

    assert 'Pipeline Failed' in sent['subject']
    assert 'the deep run started, but it did not finish' in sent['body']
    assert 'UnboundLocalError: boom' in sent['body']
    assert 'https://github.com/someone/some_repo/actions/runs/12345' in sent['body']
    assert 'Discount value mismatch in 792 bin/maturity combinations' in sent['body']
    assert '7_open_PR_with_updates_to_main.py:138 in open_PR_with_updates_to_main' in sent['body']
    assert 'surface.png' in sent['attachments']
    assert any(str(a).endswith('boundaries_refined.yaml') for a in sent['attachments'])


def test_pipeline_failed_email_without_trigger_reason_describes_a_general_crash(monkeypatch):
    """Without a trigger_reason (no deep run had started), the email must not claim a deep run happened."""
    sent = {}
    monkeypatch.setattr(step_8, 'send_email',
                        lambda subject, body, attachments=None: sent.update(subject=subject, body=body, attachments=attachments))
    monkeypatch.setattr(step_8, '_collect_all_visualizations', lambda viz_dir: [])
    monkeypatch.setenv('GITHUB_SERVER_URL', 'https://github.com')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'someone/some_repo')
    monkeypatch.setenv('GITHUB_RUN_ID', '99')

    step_8.send_email_with_report(
        'pipeline_failed', is_test=True,
        failure_reason="AssertionError: API response: missing keys: {'Rantesats'}",
        failure_location='1_scraper_run_on_minimal_grid.py:20 in scrape_minimal_grid',
    )

    assert 'Pipeline Failed' in sent['subject']
    assert 'the deep run started' not in sent['body']  # must not falsely claim a deep run was in progress
    assert 'crashed before any deep run was triggered' in sent['body']
    assert "missing keys: {'Rantesats'}" in sent['body']
    assert '1_scraper_run_on_minimal_grid.py:20 in scrape_minimal_grid' in sent['body']
    assert 'https://github.com/someone/some_repo/actions/runs/99' in sent['body']


def test_pipeline_failed_email_uses_presence_not_truthiness_of_trigger_reason(monkeypatch):
    """An empty-but-present trigger_reason ('') still means a deep run had started -- unreachable with
    today's real callers (both always supply a non-empty string), but must not silently fall back to
    the general-crash narrative if that ever changes."""
    sent = {}
    monkeypatch.setattr(step_8, 'send_email',
                        lambda subject, body, attachments=None: sent.update(subject=subject, body=body))
    monkeypatch.setattr(step_8, '_collect_all_visualizations', lambda viz_dir: [])
    monkeypatch.setenv('GITHUB_SERVER_URL', 'https://github.com')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'someone/some_repo')
    monkeypatch.setenv('GITHUB_RUN_ID', '1')

    step_8.send_email_with_report(
        'pipeline_failed', is_test=True,
        trigger_reason='',  # falsy but present
        failure_reason='boom',
        failure_location='x.py:1 in f',
    )

    assert 'the deep run started' in sent['body']
    assert 'crashed before any deep run was triggered' not in sent['body']


def test_crash_site_prefers_our_step_code_over_libraries(monkeypatch):
    """The 'Where' line names the last frame in src/ (not pandas, subprocess or io_contracts asserts)."""
    step_file = str(aleph_null.CODE_DIR / '6c_extract_rasterized_disc_surface.py')
    frames = [
        FrameSummary(str(aleph_null.CODE_DIR / 'aleph_null.py'), 250, 'deep_run'),
        FrameSummary(step_file, 40, 'extract_rasterized_surfaces'),
        FrameSummary(str(aleph_null.CODE_DIR / 'io_contracts.py'), 300, 'assert_rasterized'),
        FrameSummary('/site-packages/pandas/core/base.py', 3819, 'get_loc'),
    ]
    monkeypatch.setattr(aleph_null.traceback, 'extract_tb', lambda tb: frames)
    site = aleph_null._crash_site(RuntimeError('x'))
    assert (site.filename, site.lineno) == (step_file, 40)

    # No frame of ours at all: fall back to the innermost one
    frames = [FrameSummary('/lib/a.py', 1, 'outer'), FrameSummary('/lib/b.py', 2, 'inner')]
    assert aleph_null._crash_site(RuntimeError('x')).name == 'inner'


def test_email_send_failure_is_recorded_in_pipeline_state_json(monkeypatch, tmp_path):
    """
    If the failure-alert email itself fails to send, that must be visible in
    pipeline_state.json -- otherwise the workflow's step summary confidently tells the
    reader to "see the failure email for details" when no such email was ever sent (see
    daily_scrape.yml's pipeline_failed case). Drives the REAL _finalize_and_send_email
    (only data_dir and the email send are mocked), since the write this test checks
    happens inside that function on the normal path, and the amendment happens in
    _run_pipeline_or_email_failure's except block when that same function then raises.
    """
    monkeypatch.setattr(aleph_null, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(aleph_null.step_8, 'send_email_with_report',
                        lambda **kw: (_ for _ in ()).throw(ConnectionError("smtp down")))
    monkeypatch.setattr(aleph_null.step_1, 'scrape_minimal_grid',
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        aleph_null.run_pipeline(is_test=True)

    state = json.loads((tmp_path / 'pipeline_state.json').read_text())
    assert state['email_type'] == 'pipeline_failed'
    assert 'smtp down' in state.get('email_send_failed', '')


def test_email_send_failure_amend_write_failure_does_not_mask_the_crash(monkeypatch, capsys):
    """
    If even the amend-write (recording email_send_failed) fails -- e.g. a disk error --
    the ORIGINAL pipeline crash must still be what propagates, not a new exception from
    this secondary bookkeeping write.
    """
    write_calls = []

    def flaky_write(state):
        write_calls.append(state)
        if len(write_calls) >= 2:
            raise OSError("disk full")
        return None

    monkeypatch.setattr(aleph_null, '_write_pipeline_state_json', flaky_write)
    monkeypatch.setattr(aleph_null.step_8, 'send_email_with_report',
                        lambda **kw: (_ for _ in ()).throw(ConnectionError("smtp down")))
    monkeypatch.setattr(aleph_null.step_1, 'scrape_minimal_grid',
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        aleph_null.run_pipeline(is_test=True)

    assert len(write_calls) == 2  # the normal write, then the (failing) amend
    out = capsys.readouterr().out
    assert 'disk full' in out
    assert 'smtp down' in out


def test_finalize_failure_message_does_not_commit_to_a_specific_phase(monkeypatch, tmp_path, capsys):
    """
    The except block genuinely cannot tell whether the pipeline_state.json write or the
    email send is what failed (both happen inside _finalize_and_send_email) -- the
    printed message must not claim "could not send" specifically, since that's wrong
    whenever it was actually the write that failed.
    """
    monkeypatch.setattr(aleph_null, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(aleph_null.step_8, 'send_email_with_report',
                        lambda **kw: (_ for _ in ()).throw(ConnectionError("smtp down")))
    monkeypatch.setattr(aleph_null.step_1, 'scrape_minimal_grid',
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        aleph_null.run_pipeline(is_test=True)

    out = capsys.readouterr().out
    assert 'could not finalize the failure alert' in out
    assert 'could not send the failure alert' not in out  # old, phase-specific wording


def test_failed_alert_does_not_mask_the_crash(monkeypatch, capsys):
    """If sending the alert fails, the original crash is still what propagates (and the email error is printed)."""

    def crash(state, force_shallow):
        raise RuntimeError("boom")

    def email_down(state, is_test):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(aleph_null, '_run_pipeline_steps', crash)
    monkeypatch.setattr(aleph_null, '_finalize_and_send_email', email_down)

    with pytest.raises(RuntimeError, match="boom"):
        aleph_null._run_pipeline_or_email_failure({'email_type': 'no_change'}, is_test=True, force_shallow=False)

    assert 'smtp down' in capsys.readouterr().out


def test_real_run_pipeline_sends_exactly_one_email_on_a_crash(monkeypatch, tmp_path):
    """
    Drives the REAL run_pipeline() (not just the inner wrapper) through a light-run
    crash, end to end. Guards against a future edit that accidentally double-sends --
    e.g. a stray _finalize_and_send_email call added inside
    _run_pipeline_or_email_failure's except block would still leave run_pipeline's
    own trailing call reachable only on success, but nothing short of exercising the
    real entry point would catch a mistake made the other way around.
    """
    sent = []
    monkeypatch.setattr(aleph_null, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(aleph_null.step_8, 'send_email_with_report', lambda **kw: (sent.append(kw), True)[1])
    monkeypatch.setattr(aleph_null.step_1, 'scrape_minimal_grid',
                        lambda: (_ for _ in ()).throw(AssertionError("API response: missing keys: {'Rantesats'}")))

    with pytest.raises(AssertionError, match="Rantesats"):
        aleph_null.run_pipeline(is_test=True)

    assert len(sent) == 1, f"expected exactly one email, got {len(sent)}"
    assert sent[0]['email_type'] == 'pipeline_failed'
    assert sent[0]['trigger_reason'] is None
    assert "Rantesats" in sent[0]['failure_reason']


def test_data_dir_override_forces_test_mode_even_if_is_test_not_passed(monkeypatch, tmp_path, capsys):
    """
    A non-default data_dir has no legitimate production use (only fixtures). If a
    caller sets it without also setting is_test=True -- e.g. GitHub Actions' manual
    dispatch form has them as two independent inputs, so it's easy to fill in one
    and forget the other -- run_pipeline must still behave as a test run, not let
    fixture numbers masquerade as a real production result.
    """
    sent = []
    monkeypatch.setattr(aleph_null, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(aleph_null.step_8, 'send_email_with_report', lambda **kw: (sent.append(kw), True)[1])
    monkeypatch.setattr(aleph_null.step_1, 'scrape_minimal_grid',
                        lambda: (_ for _ in ()).throw(AssertionError("API response: missing keys: {'Rantesats'}")))

    with pytest.raises(AssertionError, match="Rantesats"):
        aleph_null.run_pipeline(data_dir_override=str(tmp_path))  # is_test not passed -> defaults to False

    assert len(sent) == 1
    assert sent[0]['is_test'] is True  # forced, despite is_test defaulting to False
    assert 'forcing test mode' in capsys.readouterr().out


def test_pipeline_complete_banner_only_prints_after_a_real_success(monkeypatch, capsys):
    """'PIPELINE COMPLETE' must only print once the pipeline AND the email both
    genuinely succeeded -- not right before a crash re-raises (misleading log output)."""
    monkeypatch.setattr(aleph_null, '_run_pipeline_steps',
                        lambda state, force_shallow: state.update(email_type='no_change'))
    monkeypatch.setattr(aleph_null, '_finalize_and_send_email', lambda state, is_test: state)

    aleph_null.run_pipeline(is_test=True)

    assert 'PIPELINE COMPLETE' in capsys.readouterr().out


def test_pipeline_complete_banner_not_printed_before_a_crash_reraises(monkeypatch, tmp_path, capsys):
    """
    The crash-then-alert path must not claim the pipeline completed right before re-raising.
    Drives the REAL _finalize_and_send_email (only data_dir and the email send are mocked) --
    a version of this test that also mocked _finalize_and_send_email away could never have
    caught the original bug, since the banner lived inside that very function.
    """
    monkeypatch.setattr(aleph_null, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(aleph_null.step_8, 'send_email_with_report', lambda **kw: True)
    monkeypatch.setattr(aleph_null.step_1, 'scrape_minimal_grid',
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        aleph_null.run_pipeline(is_test=True)

    assert 'PIPELINE COMPLETE' not in capsys.readouterr().out
