// SmartESP — связка модулей. Здесь нет логики: только создание модулей,
// вызовы begin()/loop() и передача данных между модулями.
// Правила — CLAUDE.md, устройство — docs/superpowers/specs/.

#include "secrets.h"
#include "src/common/Types.h"
#include "src/audio_out/AudioOut.h"

constexpr const char* FW_VERSION = "0.1.0";

AudioOut audioOut;

void setup() {
  Serial.begin(115200);
  Serial.printf("SmartESP %s\n", FW_VERSION);

  audioOut.begin({.bclkPin = 7, .lrcPin = 6, .dinPin = 8});
  audioOut.playTone(Tone::Wake);
}

void loop() {}
