#include "rc2_board.h"
#include "progress.hpp"
#include <SDL.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <csignal>
#include <memory>
#include <stdexcept>
#include <string>

namespace fs = std::filesystem;
constexpr const char *title = "RoboCop 2";
static volatile std::sig_atomic_t interrupted = 0;
static void stop(int) { interrupted = 1; }

struct Options {
    fs::path assets, saves, capture;
    unsigned frames = 0;
    bool headless = false;
};

static Options parse(int argc, char **argv) {
    Options opt;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i];
        auto value = [&]() {
            if (++i == argc) throw std::runtime_error("Missing value for " + key);
            return argv[i];
        };
        if (key == "--assets") opt.assets = value();
        else if (key == "--saves") opt.saves = value();
        else if (key == "--capture") opt.capture = value();
        else if (key == "--headless") opt.headless = true;
        else if (key == "--frames") {
            std::string argument = value();
            size_t used = 0;
            unsigned long n = std::stoul(argument, &used);
            if (used != argument.size() || !n || n > UINT32_MAX) throw std::runtime_error("Invalid frame limit");
            opt.frames = static_cast<unsigned>(n);
        } else throw std::runtime_error("Unknown option: " + key);
    }
    if (opt.assets.empty() || (opt.headless && !opt.frames))
        throw std::runtime_error("Usage: rc2 --assets DIR [--saves DIR] [--headless --frames N] [--capture BMP]");
    return opt;
}

static void sdl_error(const char *where) {
    throw std::runtime_error(std::string(where) + ": " + SDL_GetError());
}

struct Devices {
    SDL_Window *window = nullptr;
    SDL_Renderer *renderer = nullptr;
    SDL_Texture *texture = nullptr;
    SDL_AudioDeviceID audio = 0;
    std::array<SDL_GameController *, 2> pads{};

    ~Devices() {
        for (auto *pad : pads) if (pad) SDL_GameControllerClose(pad);
        if (audio) SDL_CloseAudioDevice(audio);
        if (upscaled) SDL_DestroyTexture(upscaled);
        if (texture) SDL_DestroyTexture(texture);
        if (renderer) SDL_DestroyRenderer(renderer);
        if (window) SDL_DestroyWindow(window);
    }

    void add_pad(int index) {
        if (!SDL_IsGameController(index)) return;
        auto id = SDL_JoystickGetDeviceInstanceID(index);
        for (auto *pad : pads)
            if (pad && SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(pad)) == id) return;
        for (auto &pad : pads) if (!pad) {
            pad = SDL_GameControllerOpen(index);
            if (pad) std::fprintf(stderr, "Gamepad: %s\n", SDL_GameControllerName(pad));
            break;
        }
    }

    void remove_pad(SDL_JoystickID id) {
        for (auto &pad : pads) if (pad && SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(pad)) == id) {
            SDL_GameControllerClose(pad);
            pad = nullptr;
        }
    }

    void open() {
        SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");
        window = SDL_CreateWindow(title, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 1280, 720,
                                  SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_ALLOW_HIGHDPI);
        if (!window) sdl_error("Window");
        SDL_ShowCursor(SDL_DISABLE);
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
        if (!renderer) renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
        if (!renderer) sdl_error("Renderer");
        texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGB888, SDL_TEXTUREACCESS_STREAMING,
                                    RC2_WIDTH, RC2_HEIGHT);
        if (!texture) sdl_error("Game surface");
        for (int i = 0; i < SDL_NumJoysticks(); ++i) add_pad(i);
        if (SDL_InitSubSystem(SDL_INIT_AUDIO) == 0) {
            SDL_AudioSpec want{};
            want.freq = RC2_AUDIO_RATE;
            want.format = AUDIO_S16SYS;
            want.channels = 2;
            want.samples = 512;
            audio = SDL_OpenAudioDevice(nullptr, 0, &want, nullptr, 0);
        }
        if (audio) SDL_PauseAudioDevice(audio, 0);
        else std::fprintf(stderr, "Audio unavailable: %s\n", SDL_GetError());
    }

    unsigned input(size_t player) const {
        unsigned result = 0;
        auto *p = pads[player];
        if (p) {
            auto b = [p](SDL_GameControllerButton button) { return SDL_GameControllerGetButton(p, button); };
            int x = SDL_GameControllerGetAxis(p, SDL_CONTROLLER_AXIS_LEFTX);
            int y = SDL_GameControllerGetAxis(p, SDL_CONTROLLER_AXIS_LEFTY);
            constexpr int deadzone = 10000;
            if (b(SDL_CONTROLLER_BUTTON_DPAD_UP) || y < -deadzone) result |= RC2_UP;
            if (b(SDL_CONTROLLER_BUTTON_DPAD_DOWN) || y > deadzone) result |= RC2_DOWN;
            if (b(SDL_CONTROLLER_BUTTON_DPAD_LEFT) || x < -deadzone) result |= RC2_LEFT;
            if (b(SDL_CONTROLLER_BUTTON_DPAD_RIGHT) || x > deadzone) result |= RC2_RIGHT;
            if (b(SDL_CONTROLLER_BUTTON_A)) result |= RC2_FIRE;
            if (b(SDL_CONTROLLER_BUTTON_B)) result |= RC2_JUMP;
            if (b(SDL_CONTROLLER_BUTTON_X)) result |= RC2_SPECIAL;
            if (b(SDL_CONTROLLER_BUTTON_BACK)) result |= RC2_COIN;
            if (b(SDL_CONTROLLER_BUTTON_START)) result |= RC2_START;
        }
        if (player == 0) {
            const Uint8 *key = SDL_GetKeyboardState(nullptr);
            if (key[SDL_SCANCODE_UP]) result |= RC2_UP;
            if (key[SDL_SCANCODE_DOWN]) result |= RC2_DOWN;
            if (key[SDL_SCANCODE_LEFT]) result |= RC2_LEFT;
            if (key[SDL_SCANCODE_RIGHT]) result |= RC2_RIGHT;
            if (key[SDL_SCANCODE_Z]) result |= RC2_FIRE;
            if (key[SDL_SCANCODE_X]) result |= RC2_JUMP;
            if (key[SDL_SCANCODE_C]) result |= RC2_SPECIAL;
            if (key[SDL_SCANCODE_5]) result |= RC2_COIN;
            if (key[SDL_SCANCODE_1] || key[SDL_SCANCODE_RETURN]) result |= RC2_START;
        }
        return result;
    }

    // Sharp bilinear: integer nearest-neighbour upscale into an intermediate
    // target, then one linear pass to the exact output size. Pixels stay crisp
    // without the uneven columns of a fractional nearest-neighbour scale.
    SDL_Texture *upscaled = nullptr;
    int upscale = 0;

    void ensure_upscaled(int factor) {
        if (factor == upscale && upscaled) return;
        if (upscaled) SDL_DestroyTexture(upscaled);
        upscaled = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGB888, SDL_TEXTUREACCESS_TARGET,
                                     RC2_WIDTH * factor, RC2_HEIGHT * factor);
        upscale = upscaled ? factor : 0;
        if (upscaled) {
            SDL_SetTextureScaleMode(texture, SDL_ScaleModeNearest);
            SDL_SetTextureScaleMode(upscaled, SDL_ScaleModeLinear);
        }
    }

    void present(const uint32_t *pixels, bool paused) {
        if (SDL_UpdateTexture(texture, nullptr, pixels, RC2_WIDTH * 4) < 0) sdl_error("Texture update");
        int width, height;
        if (SDL_GetRendererOutputSize(renderer, &width, &height) < 0) sdl_error("Display size");
        int w = std::min(width, height * 16 / 9);
        int h = std::min(height, width * 9 / 16);
        SDL_Rect dest{(width - w) / 2, (height - h) / 2, w, h};
        // The arcade showed 288 columns across a 4:3 picture. Keep that pixel
        // shape: with the 48-column margins the raster is exactly 16:9.
        const float raster_width = h * (4.0f / 3.0f) * RC2_WIDTH / RC2_ARCADE_WIDTH;
        const SDL_FRect raster{(width - raster_width) * 0.5f, float(dest.y),
                               raster_width, float(h)};
        SDL_Texture *source = texture;
        ensure_upscaled(std::max(1, (h + RC2_HEIGHT - 1) / RC2_HEIGHT));
        if (upscaled && SDL_SetRenderTarget(renderer, upscaled) == 0) {
            SDL_RenderCopy(renderer, texture, nullptr, nullptr);
            SDL_SetRenderTarget(renderer, nullptr);
            source = upscaled;
        }
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
        SDL_RenderClear(renderer);
        SDL_RenderSetClipRect(renderer, &dest);
        SDL_RenderCopyF(renderer, source, nullptr, &raster);
        SDL_RenderSetClipRect(renderer, nullptr);
        if (paused) {
            SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
            SDL_SetRenderDrawColor(renderer, 0, 0, 0, 155);
            SDL_RenderFillRect(renderer, &dest);
            int size = std::max(12, h / 12);
            SDL_Rect left{width / 2 - size / 3, height / 2 - size / 2, size / 4, size};
            SDL_Rect right{width / 2 + size / 12, left.y, left.w, size};
            SDL_SetRenderDrawColor(renderer, 255, 255, 255, 255);
            SDL_RenderFillRect(renderer, &left);
            SDL_RenderFillRect(renderer, &right);
        }
        SDL_RenderPresent(renderer);
    }
};

static int run(const Options &opt) {
    if (SDL_Init(opt.headless ? SDL_INIT_TIMER : (SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER | SDL_INIT_TIMER)) != 0)
        sdl_error("SDL");
    struct Session { ~Session() { SDL_Quit(); } } session;
    if (!opt.saves.empty()) {
        std::error_code error;
        fs::create_directories(opt.saves, error);
        if (error || rc2_set_save_dir(opt.saves.c_str()) != 0)
            std::fprintf(stderr, "EEPROM will not persist in %s\n", opt.saves.c_str());
    }
    if (rc2_init(opt.assets.c_str()) != 0) throw std::runtime_error("Board could not initialize the game");
    struct Board { ~Board() { rc2_shutdown(); } } board;
    double fps = rc2_fps();
    if (!std::isfinite(fps) || fps < 20 || fps > 240) throw std::runtime_error("Invalid refresh rate from board");
    std::fprintf(stderr, "RoboCop 2: %dx%d, %.5f Hz, %d Hz stereo\n",
                 RC2_WIDTH, RC2_HEIGHT, fps, RC2_AUDIO_RATE);
    Devices devices;
    if (!opt.headless) devices.open();
    Progress progress;
    progress.open(opt.saves);
    std::vector<uint32_t> pixels(RC2_WIDTH * RC2_HEIGHT);
    std::array<int16_t, RC2_MAX_AUDIO_FRAMES * 2> sound{};
    unsigned frame = 0;
    bool paused = false;
    double frequency = static_cast<double>(SDL_GetPerformanceFrequency());
    double duration = frequency / fps;
    double deadline = static_cast<double>(SDL_GetPerformanceCounter());
    unsigned save_period = static_cast<unsigned>(std::round(fps * 30));
    // RC2_STATS=1 logs presentation cadence every 10 seconds.
    const bool stats = std::getenv("RC2_STATS") != nullptr;
    double stats_start = 0, stats_last = 0, stats_worst = 0;
    unsigned stats_frames = 0, stats_late = 0;
    while (!interrupted && (!opt.frames || frame < opt.frames)) {
        SDL_Event event;
        while (!opt.headless && SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) interrupted = 1;
            if (event.type == SDL_CONTROLLERDEVICEADDED) devices.add_pad(event.cdevice.which);
            if (event.type == SDL_CONTROLLERDEVICEREMOVED) devices.remove_pad(event.cdevice.which);
            bool key = event.type == SDL_KEYDOWN && !event.key.repeat && event.key.keysym.sym == SDLK_ESCAPE;
            bool pad = event.type == SDL_CONTROLLERBUTTONDOWN && event.cbutton.button == SDL_CONTROLLER_BUTTON_Y;
            if (key || pad) {
                paused = !paused;
                if (paused) {
                    progress.save();
                    if (devices.audio) SDL_ClearQueuedAudio(devices.audio);
                }
            }
        }
        if (interrupted) break;
        if (!paused) {
            unsigned p1 = opt.headless ? 0 : devices.input(0);
            unsigned p2 = opt.headless ? 0 : devices.input(1);
            int count = rc2_frame(pixels.data(), sound.data(), p1, p2);
            if (count < 0 || count > RC2_MAX_AUDIO_FRAMES)
                throw std::runtime_error("Board failed while running frame " + std::to_string(frame));
            ++frame;
            if (devices.audio && count) {
                if (SDL_GetQueuedAudioSize(devices.audio) > RC2_AUDIO_RATE * 4 / 6)
                    SDL_ClearQueuedAudio(devices.audio);
                if (SDL_QueueAudio(devices.audio, sound.data(), count * 4) != 0) sdl_error("Queue audio");
            }
            if (frame % save_period == 0) progress.save();
        }
        if (!opt.headless) {
            devices.present(pixels.data(), paused);
            if (stats) {
                double t = static_cast<double>(SDL_GetPerformanceCounter()) * 1000.0 / frequency;
                if (stats_last > 0) {
                    double gap = t - stats_last;
                    stats_worst = std::max(stats_worst, gap);
                    stats_late += gap > 1000.0 / fps * 1.5;
                    ++stats_frames;
                } else stats_start = t;
                stats_last = t;
                if (t - stats_start >= 10000.0 && stats_frames) {
                    std::fprintf(stderr, "Cadence: %.2f fps, worst %.2f ms, %u late of %u\n",
                                 stats_frames * 1000.0 / (t - stats_start), stats_worst, stats_late, stats_frames);
                    stats_start = t; stats_frames = stats_late = 0; stats_worst = 0;
                }
            }
            deadline += duration;
            double now = static_cast<double>(SDL_GetPerformanceCounter());
            if (now - deadline > 3 * duration) deadline = now;
            while (now < deadline) {
                double remaining_ms = (deadline - now) * 1000 / frequency;
                SDL_Delay(static_cast<Uint32>(std::max(0.0, remaining_ms - 0.5)));
                now = static_cast<double>(SDL_GetPerformanceCounter());
            }
        }
    }
    if (!opt.capture.empty()) {
        auto *surface = SDL_CreateRGBSurfaceWithFormatFrom(pixels.data(), RC2_WIDTH, RC2_HEIGHT,
                                                           32, RC2_WIDTH * 4, SDL_PIXELFORMAT_RGB888);
        if (!surface) sdl_error("Capture");
        int status = SDL_SaveBMP(surface, opt.capture.c_str());
        SDL_FreeSurface(surface);
        if (status != 0) sdl_error("Writing capture");
    }
    if (frame) progress.save();
    return 0;
}

int main(int argc, char **argv) {
    std::signal(SIGINT, stop);
    std::signal(SIGTERM, stop);
    try { return run(parse(argc, argv)); }
    catch (const std::exception &error) {
        std::fprintf(stderr, "RoboCop 2: %s\n", error.what());
        return 1;
    }
}
