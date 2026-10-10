#!/usr/bin/env bash
# Assemble the single GitHub Pages artifact: the basketball site at the root and the football site under /football/.
# Every deploy (basketball refresh, football refresh, site-only deploy) must publish BOTH, or one deploy would erase the other site.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf _pages
mkdir -p _pages/football
cp -r site/. _pages/
cp -r football/site/. _pages/football/
rm -rf _pages/football/test            # parity test lives next to the site code; it is not part of the published site
