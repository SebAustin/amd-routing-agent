#!/usr/bin/env node
/**
 * Render each caption in launch/video/demo.srt to a transparent 1920x1080
 * PNG (Playwright/Chromium instead of ffmpeg's subtitles/drawtext filters,
 * since the ffmpeg build in this environment has neither libass nor
 * libfreetype). assemble_pipeline.py's `burn` step then composites these
 * onto the assembled video with per-caption `overlay=enable='between(t,..)'`
 * windows, using the same start/end timestamps.
 *
 * Output: build/captions/capNNN.png + build/captions_manifest.json
 * ({file, start_s, end_s}[]).
 */

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const SRT_PATH = path.join(REPO_ROOT, "launch", "video", "demo.srt");
const CAPTIONS_DIR = path.join(HERE, "build", "captions");
const MANIFEST_PATH = path.join(HERE, "build", "captions_manifest.json");

function srtTimeToSeconds(t) {
  const m = t.match(/(\d+):(\d+):(\d+),(\d+)/);
  const [, h, mnt, s, ms] = m.map(Number);
  return h * 3600 + mnt * 60 + s + ms / 1000;
}

function parseSrt(text) {
  const blocks = text.trim().split(/\n\n+/);
  const captions = [];
  for (const block of blocks) {
    const lines = block.split("\n");
    if (lines.length < 2) continue;
    const timeLine = lines[1];
    const m = timeLine.match(/([\d:,]+)\s*-->\s*([\d:,]+)/);
    if (!m) continue;
    const start_s = srtTimeToSeconds(m[1]);
    const end_s = srtTimeToSeconds(m[2]);
    const text = lines.slice(2).join("\n");
    captions.push({ start_s, end_s, text });
  }
  return captions;
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function captionHtml(text) {
  const lines = text.split("\n").map(escapeHtml).join("<br/>");
  return `<!doctype html>
<html><head><meta charset="utf-8" />
<style>
  html, body {
    margin: 0;
    width: 1920px;
    height: 1080px;
    background: transparent;
  }
  .wrap {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 64px;
    display: flex;
    justify-content: center;
  }
  .box {
    max-width: 1400px;
    background: rgba(11, 11, 13, 0.72);
    border-radius: 8px;
    padding: 12px 28px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
    font-size: 30px;
    line-height: 1.35;
    color: #f4f4f5;
    text-align: center;
    font-weight: 500;
  }
</style></head>
<body>
  <div class="wrap"><div class="box">${lines}</div></div>
</body></html>`;
}

async function main() {
  if (!fs.existsSync(SRT_PATH)) {
    throw new Error(`${SRT_PATH} missing — run assemble_pipeline.py concat + narration.py --emit-srt first`);
  }
  const captions = parseSrt(fs.readFileSync(SRT_PATH, "utf8"));
  fs.mkdirSync(CAPTIONS_DIR, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

  const manifest = [];
  for (let i = 0; i < captions.length; i++) {
    const cap = captions[i];
    const fileName = `cap${String(i + 1).padStart(3, "0")}.png`;
    const filePath = path.join(CAPTIONS_DIR, fileName);
    await page.setContent(captionHtml(cap.text));
    await page.screenshot({ path: filePath, omitBackground: true });
    manifest.push({ file: `build/captions/${fileName}`, start_s: cap.start_s, end_s: cap.end_s });
    console.log(`caption ${i + 1}/${captions.length}: ${cap.start_s.toFixed(2)}-${cap.end_s.toFixed(2)}s -> ${fileName}`);
  }

  await browser.close();
  fs.writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2) + "\n");
  console.log(`wrote ${MANIFEST_PATH} (${manifest.length} captions)`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
