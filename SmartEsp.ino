// SmartESP — связка модулей. Здесь нет логики: только создание модулей,
// вызовы begin()/loop() и передача данных между модулями.
// Правила — CLAUDE.md, устройство — docs/superpowers/specs/.

#include "secrets.h"
#include "src/common/Types.h"
#include "src/audio_out/AudioOut.h"
#include "src/audio_in/AudioIn.h"
#include "src/voice_frontend/VoiceFrontend.h"
#include "src/wifi_link/WifiLink.h"
#include "src/server_link/ServerLink.h"

constexpr const char* FW_VERSION = "0.1.0";
constexpr size_t AUDIO_BLOCK = 512;

AudioOut audioOut;
AudioIn audioIn;
VoiceFrontend voiceFrontend;
WifiLink wifiLink;
ServerLink serverLink;

int16_t micBlock[AUDIO_BLOCK];
int16_t refBlock[AUDIO_BLOCK];

void setup() {
  Serial.begin(115200);
  Serial.printf("SmartESP %s\n", FW_VERSION);

  audioOut.begin({.bclkPin = 7, .lrcPin = 6, .dinPin = 8});
  audioIn.begin({.sckPin = 5, .wsPin = 4, .sdPin = 9},
                [](int16_t* dst, size_t samples) { return audioOut.readReference(dst, samples); });
  voiceFrontend.begin({.vadSilenceMs = 500});
  wifiLink.begin(WIFI_SSID, WIFI_PASSWORD);
  serverLink.begin(SERVER_HOST, SERVER_PORT, "/device", FW_VERSION);
}

void loop() {
  wifiLink.loop();
  serverLink.loop();

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

  // Временно (до session): команды сервера — в Serial, громкость и тоны — на динамик.
  ServerCommand command;
  while (serverLink.pollCommand(command)) {
    Serial.printf("server command %d\n", (int)command.type);
    if (command.type == ServerCommandType::Volume) {
      audioOut.setVolume(command.volume);
    } else if (command.type == ServerCommandType::PlayTone) {
      audioOut.playTone(command.tone);
    }
  }
}
