#!/usr/bin/env bash
# Assemble the AMD Hackathon demo video from the recorded per-shot clips.
#
# Pipeline:
#   1. (assemble_pipeline.py clean)  fit each raw Playwright recording to
#      its narration duration (freeze-frame pad / trim, time-remap for the
#      live-prompt-burst shot 5), loudnorm the narration audio to -16 LUFS,
#      normalize to 30fps -> build/clean/sN.mp4
#   2. (assemble_pipeline.py concat) xfade (~0.4s) the 7 clean clips with
#      matching acrossfade audio -> build/assembled_noCaption.mp4, plus
#      build/assembled_timeline.json (real per-shot on-screen start/end
#      times in the concatenated video).
#   3. (narration.py --emit-srt)     re-wrap narration text into
#      <=2-line/<=42-char captions timed against that real timeline ->
#      launch/video/demo.srt.
#   4. Final ffmpeg pass: burn the captions (subtitles filter, small/
#      bottom/semi-transparent box), final encode
#      (libx264 -crf 18 -preset slow + aac -b:a 192k -ar 48000)
#      -> launch/video/demo.mp4.
#   5. Extract launch/video/thumbnail.png (1280x720) from the title card.
#
# Usage: scripts/video/assemble.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
BUILD_DIR="$HERE/build"
VIDEO_OUT_DIR="$REPO_ROOT/launch/video"

mkdir -p "$VIDEO_OUT_DIR"

echo "== step 1/5: fitting raw clips to narration duration =="
python3 "$HERE/assemble_pipeline.py" clean

echo "== step 2/5: crossfade concatenation =="
python3 "$HERE/assemble_pipeline.py" concat

echo "== step 3/5: emitting final demo.srt from the real assembled timeline =="
python3 "$HERE/narration.py" --emit-srt "$BUILD_DIR/assembled_timeline.json" "$VIDEO_OUT_DIR/demo.srt"

echo "== step 4/5: rendering + burning captions, final encode =="
# NOTE: this environment's ffmpeg build has neither libass nor libfreetype
# (confirmed via `ffmpeg -filters` — no subtitles/drawtext filter available),
# so captions are rendered as real HTML/CSS via Chromium (small, bottom,
# semi-transparent box) and composited with `overlay=enable=between(t,..)`
# instead of the subtitles filter.
node "$HERE/render_captions.mjs"
python3 "$HERE/assemble_pipeline.py" burn

FINAL_OUT="$VIDEO_OUT_DIR/demo.mp4"
echo "wrote $FINAL_OUT"

echo "== step 5/5: extracting thumbnail =="
ffmpeg -y -ss 3 -i "$FINAL_OUT" -frames:v 1 -update 1 -vf scale=1280:720 "$VIDEO_OUT_DIR/thumbnail.png"
echo "wrote $VIDEO_OUT_DIR/thumbnail.png"

echo "done."
