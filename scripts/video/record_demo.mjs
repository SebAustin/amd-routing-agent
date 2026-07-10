#!/usr/bin/env node
/**
 * Playwright recorder for the AMD Hackathon demo video.
 *
 * Records two kinds of shots into scripts/video/build/raw/:
 *   - Slide shots (1, 2, 6, 7): opens the self-contained HTML slide, calls
 *     its `start()` staged-reveal function, records for that shot's
 *     narration duration (from build/timing.json) + 1s.
 *   - Live shots (3, 4, 5): drives the deployed dashboard (or a local
 *     fallback) through real /solve calls, typing prompts char-by-char,
 *     waiting on the actual network response (never a fixed timer), and
 *     recording the displayed route/tokens/answer into
 *     build/live_shot_values.json for the narration-reconciliation step.
 *
 * Usage:
 *   node record_demo.mjs                 # everything (slides + live shots)
 *   node record_demo.mjs --slides 1,2    # only these slide shots
 *   node record_demo.mjs --shots 3       # only shot 3
 *   node record_demo.mjs --local         # force the local webapp fallback
 *
 * Resumable: only the requested shots are (re)recorded; existing raw
 * videos for shots not requested are left untouched.
 */

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const BUILD_DIR = path.join(HERE, "build");
const RAW_DIR = path.join(BUILD_DIR, "raw");
const SLIDES_DIR = path.join(HERE, "slides");
const BUILD_LOG = path.join(BUILD_DIR, "build_log.txt");
const LIVE_VALUES_PATH = path.join(BUILD_DIR, "live_shot_values.json");

const SPACE_URL = "https://sebaustin-amd-routing-agent-demo.hf.space";
const LOCAL_URL = "http://127.0.0.1:8000";
const VIEWPORT = { width: 1920, height: 1080 };

const SLIDE_FILES = {
  1: "s1_title.html",
  2: "s2_cascade.html",
  6: "s6_results.html",
  7: "s7_gemma_close.html",
};

const SHOT3_PROMPT = "What is 847 * 36?";
const SHOT4_PROMPT =
  'Classify the sentiment of this review as one of: positive, negative, neutral. Review: "This is the best purchase I\'ve made all year, absolutely love it!"';
const SHOT5_PROMPTS = [
  "How many days are there between 2024-03-01 and 2024-07-15?",
  "Convert 12 miles to kilometers.",
  "What is 214 + 998?",
];
const SHOT5_SPACING_MS = 9000;

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
  fs.mkdirSync(BUILD_DIR, { recursive: true });
  fs.appendFileSync(BUILD_LOG, line + "\n");
}

function parseArgs(argv) {
  const args = { slides: null, shots: null, local: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--slides") args.slides = argv[++i].split(",").map(Number);
    else if (a === "--shots") args.shots = argv[++i].split(",").map(Number);
    else if (a === "--local") args.local = true;
    else if (a === "--all") {
      args.slides = [1, 2, 6, 7];
      args.shots = [3, 4, 5];
    }
  }
  if (args.slides === null && args.shots === null) {
    args.slides = [1, 2, 6, 7];
    args.shots = [3, 4, 5];
  }
  args.slides = args.slides || [];
  args.shots = args.shots || [];
  return args;
}

function loadTiming() {
  const p = path.join(BUILD_DIR, "timing.json");
  if (!fs.existsSync(p)) {
    throw new Error(`${p} missing — run narration.py first`);
  }
  const timing = JSON.parse(fs.readFileSync(p, "utf8"));
  const byShot = {};
  for (const t of timing) byShot[t.shot] = t;
  return byShot;
}

async function finalizeVideo(page, destName) {
  const video = page.video();
  await page.close();
  if (!video) return null;
  const tmpPath = await video.path();
  const destPath = path.join(RAW_DIR, destName);
  await fsp.mkdir(RAW_DIR, { recursive: true });
  await fsp.rename(tmpPath, destPath);
  return destPath;
}

async function recordSlide(browser, shot, timing) {
  const file = SLIDE_FILES[shot];
  if (!file) throw new Error(`no slide mapped for shot ${shot}`);
  const shotTiming = timing[shot];
  if (!shotTiming) throw new Error(`no narration timing for shot ${shot}`);
  const holdMs = Math.round(shotTiming.duration_s * 1000) + 1000;

  log(`shot ${shot}: recording slide ${file} for ${holdMs}ms`);
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: RAW_DIR, size: VIEWPORT },
  });
  const page = await context.newPage();
  const fileUrl = "file://" + path.join(SLIDES_DIR, file);
  await page.goto(fileUrl);
  await page.evaluate(() => window.start());
  await page.waitForTimeout(holdMs);
  const dest = await finalizeVideo(page, `s${shot}.webm`);
  await context.close();
  log(`shot ${shot}: wrote ${dest}`);
}

async function serverReachable(baseUrl) {
  try {
    const res = await fetch(`${baseUrl}/healthz`, { signal: AbortSignal.timeout(8000) });
    return res.ok;
  } catch {
    return false;
  }
}

let localServerProc = null;

async function ensureLocalServer() {
  if (await serverReachable(LOCAL_URL)) return LOCAL_URL;
  log("starting local fallback webapp: uv run python -m routing_agent.webapp");
  const envPath = path.join(REPO_ROOT, ".env");
  const envVars = {};
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
      const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m) envVars[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  }
  localServerProc = spawn("uv", ["run", "python", "-m", "routing_agent.webapp"], {
    cwd: REPO_ROOT,
    env: { ...process.env, ...envVars, PORT: "8000" },
    stdio: ["ignore", "pipe", "pipe"],
    detached: false,
  });
  localServerProc.stdout.on("data", (d) => log(`[local-server] ${d.toString().trim()}`));
  localServerProc.stderr.on("data", (d) => log(`[local-server] ${d.toString().trim()}`));

  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (await serverReachable(LOCAL_URL)) return LOCAL_URL;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("local fallback webapp did not become healthy in time");
}

async function resolveBaseUrl(forceLocal) {
  if (forceLocal) return ensureLocalServer();
  if (await serverReachable(SPACE_URL)) {
    log(`using live Space: ${SPACE_URL}`);
    return SPACE_URL;
  }
  log(`live Space unreachable, falling back to local webapp`);
  return ensureLocalServer();
}

async function typeAndSubmit(page, promptText) {
  const input = page.locator("#promptInput");
  await input.click();
  await input.fill("");
  await input.pressSequentially(promptText, { delay: 40 });

  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/solve") && r.request().method() === "POST", {
      timeout: 30000,
    }),
    page.locator("#submitBtn").click(),
  ]);

  await page.locator("#routeGrid").waitFor({ state: "visible", timeout: 15000 });
  const status = response.status();
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { status, body };
}

async function readDisplayedValues(page) {
  const get = async (sel) => (await page.locator(sel).textContent())?.trim() ?? null;
  return {
    tier: await get("#routeTier"),
    model: await get("#routeModel"),
    taskType: await get("#routeTaskType"),
    tokens: await get("#routeTokens"),
    cost: await get("#routeCost"),
    savings: await get("#routeSavings"),
    answer: await get("#answerBox"),
  };
}

async function readStats(page) {
  const get = async (sel) => (await page.locator(sel).textContent())?.trim() ?? null;
  return {
    solved: await get("#statSolved"),
    tokens: await get("#statTokens"),
    baseline: await get("#statBaseline"),
    savings: await get("#statSavings"),
    cost: await get("#statCost"),
    tier1Count: await get("#countTier1"),
    tier2Count: await get("#countTier2"),
  };
}

function loadLiveValues() {
  if (fs.existsSync(LIVE_VALUES_PATH)) {
    return JSON.parse(fs.readFileSync(LIVE_VALUES_PATH, "utf8"));
  }
  return {};
}

function saveLiveValues(values) {
  fs.mkdirSync(BUILD_DIR, { recursive: true });
  fs.writeFileSync(LIVE_VALUES_PATH, JSON.stringify(values, null, 2) + "\n");
}

async function recordShot3(browser, baseUrl, liveValues) {
  log("shot 3: recording tier-0 live demo");
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: RAW_DIR, size: VIEWPORT },
  });
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: "load" });
  const { status, body } = await typeAndSubmit(page, SHOT3_PROMPT);
  if (status !== 200) throw new Error(`shot 3: /solve returned ${status}`);
  await page.waitForTimeout(3000); // linger on the result per script
  const displayed = await readDisplayedValues(page);
  liveValues.shot3 = { prompt: SHOT3_PROMPT, status, apiResponse: body, displayed };
  const dest = await finalizeVideo(page, "s3.webm");
  await context.close();
  log(`shot 3: wrote ${dest}; route=${displayed.tier} tokens=${displayed.tokens} answer=${displayed.answer}`);
}

async function recordShot4(browser, baseUrl, liveValues) {
  log("shot 4: recording tier-1 live demo");
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: RAW_DIR, size: VIEWPORT },
  });
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: "load" });
  const { status, body } = await typeAndSubmit(page, SHOT4_PROMPT);
  if (status !== 200) throw new Error(`shot 4: /solve returned ${status}`);
  await page.waitForTimeout(3000); // linger on the result per script
  const displayed = await readDisplayedValues(page);
  liveValues.shot4 = { prompt: SHOT4_PROMPT, status, apiResponse: body, displayed };
  const dest = await finalizeVideo(page, "s4.webm");
  await context.close();
  log(`shot 4: wrote ${dest}; route=${displayed.tier} model=${displayed.model} tokens=${displayed.tokens} answer=${displayed.answer}`);
}

async function recordShot5(browser, baseUrl, liveValues) {
  log("shot 5: recording savings-counter climb (3 prompts, 9s spacing)");
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: RAW_DIR, size: VIEWPORT },
  });
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: "load" });

  const results = [];
  for (let i = 0; i < SHOT5_PROMPTS.length; i++) {
    const prompt = SHOT5_PROMPTS[i];
    const { status, body } = await typeAndSubmit(page, prompt);
    const displayed = await readDisplayedValues(page);
    const stats = await readStats(page);
    results.push({ prompt, status, apiResponse: body, displayed, statsAfter: stats });
    log(`shot 5: prompt ${i + 1}/${SHOT5_PROMPTS.length} -> route=${displayed.tier} tokens=${displayed.tokens}`);
    if (i < SHOT5_PROMPTS.length - 1) {
      await page.waitForTimeout(SHOT5_SPACING_MS);
    }
  }
  await page.waitForTimeout(2000);
  liveValues.shot5 = results;
  const dest = await finalizeVideo(page, "s5.webm");
  await context.close();
  log(`shot 5: wrote ${dest}`);
}

async function recordLiveShot(browser, shotFn, shotNum, liveValues, forceLocal) {
  let baseUrl = await resolveBaseUrl(forceLocal);
  try {
    await shotFn(browser, baseUrl, liveValues);
  } catch (err) {
    log(`shot ${shotNum}: live attempt failed (${err.message}); falling back to local webapp`);
    baseUrl = await ensureLocalServer();
    await shotFn(browser, baseUrl, liveValues);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  log(`starting recorder: slides=${args.slides.join(",")} shots=${args.shots.join(",")} local=${args.local}`);

  const timing = loadTiming();
  const browser = await chromium.launch();
  const liveValues = loadLiveValues();

  try {
    for (const shot of args.slides) {
      await recordSlide(browser, shot, timing);
    }

    if (args.shots.includes(3)) {
      await recordLiveShot(browser, recordShot3, 3, liveValues, args.local);
      saveLiveValues(liveValues);
    }
    if (args.shots.includes(4)) {
      await recordLiveShot(browser, recordShot4, 4, liveValues, args.local);
      saveLiveValues(liveValues);
    }
    if (args.shots.includes(5)) {
      await recordLiveShot(browser, recordShot5, 5, liveValues, args.local);
      saveLiveValues(liveValues);
    }
  } finally {
    await browser.close();
    if (localServerProc) {
      log("stopping local fallback webapp");
      localServerProc.kill();
    }
  }

  log("recording complete");
}

main().catch((err) => {
  log(`FATAL: ${err.stack || err.message}`);
  process.exitCode = 1;
});
