"""Extract the RoboCop 2 (US v0.05, FBNeo/MAME robocop2ua) chips from the user's arcade ZIPs.

Accepts the set under any name, merged or split with its parent, and outer
ZIPs that wrap it. Chips are matched by size and CRC.

"""
import argparse
import hashlib
import io
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile

CHIPS = {
    "robo03.k1": (0x20000, 0xF4C96CC9), "robo07.k3": (0x20000, 0x11E53A7C),
    "robo02.j1": (0x20000, 0xFA086A0D), "robo06.j3": (0x20000, 0x703B49D0),
    "go-01-1.h1": (0x20000, 0xAB5356C0), "go-05-1.h3": (0x20000, 0xCE21BDA5),
    "go-00.f1": (0x20000, 0xA93369EA), "go-04.f3": (0x20000, 0xEE2F6AD9),
    "gp-09.k13": (0x10000, 0x4A4E0F8D),
    "gp10-1.y6": (0x10000, 0xD25D719C), "gp11-1.z6": (0x10000, 0x030DED47),
    "mah-04.z4": (0x80000, 0x9B6CA18C), "mah-03.y4": (0x80000, 0x37894DDC),
    "mah-01.z1": (0x80000, 0x26E0DFFF), "mah-00.y1": (0x80000, 0x7BD69E41),
    "mah-02.a1": (0x80000, 0x328A247D),
    "mah-05.y9": (0x80000, 0x6773E613), "mah-08.y12": (0x80000, 0x88D310A5),
    "mah-06.z9": (0x80000, 0x27A8808A), "mah-09.z12": (0x80000, 0xA58C43A7),
    "mah-07.a9": (0x80000, 0x526F4190), "mah-10.a12": (0x80000, 0x14B770DA),
    "gp-08.j13": (0x20000, 0x365183B1), "mah-11.f13": (0x80000, 0x642BC692),
}
WANTED = {chip_id: name for name, chip_id in CHIPS.items()}

def collect(archive, found, depth=0):
    for info in archive.infolist():
        chip_id = (info.file_size, info.CRC)
        if chip_id in WANTED and WANTED[chip_id] not in found:
            found[WANTED[chip_id]] = archive.read(info)
        elif info.filename.lower().endswith(".zip") and depth == 0 and info.file_size < 64 << 20:
            with ZipFile(io.BytesIO(archive.read(info))) as inner:
                collect(inner, found, depth + 1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zips", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    found = {}
    for path in args.zips:
        with ZipFile(path) as archive:
            collect(archive, found)
    missing = sorted(set(CHIPS) - set(found))
    if missing:
        raise SystemExit("Missing RoboCop 2 (US v0.05) chips: " + ", ".join(missing))
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in found.items()}
    if out.exists():
        for name, digest in hashes.items():
            if hashlib.sha256((out / name).read_bytes()).hexdigest() != digest:
                raise SystemExit(f"Existing file differs: {out / name}")
    else:
        with tempfile.TemporaryDirectory(dir=out.parent) as scratch:
            stage = Path(scratch) / "chips"
            stage.mkdir()
            for name, data in found.items():
                (stage / name).write_bytes(data)
            stage.rename(out)
    print(json.dumps(dict(sorted(hashes.items())), indent=2))

if __name__ == "__main__":
    main()
