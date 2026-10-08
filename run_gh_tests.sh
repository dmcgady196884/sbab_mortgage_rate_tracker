#!/bin/bash
# Trigger the 3 deep-run test scenarios on GitHub Actions.
# Runs on the current branch with is_test=true (TEST-prefixed emails, DO NOT MERGE PRs).
# Starts are staggered by 15s to avoid branch name collisions.
#
# The list_rate_change scenario is excluded — it auto-commits fake list rates
# to the branch. Run it locally instead: pytest tests/test_pipeline.py::test_list_rate_change -v -m slow
#
# Usage:
#   ./run_gh_tests.sh              # with emails
#   ./run_gh_tests.sh --no-email   # without emails

BRANCH=$(git rev-parse --abbrev-ref HEAD)
SEND_EMAIL=true

if [ "$1" = "--no-email" ]; then
    SEND_EMAIL=false
fi

echo "Triggering 3 deep-run test scenarios on branch: $BRANCH (send_email=$SEND_EMAIL)"

for scenario in discount_surface_change maturity_discovered maturity_closed; do
    gh workflow run daily_scrape.yml \
        --ref "$BRANCH" \
        -f is_test=true \
        -f send_email="$SEND_EMAIL" \
        -f data_dir="data/test_fixtures/$scenario/"
    echo "  triggered: $scenario"
    if [ "$scenario" != "maturity_closed" ]; then
        sleep 15
    fi
done

echo "Done. Monitor with: gh run list --limit 3"
