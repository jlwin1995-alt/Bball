#!/bin/bash
# Daily refresh on your own machine (alternative to the GitHub Action). Needs the Mac awake at run time.
#   crontab -e   ->   17 6 * * *  /Users/YOU/Bball/scripts/morning.sh >> /Users/YOU/bball.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
python -m pipeline.fetch_espn                      # box scores, schedule, injuries, rosters (preseason games auto-included pre-season)
test -f data/raw/preseason_minutes.json || python -m pipeline.preseason_minutes || true
python -m pipeline.backtest --every 5 --write-spread > /dev/null
python -m pipeline.build
echo "refreshed $(date)"
