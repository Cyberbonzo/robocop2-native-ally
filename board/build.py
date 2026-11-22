#!/usr/bin/env python3
"""Build the single-title RoboCop 2 board from the pinned FBNeo device sources."""
import argparse
import concurrent.futures
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("RC2_WORK", HERE.parent / ".work")).resolve()
FB = ROOT / "vendor/FBNeo"
SRC = FB / "src"
BUILD = ROOT / "build"
GEN = BUILD / "generated"
OBJ = BUILD / "board-obj"
MARGIN = int(os.environ.get("RC2_MARGIN", "54"))
SOURCE_FILES = """
burn/burn.cpp burn/burn_memory.cpp burn/tiles_generic.cpp burn/tilemap_generic.cpp
burn/burn_bitmap.cpp burn/debug_track.cpp burn/burn_sound.cpp burn/burn_sound_c.cpp burn/load.cpp burn/timer.cpp
burn/snd/burn_ym2151.cpp burn/snd/ym2151.c burn/snd/burn_ym2203.cpp burn/snd/fm.c burn/snd/ay8910.c burn/snd/msm6295.cpp
burn/drv/dataeast/deco16ic.cpp burn/drv/dataeast/deco146.cpp
cpu/m68000_intf.cpp cpu/h6280_intf.cpp cpu/h6280/h6280.cpp
cpu/z80_intf.cpp cpu/z80/z80.cpp cpu/z80/z80daisy.cpp cpu/z80/z80ctc.cpp
""".split()
DEFINES = ["-DLSB_FIRST", "-DEMU_M68K", "-DBUILD_HEADLESS", "-DBUILD_X64_EXE", "-DNO_VIZ",
           "-DHAVE_UNISTD_H", f"-DRC2_MARGIN_VALUE={MARGIN}"]


def update(path, data):
    if not path.exists() or path.read_text() != data:
        path.write_text(data)


def replace_once(code, before, after):
    assert code.count(before) == 1, before
    return code.replace(before, after)


def prepare():
    OBJ.mkdir(exist_ok=True, parents=True)
    GEN.mkdir(exist_ok=True, parents=True)
    update(GEN / "driverlist.h", """extern struct BurnDriver BurnDrvRobocop2ua;
static struct BurnDriver *const pDriver[] = { &BurnDrvRobocop2ua };
static const struct {const char *game_name; char *sourcefile;} sourcefile_table[] = {
    {"robocop2ua", (char*)"d_cninja.cpp"}, {"", (char*)""}};
""")
    code = (SRC / "burn/drv/dataeast/d_cninja.cpp").read_text()
    # 60 Hz logic: one board frame per display refresh of the Ally. The arcade
    # refresh was 57.79965 Hz; game and music run 3.8% faster. The HuC6280
    # clock that FBNeo scales by the refresh rate follows the same change.
    code = code.replace("57.79965", "60.0").replace("57.79", "60.0")
    code = code.replace('#include "timer.h"', '#include "timer.h"\n#include "rc2_board.h"', 1)
    # Wider raster for this title only. The DECO16 global X offset moves the
    # tilemap scroll origin left and the sprites right by the same amount.
    block = re.search(r"struct BurnDriver BurnDrvRobocop2ua = \{.*?\n\};", code, re.S).group(0)
    code = code.replace(block, replace_once(block, "320, 240, 4, 3", "RC2_WIDTH, 240, 16, 9"))
    init = re.search(r"static INT32 Robocop2Init\(\)\n\{.*?\n\}\n", code, re.S).group(0)
    code = code.replace(init, replace_once(init, "deco16_set_global_offsets(0, 8);",
                                           "deco16_set_global_offsets(-RC2_MARGIN, 8);"))
    # The adapter reads game state from main RAM (0x1b8000-0x1bbfff).
    code += "\nUINT8 *rc2_main_ram() { return Drv68KRAM; }\n"
    update(GEN / "rc2_devices.cpp", code)


def compile_object(source):
    cpp = source.suffix == ".cpp"
    flags = [os.environ.get("CXX", "g++") if cpp else os.environ.get("CC", "gcc"),
             "-std=gnu++17" if cpp else "-std=gnu17", "-O2", "-fPIC",
             "-fvisibility=hidden", "-ffunction-sections", "-fdata-sections",
             "-fno-strict-aliasing", "-Wno-write-strings", "-Wno-narrowing", *DEFINES]
    includes = [SRC/"burn", SRC/"burn/devices", SRC/"burn/snd", SRC/"cpu", SRC/"cpu/m68k", SRC/"cpu/z80",
                SRC/"cpu/h6280", SRC/"burner/headless", SRC/"burner", SRC/"intf", SRC/"burn/drv/dataeast", GEN,
                HERE.parent/"frontend"]
    out = OBJ / (source.name + ".o")
    if source.parent.name == "z80":  # z80.h expects z80_intf.h's calling-convention macro
        flags += ["-include", "burnint.h", "-include", "z80_intf.h"]
    subprocess.run(flags + [f"-I{x}" for x in includes] + ["-c", str(source), "-o", str(out)], check=True)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aot-object", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    prepare()
    sources = [SRC / s for s in SOURCE_FILES] + [GEN/"rc2_devices.cpp", HERE/"rc2_board.cpp", HERE/"standalone.cpp"]
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 6) as pool:
        objects = list(pool.map(compile_object, sources))
    subprocess.run(["g++", "-shared", "-Wl,--gc-sections,-z,defs", "-o", str(BUILD/"librc2_board.so"),
                    *map(str, objects + args.aot_object), "-lz", "-lm", "-pthread"], check=True)


if __name__ == "__main__":
    main()
