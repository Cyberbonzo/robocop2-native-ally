"""Translate the RoboCop 2 68000 program ROM to position-independent x86-64.

The board maps 1 MB of program ROM at 0x000000-0x0fffff, four 256 KB banks of
interleaved chip pairs. For every even ROM PC emit a native entry containing
its extension operands as an immediate, followed by a direct branch to
precompiled instruction semantics. All decoding happens here. Computed guest
jumps use PC-to-code arithmetic. The HuC6280 sound program is not translated;
it runs on the FBNeo HuC6280 core. The generated files derive from the owner's
ROM and stay private to their build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

ROM_SIZE = 0x100000
# FBNeo keeps 68000 memory byte-swapped on little-endian hosts; the chip it
# loads at offset +1 carries the high byte of each big-endian word.
BANKS = (  # (offset, high-byte CRC, low-byte CRC, chip size)
    (0x000000, 0xF4C96CC9, 0x11E53A7C, 0x20000),  # robo03.k1, robo07.k3
    (0x040000, 0xFA086A0D, 0x703B49D0, 0x20000),  # robo02.j1, robo06.j3
    (0x080000, 0xAB5356C0, 0xCE21BDA5, 0x20000),  # go-01-1.h1, go-05-1.h3
    (0x0C0000, 0xA93369EA, 0xEE2F6AD9, 0x20000),  # go-00.f1, go-04.f3
)
SLOT_SIZE = 16
VENEER_SIZE = 8


def read_program(path):
    required = {crc for _, even, odd, _ in BANKS for crc in (even, odd)}
    chips = {}
    for item in path.iterdir():
        if item.is_file() and item.stat().st_size == 0x20000:
            data = item.read_bytes()
            crc = zlib.crc32(data)
            if crc in required:
                chips[crc] = data
    image = bytearray(ROM_SIZE)
    for offset, even, odd, size in BANKS:
        for lane, crc in enumerate((even, odd)):
            if crc not in chips or len(chips[crc]) != size:
                raise ValueError(f"Missing or incorrect program ROM {crc:08x}")
            image[offset + lane:offset + 2 * size:2] = chips[crc]
    return bytes(image)


HELPERS = 0x110000      # unmapped 68000 space; only the translated code runs here
CODE_SIZE = 0x120000


class Asm:
    """Tiny 68000 emitter for the helpers: hex words plus branch labels."""

    def __init__(self, origin):
        self.origin, self.code, self.labels, self.fixups = origin, bytearray(), {}, []

    def here(self):
        return self.origin + len(self.code)

    def emit(self, words):
        self.code += bytes.fromhex(words.replace(" ", ""))

    def label(self, name):
        self.labels[name] = self.here()

    def branch(self, opcode, target):  # 16-bit displacement branches (bsr/bra/dbcc)
        self.fixups.append((len(self.code) + 2, target))
        self.emit(opcode + "0000")

    def link(self):
        for at, target in self.fixups:
            address = self.labels[target] if isinstance(target, str) else target
            displacement = address - (self.origin + at)
            assert -0x8000 <= displacement < 0x8000
            self.code[at:at + 2] = (displacement & 0xffff).to_bytes(2, "big")
        return bytes(self.code)


def l32(value):
    return f"{value:08x}"


def widen_screen_bounds(program, margin):
    """Game-specific changes for the 16:9 view.

    Column streaming: when the camera of a scrolling playfield passes 16
    pixels, the game copies one 16-pixel column of the map into the 1024-pixel
    ring of that playfield (0x010980 for playfield 3, 0x010ea2 for playfield
    4), right at the edge of its 320-pixel screen. Each call now also copies
    the next four columns, computed exactly as the game will when the camera
    gets there; the game's own counters are restored afterwards.
    """
    if margin == 0:
        return program
    code = bytearray(program) + bytearray(CODE_SIZE - len(program))
    asm = Asm(HELPERS)
    streams = (
        # entry, first instruction (moved to the trampoline), ring column,
        # column within the map segment, map pointer, segment-hold flag
        (0x010980, "3039001bbbe4", 0x1BBBE4, 0x1BBBDE, 0x1BBA6A, None),
        (0x010ea2, "3039001bbbe6", 0x1BBBE6, 0x1BBBE0, 0x1BBA6E, 0x1BBBD5),
    )
    patches = []
    for index, (entry, first, ring, column, pointer, hold) in enumerate(streams):
        trampoline, wrapper = f"t{index}", f"w{index}"
        asm.label(trampoline)
        asm.emit(first)                                   # original first instruction
        asm.emit("4ef9" + l32(entry + len(first) // 2))   # jmp back into the routine
        asm.label(wrapper)
        asm.branch("6100", trampoline)                    # bsr: the game's column
        asm.emit("48e7fffe")                              # movem.l d0-d7/a0-a6,-(a7)
        asm.emit("3f39" + l32(ring))                      # move.w ring,-(a7)
        asm.emit("3f39" + l32(column))                    # move.w column,-(a7)
        asm.emit("2f39" + l32(pointer))                   # move.l pointer,-(a7)
        asm.emit("7e03")                                  # moveq #3,d7: four more columns
        asm.label(f"next{index}")
        asm.emit("5279" + l32(column))                    # addq.w #1,column
        asm.emit("0c790010" + l32(column))                # cmpi.w #16,column
        asm.branch("6600", f"copy{index}")                # bne copy
        asm.emit("4279" + l32(column))                    # clr.w column
        if hold is not None:
            asm.emit("08390007" + l32(hold))              # btst #7,hold
            asm.branch("6600", f"copy{index}")            # bne copy (segment held)
        asm.emit("06b900000200" + l32(pointer))           # addi.l #$200,pointer
        asm.label(f"copy{index}")
        asm.branch("6100", trampoline)                    # bsr: copy the column
        asm.branch("51cf", f"next{index}")                # dbra d7,next
        asm.emit("23df" + l32(pointer))                   # move.l (a7)+,pointer
        asm.emit("33df" + l32(column))                    # move.w (a7)+,column
        asm.emit("33df" + l32(ring))                      # move.w (a7)+,ring
        asm.emit("4cdf7fff")                              # movem.l (a7)+,d0-d7/a0-a6
        asm.emit("4e75")                                  # rts
        patches.append((entry, first, wrapper))
    # Horizontal limits on screen X (word at 0x1bb604/0x1bb606 for players 1
    # and 2, (4,A5) minus the camera for the aiming cursor), compared with the
    # ROM words 288 and 32 through PC-relative reads. PC-relative data comes
    # from the board's memory, not from the translated code, so the compares
    # become immediates (same length). Comparisons are signed because the new
    # left limit is negative. For the players, the left limit is
    # 32 - min(margin, camera X) (word 0x1bba04): at the start of a stage, left
    # of the map origin, the player stops where the arcade did.
    def word(value):
        return f"{value & 0xffff:04x}"

    for index, (left, skip) in enumerate(((32, 0x01EB3C), (31, 0x01EBAA))):
        asm.label(f"left{index}")
        asm.emit("48e74000")                              # movem.l d1,-(a7)
        asm.emit("3239001bba04")                          # move.w $1bba04.l,d1 (camera X)
        asm.emit("0c41" + word(margin) + "6f04")          # cmpi.w #margin,d1; ble.s +4
        asm.emit("323c" + word(margin))                   # move.w #margin,d1
        asm.emit("4a41" "6c02" "7200")                    # tst.w d1; bge.s +2; moveq #0,d1
        asm.emit("4441" "0641" + word(left))              # neg.w d1; addi.w #left,d1
        asm.emit("b041")                                  # cmp.w d1,d0
        asm.emit("4cdf0002")                              # movem.l (a7)+,d1 (keeps flags)
        asm.emit("6f06")                                  # ble.s: at the limit, keep old X
        asm.emit("2ebc" + l32(skip))                      # inside: return past the clamp
        asm.emit("4e75")                                  # rts
    helpers = asm.link()
    code[HELPERS:HELPERS + len(helpers)] = helpers
    for entry, first, wrapper in patches:
        before = bytes.fromhex(first)
        if code[entry:entry + len(before)] != before:
            raise ValueError(f"Unexpected program bytes at {entry:06x}")
        code[entry:entry + 6] = bytes.fromhex("4ef9" + l32(asm.labels[wrapper]))
    right = word(288 + margin)
    limits = [
        (0x01EAEA, "b07ad850650e", "0c40" + right + "6d0e"),           # player 1: bcs -> blt
        (0x01EB0A, "b07ad832622c", "4eb9" + l32(asm.labels["left0"])),
        (0x01EB58, "b07ad7e2650e", "0c40" + right + "6d0e"),           # player 2
        (0x01EB78, "b07ad7c4642c", "4eb9" + l32(asm.labels["left1"])),
        (0x023322, "b07a90186508", "0c40" + right + "6d08"),           # cursor: bcs -> blt
        (0x023330, "b07a900c6206", "0c40" + word(32 - margin) + "6e06"),  # bhi -> bgt
    ]
    # Scroll requests compare the players' screen X unsigned with 160 and 112;
    # a negative X (now reachable in the left margin) read as "past 160" and
    # scrolled the camera forward. The thresholds stay; the branches go signed.
    for site in (0x01E968, 0x01E998, 0x023028, 0x023058):
        limits.append((site + 4, "650a", "6d0a"))           # bcs -> blt
        limits.append((site + 20, "6208", "6e08"))          # bhi -> bgt
    # Objects leave the playfield at fixed distances from the camera (world X
    # at (4,An) against camera X 0x1bba04 plus or minus a constant), compared
    # unsigned. Each distance grows by the margin; the compares become signed
    # because camera - distance can now be negative near a section start.
    m, m2 = margin, 2 * margin
    limits += [
        # shots: gone past camera+0x150 or at camera-0x10
        (0x01DA5E, "06400150", "0640" + word(0x150 + m)), (0x01DA66, "642a", "6c2a"),
        (0x01DA92, "04400160", "0440" + word(0x160 + m2)), (0x01DA9A, "64cc", "6ccc"),
        # actors in 0x1b9xxx: removed at camera-0x40
        (0x01F6B4, "04410040", "0441" + word(0x40 + m)), (0x01F6BC, "6400ff64", "6c00ff64"),
        # other objects with the same screen edges
        (0x026D7E, "04400010", "0440" + word(0x10 + m)), (0x026D86, "650a", "6d0a"),
        (0x02A9C4, "04400010", "0440" + word(0x10 + m)), (0x02A9CC, "640a", "6c0a"),
        (0x02AA42, "06400150", "0640" + word(0x150 + m)), (0x02AA4A, "640a", "6c0a"),
        (0x02AA6A, "04400010", "0440" + word(0x10 + m)), (0x02AA72, "6442", "6c42"),
        (0x02AA74, "06400160", "0640" + word(0x160 + m2)), (0x02AA7C, "6538", "6d38"),
        (0x020E40, "06400158", "0640" + word(0x158 + m)), (0x020E48, "6408", "6c08"),
    ]
    # Sprite lists (0x06073a and four copies) turn world X into the 9-bit
    # sprite X, camera + 320 - X, and hide anything outside [-32, 496] by
    # moving it to 496. With the wider raster the board wraps that X at 428:
    # [-84, -1] is the right margin, up to 423 the left one, and 496 itself
    # would be drawn in the right margin. Kept range [-84, 423]; hidden at 427,
    # left of the screen.
    for site in (0x06074C, 0x0607D8, 0x060864, 0x0608FA, 0x06098C):
        limits += [(site, "0c42ffe0", "0c42" + word(-84)),
                   (site + 6, "0c4201f0", "0c4201a7"),
                   (site + 12, "343c01f0", "343c01ab")]
    for address, before, after in limits:
        before, after = bytes.fromhex(before), bytes.fromhex(after)
        if len(before) != len(after) or code[address:address + len(before)] != before:
            raise ValueError(f"Unexpected program bytes at {address:06x}")
        code[address:address + len(after)] = after
    return bytes(code)


def decode_table(source):
    bodies = dict(re.findall(r"^static void (m68k_op_\w+)\(void\)\n\{\n(.*?)^\}", source, re.M | re.S))
    table = [("m68k_op_illegal", 0)] * 65536
    rows = re.findall(r"\{(m68k_op_\w+)\s*,\s*(0x\w+),\s*(0x\w+),\s*\{\s*(\d+),", source)
    if len(rows) < 1000 or len(bodies) < 1000:
        raise ValueError("Could not identify Musashi semantics and decode masks")
    for name, mask, match, cycles in rows:
        mask, match = int(mask, 16), int(match, 16)
        free = 0xffff ^ mask
        bits = free
        while True:
            table[match | bits] = (name, int(cycles))
            if bits == 0:
                break
            bits = (bits - 1) & free
    return bodies, table


def write_sites(image, ops, out):
    veneers = {opcode: i for i, opcode in enumerate(ops)}
    words = [w for (w,) in struct.iter_unpack(">H", image)]
    veneer_base = len(words) * SLOT_SIZE
    padded = words + [0] * 4
    native = bytearray(len(words) * SLOT_SIZE)
    for i, opcode in enumerate(words):
        at = i * SLOT_SIZE
        ext = sum(padded[i+1+k] << (16*k) for k in range(4))
        dest = veneer_base + veneers[opcode] * VENEER_SIZE
        # movabs $extension_words,%rdi ; jmp rel32 ; nop
        struct.pack_into("<2sQBiB", native, at, b"\x48\xbf", ext, 0xe9, dest - (at + 15), 0x90)
    blob = out / "sites_main.bin"
    blob.write_bytes(native)
    assembly = [".text", ".p2align 4", ".globl rc2_sites_main", ".hidden rc2_sites_main",
                "rc2_sites_main:", f'.incbin "{blob.resolve().as_posix()}"']
    for opcode in ops:
        assembly += [".byte 0xe9", f".long rc2_op_{opcode:04x} - . - 4", ".byte 0x90,0x90,0x90"]
    assembly.append('.section .note.GNU-stack,"",@progbits')
    (out / "sites.S").write_text("\n".join(assembly) + "\n")


def generate_header(cpu, out):
    source = (cpu / "m68kcpu.h").read_text()
    begin = source.index("INLINE uint m68ki_read_imm_16(void)\n{")
    end = source.index("\n}", source.index("INLINE uint m68ki_read_imm_32(void)\n{", begin)) + 2
    literal_reads = """
static uint64_t rc2_literals;
INLINE uint m68ki_read_imm_16(void)
{
    /* Each native site carries all four possible 68000 extension words. */
    unsigned int shift = (REG_PC - REG_PPC - 2u) * 8u;
    if (shift >= 64u) abort();
    REG_PC += 2;
    return (uint)(rc2_literals >> shift) & 65535u;
}
INLINE uint m68ki_read_imm_32(void)
{
    uint hi = m68ki_read_imm_16();
    return (hi << 16) | m68ki_read_imm_16();
}
"""
    header = (source[:begin] + "#ifdef RC2_COMPILED_KERNEL\n" + literal_reads + "\n#else\n"
              + source[begin:end] + "\n#endif\n" + source[end:])
    (out / "m68kcpu.h").write_text(header)


def generate_core(cpu, table, out, limit):
    core = (cpu / "m68kcpu.c").read_text()
    marker = '#include "m68kfpu.c"'
    extra = """
#include <stdio.h>
#include <stdlib.h>
extern const unsigned char rc2_sites_main[];
unsigned char m68ki_cycles[4][65536];
static const unsigned char rc2_cycles[65536] = {
#include "cycles.inc"
};
void m68ki_build_opcode_table(void)
{
    memcpy(m68ki_cycles[0], rc2_cycles, sizeof(rc2_cycles));
}
static void rc2_run_site(void)
{
    unsigned pc = REG_PC & 0xffffff;
    if (pc >= LIMIT || (pc & 1)) {
        fprintf(stderr,"RoboCop 2: no compiled code for PC %06x (previous PC %06x)\\n",pc,REG_PPC);
        abort();
    }
    ((void (*)(void))(rc2_sites_main + ((size_t)pc << 3)))();
}
"""
    old = "REG_IR = m68ki_read_imm_16();\n\t\t\tm68ki_instruction_jump_table[REG_IR]();\n\t\t\tUSE_CYCLES(CYC_INSTRUCTION[REG_IR]);"
    if core.count(old) != 2:
        raise ValueError("Unexpected 68000 execute loop")
    extra = extra.replace("LIMIT", hex(limit))
    core = core.replace(marker, marker + "\n" + extra).replace(old, "rc2_run_site();")
    (out / "m68kcpu.c").write_text(core)
    (out / "cycles.inc").write_text("\n".join(",".join(str(c) for _, c in table[i:i+64]) + "," for i in range(0, 65536, 64)))


def write_kernels(ops, bodies, table, out):
    preamble = """#include <stdint.h>
#include <stdlib.h>
#define RC2_COMPILED_KERNEL
#include "m68kcpu.h"
extern void m68040_fpu_op0(void);
extern void m68040_fpu_op1(void);
"""
    for batch in range(64):
        chunks = [preamble]
        for opcode in ops[batch::64]:
            name, cycles = table[opcode]
            body = re.sub(r"\breturn\s*;", "goto complete;", bodies[name])
            chunks += [f"#undef REG_IR\n#define REG_IR 0x{opcode:04x}u",
                       f"void rc2_op_{opcode:04x}(uint64_t operands)\n{{",
                       "    rc2_literals = operands;",
                       f"    m68ki_cpu.ir = 0x{opcode:04x}u;",
                       "    REG_PC += 2;", "    {", body, "    }",
                       f"complete: USE_CYCLES({cycles});", "}", ""]
        (out / f"kernel_{batch:02}.c").write_text("\n".join(chunks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("fbneo", "generated", "rom", "out"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--margin", type=int, default=48)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    original = read_program(args.rom)
    image = widen_screen_bounds(original, args.margin)
    ops = sorted({w for w, in struct.iter_unpack(">H", image)})
    bodies, table = decode_table((args.generated / "m68kops.c").read_text())
    cpu = args.fbneo / "src/cpu/m68k"
    generate_header(cpu, args.out)
    generate_core(cpu, table, args.out, len(image))
    write_kernels(ops, bodies, table, args.out)
    write_sites(image, ops, args.out)
    stats = {"cpu_sites": len(image) // 2,
             "reset_sp": int.from_bytes(image[0:4], "big"),
             "reset_pc": int.from_bytes(image[4:8], "big"),
             "decoded_operations": len(ops),
             "margin": args.margin,
             "program_sha256": hashlib.sha256(original).hexdigest(),
             "translated_sha256": hashlib.sha256(image).hexdigest()}
    (args.out / "translation.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
