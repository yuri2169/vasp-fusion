"""Turn the frames scripts/demo-flow.mjs kept (FRAMES=dir) into the recording of the demo:
an animated WebP (small, sharp) and a GIF (plays everywhere, including slides).

    FRAMES=/tmp/flow node scripts/demo-flow.mjs
    python scripts/recording.py /tmp/flow ../docs/screenshots/final-demo-flow

Each frame is shown for as long as the screen really showed it; a still screen is cut to
2.5 seconds at most. Needs Pillow (already a dependency of the backend, through reportlab).
"""
import json
import sys
from pathlib import Path

from PIL import Image

src, out = Path(sys.argv[1]), Path(sys.argv[2])
frames = json.loads((src / "frames.json").read_text())
WIDTH, LONGEST_MS, SHORTEST_MS = 960, 2500, 40

images, durations, size = [], [], None
for i, f in enumerate(frames):
    nxt = frames[i + 1]["t"] if i + 1 < len(frames) else f["t"] + LONGEST_MS / 1000
    ms = int(max(SHORTEST_MS, min(LONGEST_MS, (nxt - f["t"]) * 1000)))
    if images and ms <= SHORTEST_MS and durations[-1] < 80:      # fold bursts of near-identical frames
        durations[-1] += ms
        continue
    im = Image.open(src / f["file"]).convert("RGB")
    # The screencast's frames are not all one size: every frame is put on the first one's.
    size = size or (WIDTH, round(im.height * WIDTH / im.width))
    images.append(im.resize(size, Image.LANCZOS))
    durations.append(ms)

total = sum(durations) / 1000
images[0].save(out.with_suffix(".webp"), save_all=True, append_images=images[1:], duration=durations,
               loop=0, quality=80, method=4)
palette = [im.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for im in images]
palette[0].save(out.with_suffix(".gif"), save_all=True, append_images=palette[1:], duration=durations,
                loop=0, optimize=True, disposal=1)
for suffix in (".webp", ".gif"):
    p = out.with_suffix(suffix)
    print(f"{p.name}: {len(images)} frames, {total:.0f} s, {p.stat().st_size / 1e6:.1f} MB")
