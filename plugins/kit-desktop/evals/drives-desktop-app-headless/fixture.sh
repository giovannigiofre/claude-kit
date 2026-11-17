#!/bin/sh
# A small Electron app repo with a release bundle path named in the README; no app is really built.
set -e
git init -q .
git config user.email eval@example.invalid
git config user.name eval
mkdir -p dist/mac src
cat > README.md <<'MD'
# Ledger

Desktop bookkeeping app (Electron). `npm run dist` writes the release bundle to `dist/mac/Ledger.app`.
Settings live in the Settings window (menu Ledger > Settings...), stored in `~/Library/Application Support/Ledger/config.json`.
MD
cat > src/settings.js <<'JS'
// Settings window: the "Dark mode" toggle writes config.darkMode and re-themes the app.
module.exports = { keys: ["darkMode", "currency"] };
JS
cat > package.json <<'JSON'
{ "name": "ledger", "version": "0.9.0", "scripts": { "dist": "electron-builder --mac" } }
JSON
git add -A && git commit -qm "ledger 0.9.0"
