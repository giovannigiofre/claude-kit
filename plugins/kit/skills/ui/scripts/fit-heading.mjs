// Finds the largest font size at which a heading fits its limits, by measuring in a real browser.
//
//   node fit-heading.mjs <url | file.html> [--selector h1] [--max 48] [--min 20] [--lines 3] [--share 0.33]
//                        [--widths 390,768,1440] [--height 844]
//
// For each width: the largest size in [min, max] (px, step 1) where the heading wraps to at most
// --lines lines and its box takes at most --share of the first screen. Prints one row per width and
// a CSS clamp() that passes through the phone and desktop sizes. Exit 1 if even --min does not fit.
// Needs Playwright (the project's or a global install) and an installed Chrome.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf('--' + name); return i >= 0 ? args[i + 1] : dflt; };
const target = args.find((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
if (!target) { console.error('usage: node fit-heading.mjs <url | file.html> [options]'); process.exit(2); }
const url = /^https?:|^file:/.test(target) ? target : pathToFileURL(resolve(target)).href;
const selector = opt('selector', 'h1');
const max = Number(opt('max', 48)), min = Number(opt('min', 20));
const maxLines = Number(opt('lines', 3)), share = Number(opt('share', 0.33));
const widths = opt('widths', '390,1440').split(',').map(Number);
const screenH = Number(opt('height', 844));

let chromium;
try { ({ chromium } = createRequire(resolve(process.cwd(), 'package.json'))('playwright')); }
catch { try { ({ chromium } = await import('playwright')); } catch { console.error('Playwright not found: run it from a project that has it, or npm i -g playwright'); process.exit(2); } }

const browser = await chromium.launch({ channel: 'chrome' });
const rows = [];
for (const w of widths) {
  const page = await browser.newPage({ viewport: { width: w, height: w >= 1024 ? 900 : screenH } });
  await page.goto(url);
  await page.waitForTimeout(300);
  const fits = (px) => page.evaluate(({ selector, px }) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    el.style.fontSize = px + 'px';
    const r = el.getBoundingClientRect();
    const lh = parseFloat(getComputedStyle(el).lineHeight) || px * 1.2;
    return { lines: Math.round(r.height / lh), height: r.height, vh: innerHeight, text: el.textContent.trim().length };
  }, { selector, px });
  const first = await fits(max);
  if (!first) { console.error(`no element matches ${selector}`); process.exit(2); }
  let best = null;
  for (let px = max; px >= min; px--) {
    const m = await fits(px);
    if (m.lines <= maxLines && m.height <= share * m.vh) { best = { px, ...m }; break; }
  }
  rows.push({ w, best, chars: first.text });
  await page.close();
}
await browser.close();

let ok = true;
for (const { w, best, chars } of rows) {
  if (!best) { ok = false; console.log(`${w}px: does not fit even at ${min}px (${chars} characters): shorten the text`); continue; }
  console.log(`${w}px: ${best.px}px · ${best.lines} line(s) · ${Math.round(100 * best.height / best.vh)}% of the first screen`);
}
const phone = rows[0]?.best, desk = rows[rows.length - 1]?.best;
if (ok && phone && desk && rows.length > 1) {
  const [w1, w2] = [rows[0].w, rows[rows.length - 1].w];
  const slope = (desk.px - phone.px) / (w2 - w1);
  const base = phone.px - slope * w1;
  const lo = Math.min(phone.px, desk.px), hi = Math.max(phone.px, desk.px);
  console.log(`css: font-size: clamp(${(lo / 16).toFixed(3)}rem, ${(base / 16).toFixed(3)}rem + ${(slope * 100).toFixed(3)}vw, ${(hi / 16).toFixed(3)}rem);`);
}
process.exit(ok ? 0 : 1);
