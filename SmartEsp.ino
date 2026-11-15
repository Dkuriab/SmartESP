// SmartESP — связка модулей. Здесь нет логики: только создание модулей,
// вызовы begin()/loop() и передача данных между модулями.
// Правила — CLAUDE.md, устройство — docs/superpowers/specs/.

#include "secrets.h"
#include "src/common/Types.h"
#include "src/audio_out/AudioOut.h"
#include "src/audio_in/AudioIn.h"
#include "src/voice_frontend/VoiceFrontend.h"

constexpr const char* FW_VERSION = "0.1.0";
constexpr size_t AUDIO_BLOCK = 512;

AudioOut audioOut;
AudioIn audioIn;
VoiceFrontend voiceFrontend;

int16_t micBlock[AUDIO_BLOCK];
int16_t refBlock[AUDIO_BLOCK];

void setup() {
  Serial.begin(115200);
  Serial.printf("SmartESP %s\n", FW_VERSION);

  audioOut.begin({.bclkPin = 7, .lrcPin = 6, .dinPin = 8});
  audioIn.begin({.sckPin = 5, .wsPin = 4, .sdPin = 9},
                [](int16_t* dst, size_t samples) { return audioOut.readReference(dst, samples); });
  voiceFrontend.begin({.vadSilenceMs = 500});
}

void loop() {
  size_t n;
  while ((n = audioIn.read(micBlock, refBlock, AUDIO_BLOCK)) > 0) {
    voiceFrontend.feed(micBlock, refBlock, n);
  }

  // Временно (до session): на слово — сигнал.
  VoiceEvent event;
  while (voiceFrontend.pollEvent(event)) {
    if (event.type == VoiceEventType::WakeWord) {
      Serial.println("wake");
      audioOut.playTone(Tone::Wake);
    }
  }
}
