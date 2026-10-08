"""
I/O Contract Definitions and Assertion Functions

This module defines the schema contracts for all pipeline steps. Each step's
main function should call the relevant assertion functions at entry (inputs)
and exit (outputs).

USAGE:
	from io_contracts import assert_scraper_output, assert_deep_run_signal

	def main(scraper_df):
		assert_scraper_output(scraper_df)
		# ... do work ...
		assert_deep_run_signal(result)
		return result

PRECISION NOTE:
	SBAB currently quotes rates in integer basis points (2 decimal places).
	If they switch to sub-basis-point precision, the pipeline adapts via
	rate_precision() which detects the actual precision from the data.
	Exception: mean_discount_* in step 3a retains full precision to detect
	bin non-uniformity.

RAW SBAB API RESPONSE FORMAT (for reference):
	URL: https://www.sbab.se/www-open-rest-api/resources/rantor/bolan/hamtaprisdiffaderantor/{asset_val}/{loan_vol}
	Response: JSON array with 8 entries (one per maturity):
	[
		{
			"LoptidText": "2026-04-27",       # maturity date (string)
			"Rantesats": 3.05,                # offered interest rate (float, 2dp)
			"Rantebindningstid": 3,           # maturity period in months (int)
			"EffektivRantesats": 0.0          # effective rate (always 0.0, ignored)
		},
		...
	]

	The scraper transforms this into the SCRAPER_OUTPUT_SCHEMA below.
"""
import os
from pathlib import Path

import pandas as pd
import numpy as np


# =============================================================================
# CONSTANTS
# =============================================================================

# Valid maturities (months) - matches API's "Rantebindningstid" values
VALID_MATURITIES = [3, 12, 24, 36, 48, 60, 84, 120]

# Sentinel values for "infinity" bins in boundary configs
SENTINEL_LTV = 999.0          # Upper edge of the top "(X+)%" bin (label varies: "(90+)%" in boundaries_minimal.yaml, "(92+)%" in boundaries_refined.yaml)
SENTINEL_VOL = 999_999_999    # Upper edge of the top "(X+)M" bin (label varies: "(5+)M" in boundaries_minimal.yaml, "(10+)M" in boundaries_refined.yaml)

# Probe helpers for scraper grid generation
LTV_PROBE_LOW = 0.05          # Inside first LTV bin
LTV_PROBE_HIGH = 0.95         # Inside last LTV bin (above 90% break, below 1.0 bin edge)
VOL_PROBE_LOW = 50            # Inside first VOL bin (50 SEK)
VOL_PROBE_HIGH = 10_000_050   # Inside last VOL bin (avoids 10M boundary)
LTV_EPSILON = 0.001           # ±0.1% offset for probes around LTV boundaries
VOL_EPSILON = 50              # ±50 SEK offset for probes around VOL boundaries

# Scraper retry behavior (transient network errors, e.g. SSL handshake timeouts)
SCRAPER_MAX_RETRIES = 3          # total attempts per probe point before giving up
SCRAPER_RETRY_DELAY_SECONDS = 2  # pause between retries

# Optional pause between probe requests. 0 keeps the deployment's timing unchanged;
# anyone else running this should set a small positive value.
SCRAPER_PAUSE_SECONDS = 0

# Sanity bounds for an offered rate (percent). A value outside them is a broken response,
# not a price; one bad high value would otherwise become a false list-rate change (list rate = max).
RATE_MIN = 0.0
RATE_MAX = 20.0

# Stable-named copy of the current discount-surface heatmap, embedded in the README
CURRENT_DISCOUNT_SURFACE_PNG = 'discount_surface_current.png'

# Scraper identity, sent as the User-Agent header on every API request
SCRAPER_USER_AGENT = 'sbab_mortgage_rate_tracker (personal rate monitor; https://github.com/dmcgady196884/sbab_mortgage_rate_tracker)'

# Bin-membership convention for assign_bin() in 3a_convert_csv_to_nice_pd_df.py.
# SBAB's real pricing is closed on OPPOSITE sides per axis (confirmed 2026-09-29
# by probing exact bin-edge values against the live API) -- see assign_bin's own
# docstring for the full explanation and worked examples.
LTV_BIN_RIGHT_CLOSED = True   # LTV bins are (low, high]
VOL_BIN_RIGHT_CLOSED = False  # VOL bins are [low, high)

# Git identity for the bot's own commits (step 7's deep-run commit, and
# aleph_null.py's _commit_list_rates). Shared here rather than duplicated --
# both call sites pass it per-command via `git -c user.name=... -c
# user.email=...`, never via `git config`, so it's never written to .git/config.
GIT_IDENTITY_NAME = 'SBAB Monitor Bot'
GIT_IDENTITY_EMAIL = 'github-actions[bot]@users.noreply.github.com'


def data_dir():
	"""Resolve data directory. Override via SBAB_DATA_DIR env var for testing."""
	return Path(os.environ.get('SBAB_DATA_DIR', str(Path(__file__).parent.parent / 'data')))


# Maturity-derived column name lists (generated from VALID_MATURITIES)
_flat_cols = [f'flat_{m}m' for m in VALID_MATURITIES]
_mean_cols = [f'mean_discount_{m}m' for m in VALID_MATURITIES]
_used_cols = [f'used_for_{m}m' for m in VALID_MATURITIES]


# =============================================================================
# SCHEMA DEFINITIONS
# =============================================================================

# Step 1 output: transformed scraper results
# (transformed from raw API response - see docstring above for raw format)
SCRAPER_OUTPUT_SCHEMA = {
	'columns': [
		'url', 'loan_amount', 'ltv', 'period',
		'offered_interest_rate', 'scraped_at', 'bank', 'json'
	],
	'dtypes': {
		'url': 'object',
		'loan_amount': 'int64',
		'ltv': 'float64',
		'period': 'int64',
		'offered_interest_rate': 'float64',  # 2dp, from API's "Rantesats"
		'scraped_at': 'object',
		'bank': 'object',
		'json': 'object'  # raw API JSON item as string
	}
}

# Step 3a output: todays_pricing_df (same as scraper output - raw per-call data)
TODAYS_PRICING_SCHEMA = SCRAPER_OUTPUT_SCHEMA  # alias

# Step 3a output: per-bin uniformity flags
BIN_UNIFORM_SCHEMA = {
	'columns': ['ltv_bin', 'vol_bin'] + _flat_cols,
	'dtypes': {
		'ltv_bin': 'object',
		'vol_bin': 'object',
		**{col: 'bool' for col in _flat_cols}
	}
}

# Step 3a output: per-bin mean discounts (FULL PRECISION to detect non-uniformity)
BIN_MEAN_SCHEMA = {
	'columns': ['ltv_bin', 'vol_bin'] + _mean_cols,
	'dtypes': {
		'ltv_bin': 'object',
		'vol_bin': 'object',
		**{col: 'float64' for col in _mean_cols}
	}
}


def rate_precision(values):
	"""Detect decimal places used in rate data. Minimum 2 (integer BPs).

	Returns the smallest number of decimal places (2, 3, or 4) such that
	rounding to that many places doesn't change any value by more than
	a negligible amount.

	>>> rate_precision(pd.Series([3.17, 3.05, 3.34]))
	2
	>>> rate_precision(pd.Series([3.175, 3.050, 3.345]))
	3
	"""
	values = pd.Series(values)
	for dp in [2, 3, 4]:
		if (values - values.round(dp)).abs().max() < 1e-9:
			return dp
	return 4  # fallback

# Prominent boundaries - optional user-input proxies for LTV/VOL break-lines that are important
# to the user's goals (LTV as a fraction, VOL in SEK). Whatever is listed here is ALWAYS added to the
# bin structure, even if SBAB has no price break there. Empty by default: break lines then come only
# from what SBAB's pricing shows.
PROMINENT_LTV_BREAKS = frozenset()
PROMINENT_VOL_BREAKS = frozenset()

# discount_surfaces.csv schema - the canonical storage format for discount surfaces
# TODO (SCHEMA CLEANUP): The 'discount_pattern_id' column is a leftover from an earlier design.
#   Currently always "uniform". Consider removing it entirely, OR repurposing it
#   to encode maturity-specific patterns if SBAB ever introduces non-uniform
#   discounts across maturities. For now, kept for backwards compatibility.
DISCOUNT_SURFACES_CSV_SCHEMA = {
	'columns': [
		'ltv_bin', 'vol_bin', 'discount', 'valid_from', 'valid_to',
		'discount_pattern_id',
	] + _used_cols,
	'dtypes': {
		'ltv_bin': 'object',           # "(0-50)%", "(50-60)%", ..., "(85+)%"
		'vol_bin': 'object',           # "(0-0.5)M", "(0.5-0.6)M", ..., "(5+)M"
		'discount': 'float64',         # 2dp, integer basis points
		'valid_from': 'object',        # "YYYY-MM-DD" or empty
		'valid_to': 'object',          # "YYYY-MM-DD" or empty (empty = current)
		'discount_pattern_id': 'object',  # "uniform" etc.
		**{col: 'int64' for col in _used_cols}  # 1 or 0
	}
}

# Valid email types
VALID_EMAIL_TYPES = ["no_change", "list_rate_change", "deep_run_started", "catastrophic_failure", "maturity_change", "pipeline_failed"]


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _assert_df_schema(df, schema, name):
	"""
	Assert that a DataFrame conforms to a schema.

	Args:
		df: pandas DataFrame to check
		schema: dict with 'columns' and 'dtypes' keys
		name: human-readable name for error messages
	"""
	assert isinstance(df, pd.DataFrame), \
		f"{name}: expected DataFrame, got {type(df).__name__}"

	# Check columns
	expected_cols = set(schema['columns'])
	actual_cols = set(df.columns)

	missing = expected_cols - actual_cols
	extra = actual_cols - expected_cols

	assert not missing, \
		f"{name}: missing columns: {missing}"
	assert not extra, \
		f"{name}: unexpected columns: {extra}"

	# Check dtypes
	# Note: treat 'object', 'string', 'str' as equivalent (pandas version differences)
	string_types = {'object', 'string', 'str'}
	for col, expected_dtype in schema['dtypes'].items():
		actual_dtype = str(df[col].dtype)
		if expected_dtype in string_types:
			assert actual_dtype in string_types, \
				f"{name}: column '{col}' has dtype '{actual_dtype}', expected string-like type"
		else:
			assert actual_dtype == expected_dtype, \
				f"{name}: column '{col}' has dtype '{actual_dtype}', expected '{expected_dtype}'"


def _assert_dict_structure(d, required_keys, name, value_types=None):
	"""
	Assert that a dict has required keys and optionally check value types.

	Args:
		d: dict to check
		required_keys: set or list of required keys
		name: human-readable name for error messages
		value_types: optional dict of {key: expected_type}
	"""
	assert isinstance(d, dict), \
		f"{name}: expected dict, got {type(d).__name__}"

	missing = set(required_keys) - set(d.keys())
	assert not missing, \
		f"{name}: missing keys: {missing}"

	if value_types:
		for key, expected_type in value_types.items():
			if key in d:
				assert isinstance(d[key], expected_type), \
					f"{name}: key '{key}' has type '{type(d[key]).__name__}', expected '{expected_type.__name__}'"


# =============================================================================
# PUBLIC ASSERTION FUNCTIONS - DataFrames
# =============================================================================

def assert_scraper_output(df):
	"""Assert step 1 output: transformed scraper results."""
	_assert_df_schema(df, SCRAPER_OUTPUT_SCHEMA, 'scraper_output')


def assert_todays_pricing_df(df):
	"""Assert step 3a output: todays_pricing_df (raw per-API-call data)."""
	_assert_df_schema(df, TODAYS_PRICING_SCHEMA, 'todays_pricing_df')


def assert_bin_uniform_df(df):
	"""Assert step 3a output: discount_surfaces_BIN_uniform_df."""
	_assert_df_schema(df, BIN_UNIFORM_SCHEMA, 'discount_surfaces_BIN_uniform_df')


def assert_bin_mean_df(df):
	"""Assert step 3a output: discount_surfaces_BIN_mean_df."""
	_assert_df_schema(df, BIN_MEAN_SCHEMA, 'discount_surfaces_BIN_mean_df')


def assert_discount_surfaces_df(df):
	"""
	Assert that a DataFrame conforms to the discount_surfaces.csv schema.

	Used by step 6g when creating new discount surface rows, and by any
	step that reads/validates discount_surfaces.csv.
	"""
	_assert_df_schema(df, DISCOUNT_SURFACES_CSV_SCHEMA, 'discount_surfaces_df')


# =============================================================================
# PUBLIC ASSERTION FUNCTIONS - Other Types
# =============================================================================

EXPECTED_API_KEYS = {'Rantebindningstid', 'Rantesats', 'LoptidText', 'EffektivRantesats'}


def assert_api_response(data):
	"""Assert raw SBAB API response structure (per-call, in scraper).

	Validates structure and types but NOT maturity count/set — that check
	lives in detect_maturity_changes(), called once after the full scrape.
	This allows the scraper to collect data even if maturities have changed.
	"""
	assert isinstance(data, list), \
		f"API response: expected list, got {type(data).__name__}"
	assert len(data) > 0, \
		f"API response: empty list"

	for i, item in enumerate(data):
		assert isinstance(item, dict), \
			f"API response[{i}]: expected dict, got {type(item).__name__}"

		missing = EXPECTED_API_KEYS - set(item.keys())
		assert not missing, \
			f"API response[{i}]: missing keys: {missing}"

		mat = item['Rantebindningstid']
		rate = item['Rantesats']
		assert isinstance(mat, int), \
			f"API response[{i}]: Rantebindningstid has type {type(mat).__name__}, expected int"
		assert isinstance(rate, (int, float)), \
			f"API response[{i}]: Rantesats has type {type(rate).__name__}, expected numeric"
		assert RATE_MIN < rate < RATE_MAX, \
			f"API response[{i}]: Rantesats {rate} is outside the plausible range ({RATE_MIN}, {RATE_MAX})"


def detect_maturity_changes(scraper_df):
	"""Detect if scraped maturities differ from VALID_MATURITIES.

	Called once in the orchestrator after the full scrape completes.

	Returns:
		None if maturities match, or {'added': set, 'removed': set} if changed.
	"""
	scraped = set(scraper_df['period'].unique())
	expected = set(VALID_MATURITIES)

	if scraped == expected:
		return None

	return {
		'added': scraped - expected,
		'removed': expected - scraped,
	}


def update_maturities(new_maturities):
	"""Update VALID_MATURITIES and all derived module-level variables at runtime.

	Mutates VALID_MATURITIES in place so all existing references (via
	'from io_contracts import VALID_MATURITIES') see the new list.
	Reassigns derived column lists and schemas via global.
	"""
	global _flat_cols, _mean_cols, _used_cols
	global BIN_UNIFORM_SCHEMA, BIN_MEAN_SCHEMA, DISCOUNT_SURFACES_CSV_SCHEMA

	VALID_MATURITIES[:] = sorted(new_maturities)

	_flat_cols = [f'flat_{m}m' for m in VALID_MATURITIES]
	_mean_cols = [f'mean_discount_{m}m' for m in VALID_MATURITIES]
	_used_cols = [f'used_for_{m}m' for m in VALID_MATURITIES]

	BIN_UNIFORM_SCHEMA = {
		'columns': ['ltv_bin', 'vol_bin'] + _flat_cols,
		'dtypes': {
			'ltv_bin': 'object',
			'vol_bin': 'object',
			**{col: 'bool' for col in _flat_cols}
		}
	}
	BIN_MEAN_SCHEMA = {
		'columns': ['ltv_bin', 'vol_bin'] + _mean_cols,
		'dtypes': {
			'ltv_bin': 'object',
			'vol_bin': 'object',
			**{col: 'float64' for col in _mean_cols}
		}
	}
	DISCOUNT_SURFACES_CSV_SCHEMA = {
		'columns': [
			'ltv_bin', 'vol_bin', 'discount', 'valid_from', 'valid_to',
			'discount_pattern_id',
		] + _used_cols,
		'dtypes': {
			'ltv_bin': 'object',
			'vol_bin': 'object',
			'discount': 'float64',
			'valid_from': 'object',
			'valid_to': 'object',
			'discount_pattern_id': 'object',
			**{col: 'int64' for col in _used_cols}
		}
	}


def update_valid_maturities_on_disk(new_maturities):
	"""Rewrite the VALID_MATURITIES line in this source file.

	Makes the change permanent so the PR includes the updated constant
	and future runs start with the correct maturity set.
	"""
	import re
	source_path = Path(__file__)
	content = source_path.read_text()

	new_line = f'VALID_MATURITIES = {sorted(new_maturities)}'
	content = re.sub(
		r'^VALID_MATURITIES\s*=\s*\[.*?\]',
		new_line,
		content,
		count=1,
		flags=re.MULTILINE,
	)
	source_path.write_text(content)


def assert_list_rate_changes(result):
	"""
	Assert step 2 output: list_rate_changes.

	Can be None (no changes) or dict of {maturity: {'old': float, 'new': float, 'delta': float}}.
	"""
	if result is None:
		return  # valid: no changes

	assert isinstance(result, dict), \
		f"list_rate_changes: expected dict or None, got {type(result).__name__}"

	for maturity, change in result.items():
		assert maturity in VALID_MATURITIES, \
			f"list_rate_changes: invalid maturity {maturity}"
		_assert_dict_structure(
			change,
			required_keys=['old', 'new', 'delta'],
			name=f"list_rate_changes[{maturity}]",
			value_types={'old': (int, float), 'new': (int, float), 'delta': (int, float)}
		)


def assert_deep_run_signal(result):
	"""Assert step 4 output: deep_run_signal."""
	_assert_dict_structure(
		result,
		required_keys=['trigger_deep_run', 'reason'],
		name='deep_run_signal',
		value_types={'trigger_deep_run': bool}
	)
	# reason can be str or None
	assert result['reason'] is None or isinstance(result['reason'], str), \
		f"deep_run_signal: 'reason' must be str or None, got {type(result['reason']).__name__}"


def assert_email_type(result):
	"""Assert step 5a output: email_type."""
	assert isinstance(result, str), \
		f"email_type: expected str, got {type(result).__name__}"
	assert result in VALID_EMAIL_TYPES, \
		f"email_type: invalid value '{result}', must be one of {VALID_EMAIL_TYPES}"


def assert_rasterized_surfaces(result):
	"""
	Assert step 6c output: rasterized_surfaces dict.

	Dict of {maturity: 2D numpy array} for all 8 maturities.

	NOTE: Step 6c returns a tuple (rasterized_surfaces, ltv_probes, vol_probes).
	This function only validates the rasterized_surfaces dict.
	"""
	# TODO: Add assert_full_rasterized_result() to validate the full tuple
	#       including ltv_probes (list of floats) and vol_probes (list of ints)
	assert isinstance(result, dict), \
		f"rasterized_surfaces: expected dict, got {type(result).__name__}"

	for maturity in VALID_MATURITIES:
		assert maturity in result, \
			f"rasterized_surfaces: missing maturity {maturity}"
		arr = result[maturity]
		assert isinstance(arr, np.ndarray), \
			f"rasterized_surfaces[{maturity}]: expected np.ndarray, got {type(arr).__name__}"
		assert arr.ndim == 2, \
			f"rasterized_surfaces[{maturity}]: expected 2D array, got {arr.ndim}D"


def assert_break_lines(result):
	"""Assert step 6d output: break_lines."""
	_assert_dict_structure(
		result,
		required_keys=['ltv_breaks', 'vol_breaks'],
		name='break_lines'
	)
	assert isinstance(result['ltv_breaks'], (set, list, frozenset)), \
		f"break_lines['ltv_breaks']: expected set or list, got {type(result['ltv_breaks']).__name__}"
	assert isinstance(result['vol_breaks'], (set, list, frozenset)), \
		f"break_lines['vol_breaks']: expected set or list, got {type(result['vol_breaks']).__name__}"

	# Validate prominent boundaries are included
	assert_prominent_boundaries_included(result)


def assert_prominent_boundaries_included(break_lines):
	"""
	Assert that break_lines include all prominent boundaries.

	Prominent boundaries are user-input proxies for LTV/VOL break-lines that
	are important to the user's goals; they must always be present, regardless
	of SBAB's pricing decisions. A no-op while both sets are empty (the default).
	"""
	ltv_breaks = set(break_lines['ltv_breaks'])
	vol_breaks = set(break_lines['vol_breaks'])

	missing_ltv = PROMINENT_LTV_BREAKS - ltv_breaks
	missing_vol = PROMINENT_VOL_BREAKS - vol_breaks

	assert not missing_ltv, \
		f"break_lines missing required prominent LTV boundaries: {missing_ltv}"
	assert not missing_vol, \
		f"break_lines missing required prominent VOL boundaries: {missing_vol}"


def assert_bins(result):
	"""Assert step 6e output: bins."""
	_assert_dict_structure(
		result,
		required_keys=['LTV_BINS', 'VOL_BINS', 'LTV_LABELS', 'VOL_LABELS'],
		name='bins'
	)
	for key in ['LTV_BINS', 'VOL_BINS', 'LTV_LABELS', 'VOL_LABELS']:
		assert isinstance(result[key], list), \
			f"bins['{key}']: expected list, got {type(result[key]).__name__}"


def assert_validation_result(result):
	"""Assert step 6j output: validation_result."""
	_assert_dict_structure(
		result,
		required_keys=['passed', 'reason'],
		name='validation_result',
		value_types={'passed': bool}
	)
	assert result['reason'] is None or isinstance(result['reason'], str), \
		f"validation_result: 'reason' must be str or None, got {type(result['reason']).__name__}"


# =============================================================================
# TODO: VALUE RANGE ASSERTIONS (future)
# =============================================================================
#
# def assert_ltv_range(df, col='ltv'):
#     """Assert 0 < ltv < 1"""
#     assert (df[col] > 0).all() and (df[col] < 1).all(), ...
#
# def assert_maturity_values(df, col='period'):
#     """Assert period in VALID_MATURITIES"""
#     assert df[col].isin(VALID_MATURITIES).all(), ...
#
# def assert_2dp_precision(df, col):
#     """Assert values are rounded to 2 decimal places"""
#     rounded = df[col].round(2)
#     assert (df[col] == rounded).all(), ...
