#ifndef RC2_BOARD_H
#define RC2_BOARD_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The arcade raster is 320x240 on a 4:3 monitor (square pixels). 54 extra
 * columns on either side give a 428x240 raster that covers 16:9 with the
 * original pixel shape (the presentation crops under one pixel per side). */
#ifndef RC2_MARGIN_VALUE
#define RC2_MARGIN_VALUE 54
#endif
enum {
    RC2_ARCADE_WIDTH = 320,
    RC2_MARGIN = RC2_MARGIN_VALUE,
    RC2_WIDTH = RC2_ARCADE_WIDTH + 2 * RC2_MARGIN,
    RC2_HEIGHT = 240,
    RC2_AUDIO_RATE = 48000,
    RC2_MAX_AUDIO_FRAMES = 2048
};

enum {
    RC2_UP = 1, RC2_DOWN = 2, RC2_LEFT = 4, RC2_RIGHT = 8,
    RC2_FIRE = 16, RC2_JUMP = 32, RC2_SPECIAL = 64,
    RC2_START = 128, RC2_COIN = 256
};

/* The game-specific board consumes extracted, CRC-verified chips. */
int rc2_init(const char *directory);
/* Optional, before init: keep the arcade EEPROM (settings, high scores) here. */
int rc2_set_save_dir(const char *directory);
double rc2_fps(void);
/* XRGB8888, top to bottom, and interleaved 48 kHz signed stereo.
 * Return stereo frame count, or a negative value on a board error. */
int rc2_frame(uint32_t *pixels, int16_t *stereo, unsigned p1, unsigned p2);
void rc2_shutdown(void);

/* Zero size indicates that this build has no verified save-state implementation.
 * Save and load return zero on success. A rejected load leaves the board intact. */
size_t rc2_state_size(void);
int rc2_save_state(void *out, size_t size);
int rc2_load_state(const void *data, size_t size);

#ifdef __cplusplus
}
#endif
#endif
