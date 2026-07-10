#!/usr/bin/env python3
"""Numeric/filter-graph helper for assemble.sh.

ffmpeg's xfade/acrossfade offsets require float arithmetic and cumulative
bookkeeping that's painful in plain bash, so assemble.sh shells out to this
script for the two heavy steps:

  clean   - fit each shot's raw Playwright recording to its narration
            duration (freeze-frame pad / trim, or time-remap for the
            live-prompt-burst shot 5), loudnorm the narration audio, mux
            into build/clean/sN.mp4. Writes build/shot_plan.json.
  concat  - xfade + acrossfade all 7 clean clips into one video
            (build/assembled_noCaption.mp4) and write
            build/assembled_timeline.json (per-shot on-screen start/end
            times in the final concatenated timeline) for the SRT step.

Every numeric decision here is deterministic given build/timing.json and
the raw video durations, so re-running is safe/resumable (clean step
skips a shot if its output is already newer than its raw+audio inputs).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD_DIR = HERE / "build"
RAW_DIR = BUILD_DIR / "raw"
CLEAN_DIR = BUILD_DIR / "clean"

CROSSFADE_S = 0.4
PAD_S = 0.5
NUM_SHOTS = 7
SPEED_REMAP_SHOTS = {5}  # shot 5: live prompt burst, sped up to fit narration


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out)


def load_timing() -> dict[int, float]:
    timing = json.loads((BUILD_DIR / "timing.json").read_text())
    return {t["shot"]: t["duration_s"] for t in timing}


def build_plan() -> list[dict]:
    timing = load_timing()
    plan = []
    for shot in range(1, NUM_SHOTS + 1):
        raw_path = RAW_DIR / f"s{shot}.webm"
        mp3_path = BUILD_DIR / f"shot{shot}.mp3"
        if not raw_path.exists():
            raise SystemExit(f"missing raw video for shot {shot}: {raw_path}")
        if not mp3_path.exists():
            raise SystemExit(f"missing narration mp3 for shot {shot}: {mp3_path}")

        raw_dur = ffprobe_duration(raw_path)
        narr_dur = timing[shot]

        speed = None
        if shot in SPEED_REMAP_SHOTS:
            target = round(narr_dur + PAD_S, 3)
            if raw_dur > target * 1.05:
                speed = raw_dur / target
        else:
            target = round(max(raw_dur, narr_dur) + PAD_S, 3)

        plan.append(
            {
                "shot": shot,
                "raw_path": str(raw_path),
                "mp3_path": str(mp3_path),
                "raw_dur": raw_dur,
                "narr_dur": narr_dur,
                "target": target,
                "speed": speed,
            }
        )
    return plan


def clean_step() -> None:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    (BUILD_DIR / "shot_plan.json").write_text(json.dumps(plan, indent=2) + "\n")

    for entry in plan:
        shot = entry["shot"]
        out_path = CLEAN_DIR / f"s{shot}.mp4"
        raw_path = Path(entry["raw_path"])
        mp3_path = Path(entry["mp3_path"])
        if (
            out_path.exists()
            and out_path.stat().st_mtime >= raw_path.stat().st_mtime
            and out_path.stat().st_mtime >= mp3_path.stat().st_mtime
        ):
            print(f"shot {shot}: clean clip up to date, skipping")
            continue

        target = entry["target"]
        speed = entry["speed"]

        v_dur = entry["raw_dur"] / speed if speed else entry["raw_dur"]
        video_chain = "[0:v]"
        if speed:
            video_chain += f"setpts={1.0 / speed:.6f}*PTS,"
        video_chain += "scale=1920:1080,fps=30,format=yuv420p"
        if v_dur < target - 0.01:
            video_chain += f",tpad=stop_mode=clone:stop_duration={target - v_dur:.3f}"
        video_chain += "[v]"

        audio_chain = "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11"
        if entry["narr_dur"] < target - 0.01:
            audio_chain += f",apad=whole_dur={round(target * 48000)}"
        audio_chain += "[a]"

        filter_complex = f"{video_chain};{audio_chain}"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_path),
            "-i",
            str(mp3_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{target:.3f}",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(out_path),
        ]
        print(f"shot {shot}: target={target:.2f}s speed={speed} -> {out_path.name}")
        subprocess.run(cmd, check=True, capture_output=True)
    print("clean step complete")


def concat_step() -> None:
    plan = json.loads((BUILD_DIR / "shot_plan.json").read_text())
    inputs = []
    for entry in plan:
        shot = entry["shot"]
        inputs += ["-i", str(CLEAN_DIR / f"s{shot}.mp4")]

    n = len(plan)
    targets = [e["target"] for e in plan]
    xd = CROSSFADE_S

    video_labels = [f"{i}:v" for i in range(n)]
    audio_labels = [f"{i}:a" for i in range(n)]

    filter_parts = []
    cur_v = f"[{video_labels[0]}]"
    cur_a = f"[{audio_labels[0]}]"
    cumulative = targets[0]
    starts = [0.0]
    for i in range(1, n):
        offset = cumulative - xd
        next_v = f"[vx{i}]"
        next_a = f"[ax{i}]"
        filter_parts.append(
            f"{cur_v}[{video_labels[i]}]xfade=transition=fade:duration={xd}:offset={offset:.3f}{next_v}"
        )
        filter_parts.append(f"{cur_a}[{audio_labels[i]}]acrossfade=d={xd}{next_a}")
        starts.append(offset)
        cumulative = cumulative + targets[i] - xd
        cur_v = next_v
        cur_a = next_a

    ends = starts[1:] + [cumulative]
    filter_complex = ";".join(filter_parts)

    out_path = BUILD_DIR / "assembled_noCaption.mp4"
    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex",
            filter_complex,
            "-map",
            cur_v,
            "-map",
            cur_a,
            "-c:v",
            "libx264",
            "-crf",
            "19",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(out_path),
        ]
    )
    print(f"concatenating {n} shots -> {out_path.name} (predicted duration {cumulative:.2f}s)")
    subprocess.run(cmd, check=True, capture_output=True)

    probed_dur = ffprobe_duration(out_path)
    print(f"probed assembled duration: {probed_dur:.2f}s")

    timeline = []
    for i, entry in enumerate(plan):
        timeline.append(
            {"shot": entry["shot"], "start_s": round(starts[i], 3), "end_s": round(ends[i], 3)}
        )
    # Clamp the last shot's end to the real probed duration so the SRT
    # never claims a caption extends past the actual video.
    timeline[-1]["end_s"] = round(min(timeline[-1]["end_s"], probed_dur), 3)
    (BUILD_DIR / "assembled_timeline.json").write_text(json.dumps(timeline, indent=2) + "\n")
    print("wrote build/assembled_timeline.json")


def burn_step() -> None:
    """Composite the Playwright-rendered caption PNGs (build/captions/) onto
    build/assembled_noCaption.mp4 with per-caption overlay(enable=between(t,
    start,end)) windows, then do the final delivery encode.

    This stands in for ffmpeg's subtitles/drawtext filters, which need
    libass/libfreetype — not present in this environment's ffmpeg build
    (confirmed via `ffmpeg -filters`). Rendering captions as real HTML/CSS
    via Chromium (scripts/video/render_captions.mjs) gets the same subtle
    small/bottom/semi-transparent-box look with zero extra system deps.
    """
    manifest_path = BUILD_DIR / "captions_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assembled = BUILD_DIR / "assembled_noCaption.mp4"

    repo_root = HERE.parent.parent
    out_path = repo_root / "launch" / "video" / "demo.mp4"

    inputs = ["-i", str(assembled)]
    for cap in manifest:
        inputs += ["-i", str(HERE / cap["file"])]

    filter_parts = []
    cur = "[0:v]"
    for i, cap in enumerate(manifest, start=1):
        nxt = f"[v{i}]" if i < len(manifest) else "[vout]"
        enable = f"between(t\\,{cap['start_s']:.3f}\\,{cap['end_s']:.3f})"
        filter_parts.append(f"{cur}[{i}:v]overlay=enable='{enable}'{nxt}")
        cur = nxt
    filter_complex = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "0:a",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "slow",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(out_path),
        ]
    )
    print(f"burning {len(manifest)} captions onto assembled video -> {out_path}")
    subprocess.run(cmd, check=True)
    print(f"wrote {out_path}")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"clean", "concat", "burn"}:
        raise SystemExit("usage: assemble_pipeline.py {clean|concat|burn}")
    if sys.argv[1] == "clean":
        clean_step()
    elif sys.argv[1] == "concat":
        concat_step()
    else:
        burn_step()


if __name__ == "__main__":
    main()
