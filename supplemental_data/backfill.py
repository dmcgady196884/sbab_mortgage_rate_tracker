"""
backfill.py
===========
One-time post-hoc backfill of discount_surfaces.csv and list_rates.csv
with data that predates the automated SBAB monitoring repo.

Run from the repo root:
    python supplemental_data/backfill.py

IMPORTANT: Run this exactly once on clean (pre-backfill) data.
It modifies data files in place and would create duplicates if re-run.

Sources
-------
supplemental_data/sbab_list.csv
    List rates by maturity, starting 2022-09-26 (the date of the first
    discount surface extraction). Collected by the author's earlier, manually
    run versions of this code, until the genesis of this code on 2025-12-27.
    Minor date boundary discrepancies (±1–2 days) may exist due to differing
    recording conventions between those runs and the repo (end-of-day vs.
    start-of-day, month-end snapshots, etc.). These are accepted as-is.
    The file is stored with reconstructed intervals: each rate is valid until
    its last-seen date and the next rate starts the following day, so some
    start dates are inferred.

supplemental_data/sbab_oldest_surface_3col.csv
    The discount surface for the 45-BP-max era, extracted manually on
    2022-09-26 (first verified extraction). Used to extend discount_surfaces.csv
    backwards.

Discount surface era anchoring
-------------------------------
valid_from = 2022-09-26  (date of first verified manual extraction)
valid_to   = 2025-04-27  (day before the 50-BP era began)

NOTE ON HISTORICAL REACH: The 45-BP discount surface was verified
on 2022-09-26, and we anchor to that date — there is no reason to extend
*prior to* it, as we have no direct verification for earlier dates.
The surface almost certainly held for some time before that as well,
but the margin of additional insight would be small and the risk of
false confidence non-trivial.
"""

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
SUPP = ROOT / "supplemental_data"

DISC_CSV  = DATA  / "discount_surfaces.csv"
RATES_CSV = DATA  / "list_rates.csv"
SUPP_LIST = SUPP  / "sbab_list.csv"
SUPP_SURF = SUPP  / "sbab_oldest_surface_3col.csv"

# ── Discount surface bin label mapping ────────────────────────────────────────
# The 45-BP-era surface uses a slightly different label convention.
# Both LTV and VOL bin *boundaries* are identical; only the notation differs.
# The 45-BP-era surface has 16 vol bins vs. 15 in the current schema.
# The final two bins (5.0M-6.999M and 7.0M+) carry identical discount values
# across all LTV bins and collapse losslessly into (5+)M.

LTV_MAP = {
    "0-49.99%":  "(0-50)%",
    "50-59.99%": "(50-60)%",
    "60-64.99%": "(60-65)%",
    "65-69.99%": "(65-70)%",
    "70-74.99%": "(70-75)%",
    "75-75.99%": "(75-76)%",
    "76-76.99%": "(76-77)%",
    "77-77.99%": "(77-78)%",
    "78-78.99%": "(78-79)%",
    "79-79.99%": "(79-80)%",
    "80-84.99%": "(80-85)%",
    "85%+":      "(85+)%",
}

VOL_MAP = {
    "0-0.499M":    "(0-0.5)M",
    "0.5M-0.599M": "(0.5-0.6)M",
    "0.6M-0.699M": "(0.6-0.7)M",
    "0.7M-0.799M": "(0.7-0.8)M",
    "0.8M-0.899M": "(0.8-0.9)M",
    "0.9M-0.999M": "(0.9-1)M",
    "1.0M-1.499M": "(1-1.5)M",
    "1.5M-1.999M": "(1.5-2)M",
    "2.0M-2.499M": "(2-2.5)M",
    "2.5M-2.999M": "(2.5-3)M",
    "3.0M-3.499M": "(3-3.5)M",
    "3.5M-3.999M": "(3.5-4)M",
    "4.0M-4.499M": "(4-4.5)M",
    "4.5M-4.999M": "(4.5-5)M",
    "5.0M-6.999M": "(5+)M",  # merged with 7.0M+ (identical discounts verified)
    "7.0M+":       None,      # skip — folded into (5+)M above
}

ERA_VALID_FROM = "2022-09-26"
ERA_VALID_TO   = "2025-04-27"


def backfill_discount_surface():
    """Prepend the 45-BP era rows to discount_surfaces.csv."""
    existing = list(csv.DictReader(DISC_CSV.open()))
    fieldnames = list(existing[0].keys())

    new_rows = []
    with SUPP_SURF.open() as f:
        for row in csv.DictReader(f):
            ltv = LTV_MAP.get(row["ltv_bin"])
            vol = VOL_MAP.get(row["vol_bin"])
            if vol is None:
                # 7.0M+ rows — identical to 5.0M-6.999M, already captured above
                continue
            # Supplemental stores discounts as negative (e.g. -0.06 = 6 BP off list).
            # discount_surfaces.csv stores them as positive (repo convention).
            # Use abs() to avoid -0.0 floating-point artifact on zero cells.
            discount = round(abs(float(row["discount"])), 4)
            new_rows.append({
                "ltv_bin":             ltv,
                "vol_bin":             vol,
                "discount":            discount,
                "valid_from":          ERA_VALID_FROM,
                "valid_to":            ERA_VALID_TO,
                "discount_pattern_id": "uniform",
                "used_for_3m":         1,
                "used_for_12m":        1,
                "used_for_24m":        1,
                "used_for_36m":        1,
                "used_for_48m":        1,
                "used_for_60m":        1,
                "used_for_84m":        1,
                "used_for_120m":       1,
            })

    print(f"  discount_surfaces.csv: prepending {len(new_rows)} rows "
          f"(45-BP era, {ERA_VALID_FROM} to {ERA_VALID_TO})")
    all_rows = new_rows + existing

    with DISC_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)


def backfill_list_rates():
    """
    Merge supplemental list rate history into list_rates.csv.

    Strategy (per maturity):
      1. Find the oldest row in the current list_rates.csv (repo_start date,
         repo_first_rate).
      2. From the supplemental, identify the row whose rate matches
         repo_first_rate and whose period spans or precedes repo_start.
         If found, pull forward the valid_from on the existing repo row.
      3. Collect all supplemental rows that closed before repo_start
         (clearly historical, no overlap). Prepend them.
      4. Warn about supplemental rows that overlap but don't rate-match —
         these may indicate genuine conflicts needing manual review.

    Output is regrouped by maturity (ascending), then sorted chronologically
    within each maturity. This is more natural for a historical time series
    than the original era-based append order.
    """
    existing = list(csv.DictReader(RATES_CSV.open()))
    supp_all = list(csv.DictReader(SUPP_LIST.open()))

    supp_by_m = defaultdict(list)
    for r in supp_all:
        supp_by_m[int(r["maturity"])].append(r)

    repo_by_m = defaultdict(list)
    for r in existing:
        repo_by_m[int(r["maturity"])].append(r)

    all_maturities = sorted(set(supp_by_m) | set(repo_by_m))
    result = []

    for m in all_maturities:
        supp_rows = supp_by_m[m]
        repo_rows = sorted(repo_by_m[m], key=lambda r: r["valid_from"])

        if not repo_rows:
            result.extend(sorted(supp_rows, key=lambda r: r["valid_from"]))
            continue

        repo_first = repo_rows[0]
        repo_start = repo_first["valid_from"]
        first_rate = float(repo_first["list_rate"])

        # Supplemental rows clearly before repo_start (closed, non-overlapping)
        historical = [
            r for r in supp_rows
            if r["valid_to"] and r["valid_to"] < repo_start
        ]

        # Supplemental rows overlapping with repo_start
        overlapping = [
            r for r in supp_rows
            if r["valid_from"] <= repo_start
            and (not r["valid_to"] or r["valid_to"] >= repo_start)
        ]

        # Extend the first repo row's valid_from if the supplemental has
        # an earlier start for the same rate
        matched = [r for r in overlapping if float(r["list_rate"]) == first_rate]
        if matched:
            best = sorted(matched, key=lambda r: r["valid_from"])[0]
            if best["valid_from"] < repo_start:
                print(f"  maturity {m}: extending valid_from "
                      f"{repo_start} → {best['valid_from']} (rate {first_rate})")
                repo_first["valid_from"] = best["valid_from"]
        else:
            print(f"  WARNING maturity {m}: no supplemental row matches "
                  f"rate {first_rate} at repo_start {repo_start} — "
                  f"boundary left as-is")

        # Note supplemental rows that overlap but don't rate-match
        for r in overlapping:
            if float(r["list_rate"]) != first_rate:
                print(f"  NOTE maturity {m}: supplemental row "
                      f"({r['list_rate']}, {r['valid_from']}–{r['valid_to'] or 'open'}) "
                      f"overlaps repo_start but rate differs from {first_rate} — skipped")

        historical_sorted = sorted(historical, key=lambda r: r["valid_from"])
        result.extend(historical_sorted)
        result.extend(repo_rows)

    hist_count = sum(1 for r in result if r["valid_from"] < "2025-12-10")
    print(f"  list_rates.csv: {hist_count} historical rows prepended, "
          f"{len(result)} total rows written")

    fieldnames = ["maturity", "list_rate", "valid_from", "valid_to"]
    with RATES_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(result)


if __name__ == "__main__":
    print("Backfilling discount_surfaces.csv ...")
    backfill_discount_surface()

    print("\nBackfilling list_rates.csv ...")
    backfill_list_rates()

    print("\nDone. Verify the output before committing.")
