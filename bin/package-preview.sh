#!/usr/bin/env bash
# Builds the site and zips the result into a single file you can send to
# someone, or drag onto https://app.netlify.com/drop for an instant public
# link. Requires Ruby + Bundler (see README).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Installing gems..."
bundle install --quiet

echo "Building site..."
bundle exec jekyll build

OUT="sumnerlab-preview.zip"
rm -f "$OUT"
(cd _site && zip -rq "../$OUT" .)

echo "Done: $OUT"
echo "Unzip it and run 'python3 -m http.server 8000' from inside the folder, then open http://localhost:8000"
echo "Or drag the unzipped folder onto https://app.netlify.com/drop for a shareable link."
