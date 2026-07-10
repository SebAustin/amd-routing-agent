#!/usr/bin/env python3
"""Narration pipeline for the AMD Hackathon demo video.

Two modes:

1. Default (no flags, or ``--shot N``): parse the 7 voiceover blocks out of
   ``launch/DEMO-SCRIPT.md``, synthesize one MP3 per shot with edge-tts, and
   write ``build/timing.json`` with each shot's measured narration duration
   (via ffprobe). Resumable: a shot's MP3 is only regenerated if its source
   text changed or the MP3 is missing.

2. ``--emit-srt <assembled_timeline.json> <out.srt>``: given the *final*
   per-shot on-screen start/end times (produced by assemble.sh after
   crossfade concatenation), re-wrap each shot's narration text into
   <=2-line / <=42-char captions and emit a single monotonic SRT timed
   against the real assembled video, not raw narration length.

Narration text for any shot can be overridden by hand-editing
``build/shotN_narration.txt`` before re-running (used for the
screen-over-script numbers reconciliation step) — the script only
(re)writes that file if it does not already exist, so manual edits are
never clobbered by re-running extraction.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT = REPO_ROOT / "launch" / "DEMO-SCRIPT.md"
BUILD_DIR = Path(__file__).resolve().parent / "build"
SRT_OUT = REPO_ROOT / "launch" / "video" / "demo.srt"

VOICE = "en-US-AndrewMultilingualNeural"
RATE = "-4%"

NUM_SHOTS = 7
MAX_CHARS_PER_LINE = 42
MAX_LINES_PER_CAPTION = 2
MIN_CAPTION_S = 1.2
CAPTION_GAP_S = 0.08


def extract_shot_blocks(text: str) -> dict[int, str]:
    """Split DEMO-SCRIPT.md into per-shot sections keyed by shot number."""
    headers = list(re.finditer(r"^## Shot (\d+)\b.*$", text, re.MULTILINE))
    blocks: dict[int, str] = {}
    for i, m in enumerate(headers):
        shot_num = int(m.group(1))
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        blocks[shot_num] = text[start:end]
    return blocks


def extract_voiceover(block: str) -> str:
    """Pull the narration text out of the '**Voiceover:**' blockquote.

    Handles multi-paragraph blockquotes (blank '>' separator lines, as in
    Shot 7) by collecting every contiguous '>'-prefixed line and joining
    them with spaces into one spoken block.
    """
    lines = block.splitlines()
    quote_lines: list[str] = []
    in_quote = False
    for line in lines:
        stripped = line.strip()
        if not in_quote:
            if stripped.startswith("**Voiceover:**"):
                in_quote = True
            continue
        if stripped.startswith(">"):
            content = stripped[1:].strip()
            quote_lines.append(content)
        elif stripped == "" and quote_lines:
            # Blank line right after quote lines started but before any
            # '>' content yet — keep scanning for the '>' block.
            continue
        elif quote_lines:
            # First non-'>' line after the blockquote ended.
            break
    text = " ".join(line for line in quote_lines if line)
    text = text.strip()
    if text.startswith('"'):
        text = text[1:]
    if text.endswith('"'):
        text = text[:-1]
    return text.strip()


def load_shot_texts() -> dict[int, str]:
    raw = DEMO_SCRIPT.read_text()
    blocks = extract_shot_blocks(raw)
    texts: dict[int, str] = {}
    for shot in range(1, NUM_SHOTS + 1):
        if shot not in blocks:
            raise SystemExit(f"Shot {shot} not found in {DEMO_SCRIPT}")
        voiceover = extract_voiceover(blocks[shot])
        if not voiceover:
            raise SystemExit(f"Shot {shot}: no voiceover text extracted")
        texts[shot] = voiceover
    return texts


def narration_txt_path(shot: int) -> Path:
    return BUILD_DIR / f"shot{shot}_narration.txt"


def mp3_path(shot: int) -> Path:
    return BUILD_DIR / f"shot{shot}.mp3"


def ensure_narration_file(shot: int, extracted_text: str) -> Path:
    """Write build/shotN_narration.txt only if it doesn't already exist,
    so hand-reconciled overrides (screen-over-script numbers) survive
    re-running extraction.
    """
    path = narration_txt_path(shot)
    if not path.exists():
        path.write_text(extracted_text + "\n")
    return path


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out)


def synthesize(shot: int, text: str, force: bool = False) -> Path:
    out = mp3_path(shot)
    txt_path = narration_txt_path(shot)
    if out.exists() and not force and out.stat().st_mtime >= txt_path.stat().st_mtime:
        print(f"shot {shot}: mp3 up to date, skipping synthesis")
        return out
    print(f"shot {shot}: synthesizing narration ({len(text)} chars)")
    subprocess.run(
        [
            "edge-tts",
            "--voice",
            VOICE,
            f"--rate={RATE}",
            "--text",
            text,
            "--write-media",
            str(out),
        ],
        check=True,
    )
    return out


def run_synthesis(shots: list[int], force: bool) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    extracted = load_shot_texts()

    timing = []
    for shot in range(1, NUM_SHOTS + 1):
        txt_path = ensure_narration_file(shot, extracted[shot])
        text = txt_path.read_text().strip()
        if shot in shots:
            synthesize(shot, text, force=force)
        out = mp3_path(shot)
        if not out.exists():
            raise SystemExit(f"shot {shot}: mp3 missing, run without --shot filter first")
        duration = ffprobe_duration(out)
        timing.append(
            {
                "shot": shot,
                "text": text,
                "mp3": str(out.relative_to(REPO_ROOT)),
                "duration_s": round(duration, 3),
            }
        )
        print(f"shot {shot}: duration {duration:.2f}s")

    timing_path = BUILD_DIR / "timing.json"
    timing_path.write_text(json.dumps(timing, indent=2) + "\n")
    print(f"wrote {timing_path}")


def wrap_caption_lines(text: str) -> list[str]:
    """Greedy word-wrap into lines of <= MAX_CHARS_PER_LINE chars."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= MAX_CHARS_PER_LINE:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def chunk_into_captions(text: str) -> list[str]:
    """Group wrapped lines into caption cards of <= MAX_LINES_PER_CAPTION
    lines each, returning each caption's display text (lines joined by
    newline).
    """
    lines = wrap_caption_lines(text)
    captions = []
    for i in range(0, len(lines), MAX_LINES_PER_CAPTION):
        captions.append("\n".join(lines[i : i + MAX_LINES_PER_CAPTION]))
    return captions


def srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms_total = round(seconds * 1000)
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def emit_srt(timeline_path: Path, out_path: Path) -> None:
    timeline = json.loads(timeline_path.read_text())
    timing_path = BUILD_DIR / "timing.json"
    timing = json.loads(timing_path.read_text())
    text_by_shot = {t["shot"]: t["text"] for t in timing}

    entries: list[tuple[float, float, str]] = []
    for shot_entry in timeline:
        shot = shot_entry["shot"]
        shot_start = float(shot_entry["start_s"])
        shot_end = float(shot_entry["end_s"])
        shot_duration = max(shot_end - shot_start, 0.01)
        text = text_by_shot.get(shot)
        if text is None:
            raise SystemExit(f"no narration text found for shot {shot}")

        captions = chunk_into_captions(text)
        total_chars = sum(len(c.replace("\n", " ")) for c in captions) or 1

        cursor = shot_start
        remaining = shot_duration
        for i, caption in enumerate(captions):
            chars = len(caption.replace("\n", " "))
            is_last = i == len(captions) - 1
            if is_last:
                dur = max(shot_end - cursor - CAPTION_GAP_S, MIN_CAPTION_S)
            else:
                dur = max(shot_duration * (chars / total_chars), MIN_CAPTION_S)
                dur = min(dur, remaining - MIN_CAPTION_S)
            dur = max(dur, MIN_CAPTION_S)
            start = cursor
            end = min(cursor + dur, shot_end - 0.01)
            if end <= start:
                end = start + MIN_CAPTION_S
            entries.append((start, end, caption))
            cursor = end + CAPTION_GAP_S
            remaining = shot_end - cursor

    # Enforce global monotonicity defensively (shots are already sequential
    # and non-overlapping by construction, but clamp just in case rounding
    # pushed a caption past the next shot's start).
    for i in range(1, len(entries)):
        prev_start, prev_end, prev_text = entries[i - 1]
        start, end, text = entries[i]
        if start <= prev_end:
            start = prev_end + 0.01
            end = max(end, start + MIN_CAPTION_S)
            entries[i] = (start, end, text)

    lines = []
    for idx, (start, end, caption) in enumerate(entries, start=1):
        lines.append(str(idx))
        lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
        lines.append(caption)
        lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path} ({len(entries)} captions)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shot", type=int, action="append", help="Regenerate only this shot's mp3 (repeatable)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Force re-synthesis even if mp3 is up to date"
    )
    parser.add_argument("--emit-srt", nargs=2, metavar=("TIMELINE_JSON", "OUT_SRT"))
    args = parser.parse_args()

    if args.emit_srt:
        timeline_path, out_path = args.emit_srt
        emit_srt(Path(timeline_path), Path(out_path))
        return

    shots = args.shot if args.shot else list(range(1, NUM_SHOTS + 1))
    run_synthesis(shots, force=args.force)


if __name__ == "__main__":
    main()
