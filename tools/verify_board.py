"""Run the compiled board off-screen and capture deterministic video/audio checkpoints."""
import argparse
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
from struct import pack

WIDTH, HEIGHT = 320 + 2 * int(os.environ.get("RC2_MARGIN", "54")), 240
BUTTONS = dict(up=1, down=2, left=4, right=8, fire=16, jump=32, special=64, start=128, coin=256)


def input_event(value):
    span, buttons = value.split(":", 1)
    ends = span.split("-")
    mask = 0
    for button in buttons.split("+"):
        mask |= BUTTONS[button]
    return int(ends[0]), int(ends[-1]), mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("chips", type=Path)
    parser.add_argument("--frames", default=650, type=int)
    parser.add_argument("--p1", action="append", type=input_event, default=[])
    parser.add_argument("--snap", type=int, action="append", default=[])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    b = ct.CDLL(str(args.library.resolve()))
    b.rc2_init.argtypes = [ct.c_char_p]
    b.rc2_frame.argtypes = [ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_int16), ct.c_uint, ct.c_uint]
    b.rc2_fps.restype = ct.c_double
    b.rc2_shutdown.restype = None
    if b.rc2_init(os.fsencode(args.chips.resolve())):
        raise SystemExit("board initialization failed")
    pixels = (ct.c_uint32 * (WIDTH * HEIGHT))()
    stereo = (ct.c_int16 * 4096)()
    selected = set(args.snap) | {0, args.frames - 1}
    audio_hash = hashlib.sha256()
    video_hash = hashlib.sha256()
    nonzero_audio_frames = total_samples = 0
    try:
        print(json.dumps({"fps": b.rc2_fps()}), flush=True)
        for frame in range(args.frames):
            pad = 0
            for start, end, mask in args.p1:
                if start <= frame <= end:
                    pad |= mask
            count = b.rc2_frame(pixels, stereo, pad, 0)
            if not 0 <= count <= 2048:
                raise RuntimeError(f"board failed at frame {frame}: {count}")
            pcm = ct.string_at(stereo, count * 4)
            total_samples += count
            nonzero_audio_frames += pcm.count(0) < len(pcm)
            audio_hash.update(pcm)
            digest = hashlib.blake2s(bytes(pixels)).digest()
            video_hash.update(digest)
            if frame in selected:
                count_colors = len(set(pixels))
                print(json.dumps({"frame": frame, "colors": count_colors,
                                  "video_hash": digest.hex()[:16], "samples": count}), flush=True)
                if args.out is not None:
                    args.out.mkdir(exist_ok=True, parents=True)
                    rgb = b"".join(pack(">I", px)[1:] for px in pixels)
                    (args.out / f"frame-{frame:05d}.ppm").write_bytes(
                        f"P6\n{WIDTH} {HEIGHT}\n255\n".encode() + rgb)
        print(json.dumps({"frames": args.frames, "stereo_samples": total_samples,
                          "nonzero_audio_frames": nonzero_audio_frames,
                          "audio_sha256": audio_hash.hexdigest(),
                          "video_sequence_sha256": video_hash.hexdigest()}), flush=True)
    finally:
        b.rc2_shutdown()


if __name__ == "__main__":
    main()
