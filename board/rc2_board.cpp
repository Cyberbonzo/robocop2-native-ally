// Single-title Data East RoboCop 2 (DE-0362 board family) peripheral and input adapter.
#include "burnint.h"
#include "timer.h"
#include "deco16ic.h"
#pragma GCC visibility push(default)
#include "rc2_board.h"
#pragma GCC visibility pop
#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <unordered_map>
#include <vector>
#include <zlib.h>

extern BurnDriver BurnDrvRobocop2ua;
UINT8 *rc2_main_ram();
// Development aid: copy of 68000 main RAM (0x1b8000-0x1bbfff) in bus order.
extern "C" __attribute__((visibility("default"))) int rc2_debug_ram(uint8_t *out, size_t size) {
    UINT8 *ram = rc2_main_ram();
    if (!ram || size < 0x4000) return -1;
    for (size_t i = 0; i < 0x4000; ++i) out[i] = ram[i ^ 1];
    return 0;
}
// Development aid: DECO16 priority map of the last frame (512 bytes per line).
extern "C" __attribute__((visibility("default"))) int rc2_debug_prio(uint8_t *out, size_t size) {
    if (!deco16_prio_map || size < 512 * RC2_HEIGHT) return -1;
    memcpy(out, deco16_prio_map, 512 * RC2_HEIGHT);
    return 0;
}
// Development aid: playfield RAM (4 KB each, host byte order) of pf1-pf4.
extern "C" __attribute__((visibility("default"))) int rc2_debug_pf(int index, uint8_t *out, size_t size) {
    if (index < 0 || index > 3 || !deco16_pf_ram[index] || size < 0x1000) return -1;
    memcpy(out, deco16_pf_ram[index], 0x1000);
    return 0;
}
static std::unordered_map<uint32_t, std::vector<unsigned char>> chips;
static bool active;

// Position of the driver inputs in MetamrphInputList.
enum { PLAYER_INPUTS = 9, DIP_A = 20 };

static INT32 load_chip(UINT8 *dst, INT32 *written, INT32 index) {
    BurnRomInfo rom{};
    if (BurnDrvRobocop2ua.GetRomInfo(&rom, index)) return 1;
    auto chip = chips.find(rom.nCrc);
    if (chip == chips.end() || chip->second.size() != rom.nLen) {
        fprintf(stderr, "Missing chip %08x (index %d)\n", rom.nCrc, index);
        return 1;
    }
    memcpy(dst, chip->second.data(), rom.nLen);
    if (written) *written = rom.nLen;
    return 0;
}

static UINT32 xrgb(INT32 r, INT32 g, INT32 b, INT32) {
    return (r << 16) | (g << 8) | b;
}

int rc2_init(const char *directory) {
    if (active || !directory) return -1;
    chips.clear();
    try {
        for (const auto &f : std::filesystem::directory_iterator(directory)) {
            if (!f.is_regular_file() || f.file_size() > 1024*1024 || !f.file_size()) continue;
            std::ifstream stream(f.path(), std::ios::binary);
            std::vector<unsigned char> bytes(f.file_size());
            if (!stream.read(reinterpret_cast<char *>(bytes.data()), bytes.size())) return -1;
            const auto crc = crc32(0, bytes.data(), bytes.size());
            chips.emplace(crc, std::move(bytes));
        }
    } catch (const std::exception &e) {
        fprintf(stderr, "Reading chip directory: %s\n", e.what());
        return -1;
    }
    BurnLibInit();
    nBurnDrvActive = 0;
    nBurnBpp = 4;
    nBurnPitch = RC2_WIDTH * nBurnBpp;
    nBurnSoundRate = RC2_AUDIO_RATE;
    BurnHighCol = xrgb;
    BurnExtLoadRom = load_chip;
    BurnInitMemoryManager();
    BurnTimerPreInit();
    // Driver defaults of the three DIP switch banks.
    static const UINT8 dip_defaults[3] = {0xbf, 0x7f, 0xff};
    for (int bank = 0; bank < 3; ++bank) {
        BurnInputInfo input{};
        BurnDrvRobocop2ua.GetInputInfo(&input, DIP_A + bank);
        *input.pVal = dip_defaults[bank];
    }
    const auto result = BurnDrvRobocop2ua.Init();
    chips.clear();
    if (result != 0) {
        BurnExitMemoryManager();
        BurnLibExit();
        return -1;
    }
    active = true;
    return 0;
}

// Left of the start of the map section (camera X, word 0x1bba04) there is no
// map; in the columns that fall
// there, the colour covering most of them (the backdrop) becomes black, so
// characters walking in stay visible. When nearly a whole extra side is a
// single colour (a scene drawn for 320 columns only), that colour becomes
// black too. RAM is stored byte-swapped by FBNeo; aligned words read natively.
static void blacken_dominant(uint32_t *pixels, int x0, int x1) {
    std::unordered_map<uint32_t, int> count;
    for (int y = 0; y < RC2_HEIGHT; y += 2)
        for (int x = x0; x < x1; x += 2) ++count[pixels[y * RC2_WIDTH + x]];
    uint32_t dominant = 0;
    int best = 0;
    for (const auto &[colour, n] : count) if (n > best) { best = n; dominant = colour; }
    for (int y = 0; y < RC2_HEIGHT; ++y)
        for (int x = x0; x < x1; ++x)
            if (pixels[y * RC2_WIDTH + x] == dominant) pixels[y * RC2_WIDTH + x] = 0;
}

// Past the end of a section map the streamed main playfield holds empty tiles
// and only the layers behind it show (parallax backdrop, repeating fill) that
// the 320-column game never reveals there. The DECO16 priority map tells the
// layers apart: tilemaps write their priority value (higher = in front),
// sprites set bit 7, the HUD layer drawn last writes 0. The main layer is the
// front-most tilemap priority found in the 320 central columns. A margin
// column, scanning in from the outer edge, where the main layer covers under
// 10% of the lines is beyond the map (the empty tiles there still draw a few
// stray pixels): its tilemap pixels become black; sprites and the HUD stay. Skipped when central columns also lack the main layer, since the
// scene is then drawn that way.
static int main_layer = 0;

static bool lacks_main_layer(int x) {
    int main = 0;
    for (int y = 0; y < RC2_HEIGHT; ++y) main += deco16_prio_map[y * 512 + x] == main_layer;
    return main * 10 < RC2_HEIGHT;
}

static void hide_beyond_map(uint32_t *pixels) {
    main_layer = 0;
    for (int y = 0; y < RC2_HEIGHT; y += 2)
        for (int x = RC2_MARGIN; x < static_cast<int>(RC2_WIDTH - RC2_MARGIN); x += 2) {
            const UINT8 p = deco16_prio_map[y * 512 + x];
            if (!(p & 0x80)) main_layer = std::max<int>(main_layer, p);
        }
    if (main_layer < 2) return;
    for (int x = RC2_MARGIN; x < static_cast<int>(RC2_WIDTH - RC2_MARGIN); x += 2)
        if (lacks_main_layer(x)) return;
    auto clear = [&](int x) {
        for (int y = 0; y < RC2_HEIGHT; ++y) {
            const UINT8 p = deco16_prio_map[y * 512 + x];
            if (p && !(p & 0x80)) pixels[y * RC2_WIDTH + x] = 0;
        }
    };
    for (int x = RC2_WIDTH - 1; x >= static_cast<int>(RC2_WIDTH - RC2_MARGIN) && lacks_main_layer(x); --x) clear(x);
    for (int x = 0; x < static_cast<int>(RC2_MARGIN) && lacks_main_layer(x); ++x) clear(x);
}

static void hide_unused_margins(uint32_t *pixels) {
    if (!RC2_MARGIN) return;
    hide_beyond_map(pixels);
    // Each section of a stage starts at its own camera X; the smallest X seen
    // since the camera last jumped is where that section's map begins.
    static int origin = 0, previous = -10000;
    const int camera = *reinterpret_cast<const INT16 *>(rc2_main_ram() + 0x3a04);
    if (std::abs(camera - previous) > 64) origin = camera;
    origin = std::min(origin, camera);
    previous = camera;
    const int outside = std::clamp(RC2_MARGIN - (camera - origin), 0, static_cast<int>(RC2_MARGIN));
    if (outside) blacken_dominant(pixels, 0, outside);
    for (const int x0 : {0, static_cast<int>(RC2_WIDTH - RC2_MARGIN)}) {
        const uint32_t backdrop = pixels[(RC2_HEIGHT / 2) * RC2_WIDTH + x0 + RC2_MARGIN / 2];
        int same = 0;
        for (int y = 0; y < RC2_HEIGHT; ++y)
            for (int x = x0; x < x0 + RC2_MARGIN; ++x)
                same += pixels[y * RC2_WIDTH + x] == backdrop;
        if (!backdrop || same * 100 < RC2_HEIGHT * RC2_MARGIN * 97) continue;
        for (int y = 0; y < RC2_HEIGHT; ++y)
            for (int x = x0; x < x0 + RC2_MARGIN; ++x)
                if (pixels[y * RC2_WIDTH + x] == backdrop) pixels[y * RC2_WIDTH + x] = 0;
    }
}

int rc2_set_save_dir(const char *directory) {
    if (active || !directory) return -1;
    const size_t n = strlen(directory);
    if (!n || n + 2 + sizeof("robocop2ua.nv") > MAX_PATH) return -1;
    snprintf(szAppEEPROMPath, MAX_PATH, "%s%s", directory, directory[n - 1] == '/' ? "" : "/");
    return 0;
}

double rc2_fps() { return nBurnFPS / 100.0; }

int rc2_frame(uint32_t *pixels, int16_t *audio, unsigned p1, unsigned p2) {
    if (!active || !pixels || !audio) return -1;
    const unsigned players[2] = {p1, p2};
    // Input list order: coin, start, up, down, left, right, button 1-3.
    static const std::array<unsigned, PLAYER_INPUTS> masks = {
        RC2_COIN, RC2_START, RC2_UP, RC2_DOWN, RC2_LEFT, RC2_RIGHT,
        RC2_FIRE, RC2_JUMP, RC2_SPECIAL};
    for (int p = 0; p < 2; ++p) for (int i = 0; i < PLAYER_INPUTS; ++i) {
        BurnInputInfo input{};
        BurnDrvRobocop2ua.GetInputInfo(&input, p * PLAYER_INPUTS + i);
        *input.pVal = (players[p] & masks[i]) != 0;
    }
    pBurnDraw = reinterpret_cast<UINT8 *>(pixels);
    pBurnSoundOut = audio;
    memset(audio, 0, sizeof(*audio) * 2 * nBurnSoundLen);
    ++nCurrentFrame;
    if (BurnDrvRobocop2ua.Frame() != 0) return -1;
    hide_unused_margins(pixels);
    return nBurnSoundLen;
}

void rc2_shutdown() {
    if (!active) return;
    BurnDrvRobocop2ua.Exit();
    BurnExitMemoryManager();
    BurnLibExit();
    active = false;
}

#include "../frontend/board_progress.inc"
