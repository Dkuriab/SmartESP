// SmartESP — связка модулей. Здесь нет логики: только создание модулей,
// вызовы begin()/loop() и передача данных между модулями.
// Правила — CLAUDE.md, устройство — docs/superpowers/specs/.

#include "secrets.h"
#include "src/common/Types.h"
#include "src/audio_out/AudioOut.h"
#include "src/audio_in/AudioIn.h"

constexpr const char* FW_VERSION = "0.1.0";
constexpr size_t AUDIO_BLOCK = 512;

AudioOut audioOut;
AudioIn audioIn;

int16_t micBlock[AUDIO_BLOCK];
int16_t refBlock[AUDIO_BLOCK];

void setup() {
  Serial.begin(115200);
  Serial.printf("SmartESP %s\n", FW_VERSION);

  audioOut.begin({.bclkPin = 7, .lrcPin = 6, .dinPin = 8});
  audioIn.begin({.sckPin = 5, .wsPin = 4, .sdPin = 9, .shift = 14, .printLevel = true},
                [](int16_t* dst, size_t samples) { return audioOut.readReference(dst, samples); });

  audioOut.playTone(Tone::Wake);
}

void loop() {
  // Пока звук микрофона никому не нужен — просто вычитываем.
  while (audioIn.read(micBlock, refBlock, AUDIO_BLOCK) > 0) {
  }
}
