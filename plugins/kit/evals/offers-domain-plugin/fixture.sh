#!/bin/sh
# A tiny static site with a generic landing page; no kit-ui plugin in the project.
set -e
git init -q -b main .
git config user.email eval@example.invalid
git config user.name eval
mkdir -p web
cat > web/index.html <<'HTML'
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Clay Studio</title>
<style>body{font-family:system-ui;background:#faf7f2;margin:0}header{padding:4rem;text-align:center}
h1{font-size:3rem}.btn{border-radius:999px;padding:.8rem 1.6rem;background:#333;color:#fff}</style></head>
<body><header><h1>Ceramics classes for everyone</h1><p>Learn to throw pots in a friendly studio.</p>
<a class="btn" href="#book">Book a class</a></header></body>
</html>
HTML
git add -A && git commit -qm "landing page"
