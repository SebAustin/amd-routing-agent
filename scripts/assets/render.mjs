// scripts/assets/render.mjs
//
// Renders launch/cover.png (1920x1080 PNG) from scripts/assets/cover.html and
// launch/deck.pdf (8 sequential 1280x720 pages) from scripts/assets/deck.html,
// using Playwright's Chromium. Self-contained HTML/CSS only, no external
// network calls at render time.
//
// Usage:
//   node scripts/assets/render.mjs cover
//   node scripts/assets/render.mjs deck
//   node scripts/assets/render.mjs deck-slides   (also dumps one PNG per slide
//                                                  for visual QA)
//   node scripts/assets/render.mjs all

import { createRequire } from "module";
import Module from "module";
import path from "path";
import { fileURLToPath } from "url";

// Playwright is installed outside the repo (scratchpad); resolve it via
// NODE_PATH set by the caller, or fall back to a normal require() if it is
// ever added as a real project dependency.
Module._initPaths();
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const assetsDir = __dirname;
const launchDir = path.join(repoRoot, "launch");

const SLIDE_W = 1280;
const SLIDE_H = 720;

async function renderCover(browser) {
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  await page.goto("file://" + path.join(assetsDir, "cover.html"));
  await page.waitForTimeout(120); // let fonts/paint settle
  const out = path.join(launchDir, "cover.png");
  await page.screenshot({ path: out, fullPage: false });
  await page.close();
  console.log("wrote", out);
}

async function renderDeckPdf(browser) {
  const page = await browser.newPage({
    viewport: { width: SLIDE_W, height: SLIDE_H },
    deviceScaleFactor: 1,
  });
  await page.goto("file://" + path.join(assetsDir, "deck.html"));
  await page.waitForTimeout(120);
  const out = path.join(launchDir, "deck.pdf");
  await page.pdf({
    path: out,
    width: `${SLIDE_W}px`,
    height: `${SLIDE_H}px`,
    printBackground: true,
    margin: { top: 0, right: 0, bottom: 0, left: 0 },
  });
  await page.close();
  console.log("wrote", out);
}

async function renderDeckSlidePngs(browser) {
  const page = await browser.newPage({
    viewport: { width: SLIDE_W, height: SLIDE_H },
    deviceScaleFactor: 1,
  });
  await page.goto("file://" + path.join(assetsDir, "deck.html"));
  await page.waitForTimeout(120);
  const slides = await page.$$(".slide");
  console.log("found", slides.length, "slide sections");
  for (let i = 0; i < slides.length; i++) {
    const out = path.join(assetsDir, `slide-${i + 1}.png`);
    await slides[i].screenshot({ path: out });
    console.log("wrote", out);
  }
  await page.close();
}

async function main() {
  const mode = process.argv[2] || "all";
  const browser = await chromium.launch();
  try {
    if (mode === "cover" || mode === "all") await renderCover(browser);
    if (mode === "deck" || mode === "all") await renderDeckPdf(browser);
    if (mode === "deck-slides") await renderDeckSlidePngs(browser);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
