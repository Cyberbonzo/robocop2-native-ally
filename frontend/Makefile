CXX ?= c++
BUILD ?= ../../build
SDL_CFLAGS := $(shell pkg-config --cflags sdl2)
SDL_LIBS := $(shell pkg-config --libs sdl2)
CXXFLAGS ?= -O2 -g

.PHONY: all
all: $(BUILD)/rc2

$(BUILD)/frontend.o: main.cpp progress.hpp rc2_board.h
	mkdir -p "$(BUILD)"
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Wpedantic $(SDL_CFLAGS) -c main.cpp -o "$@"

$(BUILD)/rc2: $(BUILD)/frontend.o $(BUILD)/librc2_board.so
	$(CXX) $(LDFLAGS) "$<" -L"$(BUILD)" -lrc2_board $(SDL_LIBS) -pthread -Wl,-rpath,'$$ORIGIN' -o "$@"
