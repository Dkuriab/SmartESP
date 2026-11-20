// SmartESP — связка модулей. Здесь нет логики: только создание модулей,
// вызовы begin()/loop() и передача данных между модулями.
// Правила — CLAUDE.md, устройство — docs/superpowers/specs/2026-11-15-firmware-design.md.

#include "secrets.h"
#include "src/common/Types.h"
#include "src/audio_out/AudioOut.h"
#include "src/audio_in/AudioIn.h"
#include "src/voice_frontend/VoiceFrontend.h"
#include "src/wake_word/WakeWord.h"
#include "src/wake_word/ModelData.h"
#include "src/wifi_link/WifiLink.h"
#include "src/server_link/ServerLink.h"
#include "src/session/Session.h"

constexpr const char* FW_VERSION = "0.4.0";
constexpr size_t AUDIO_BLOCK = 512;  // 32 мс

AudioOut audioOut;
AudioIn audioIn;
VoiceFrontend voiceFrontend;
WakeWord wakeWord;
WifiLink wifiLink;
ServerLink serverLink;
Session session;

int16_t micBlock[AUDIO_BLOCK];
int16_t refBlock[AUDIO_BLOCK];
int16_t audioBlock[AUDIO_BLOCK];

void setup() {
  Serial.begin(115200);
  Serial.printf("SmartESP %s\n", FW_VERSION);

  audioOut.begin({.bclkPin = 7, .lrcPin = 6, .dinPin = 8});
  // Образец динамика берёт сам audio_in — сразу после чтения микрофона.
  audioIn.begin({.sckPin = 5, .wsPin = 4, .sdPin = 9},
                [](int16_t* dst, size_t samples) { return audioOut.readReference(dst, samples); });
  voiceFrontend.begin({.vadSilenceMs = 500});
  wakeWord.begin({.model = WAKE_MODEL_DATA,
                  .modelSize = WAKE_MODEL_SIZE,
                  .arenaSize = WAKE_MODEL_ARENA_SIZE,
                  .cutoff = WAKE_MODEL_CUTOFF,
                  .window = WAKE_MODEL_WINDOW});
  wifiLink.begin(WIFI_SSID, WIFI_PASSWORD);
  serverLink.begin(SERVER_HOST, SERVER_PORT, "/device", FW_VERSION);
  session.begin({});
}

void loop() {
  wifiLink.loop();  // server_link обслуживает сеть в своей задаче

  session.setConnected(serverLink.isConnected());
  // Сначала «играет ли», потом счётчик: так итоговое played полное (см. AudioOut.h).
  const bool playing = audioOut.isPlaying();
  session.setPlayedBytes(audioOut.playedBytes());
  session.setPlaybackActive(playing);
  session.loop(millis());

  size_t n;

  // Микрофон + образец → обработка звука.
  while ((n = audioIn.read(micBlock, refBlock, AUDIO_BLOCK)) > 0) {
    voiceFrontend.feed(micBlock, refBlock, n);
  }

  // Очищенный звук → поиск слова; слово (с громкостью) → сценарий.
  while ((n = voiceFrontend.readForWake(audioBlock, AUDIO_BLOCK)) > 0) {
    wakeWord.feed(audioBlock, n);
  }
  if (wakeWord.poll()) {
    session.onVoiceEvent(VoiceEvent{VoiceEventType::WakeWord, voiceFrontend.level()});
  }

  // Начало и конец речи → сценарий.
  VoiceEvent voiceEvent;
  while (voiceFrontend.pollEvent(voiceEvent)) {
    session.onVoiceEvent(voiceEvent);
  }

  // Очищенный звук вопроса → сервер.
  while ((n = voiceFrontend.readClean(audioBlock, AUDIO_BLOCK)) > 0) {
    serverLink.sendAudio(audioBlock, n);
  }

  // Звук ответа → динамик.
  while ((n = serverLink.readAudio(audioBlock, AUDIO_BLOCK)) > 0) {
    audioOut.write(audioBlock, n);
  }

  // Команды сервера → сценарий.
  ServerCommand command;
  while (serverLink.pollCommand(command)) {
    session.onServerCommand(command);
  }

  // Действия сценария → модули: каждое действие — один вызов одного модуля.
  Action action;
  while (session.pollAction(action)) {
    switch (action.type) {
      case ActionType::StartCapture: voiceFrontend.setCapture(true); break;
      case ActionType::StopCapture: voiceFrontend.setCapture(false); break;
      case ActionType::SendEvent: serverLink.sendEvent(action.event); break;
      case ActionType::StopPlayback: audioOut.stop(); break;
      case ActionType::PlayTone: audioOut.playTone(action.tone); break;
      case ActionType::SetVolume: audioOut.setVolume(action.volume); break;
      case ActionType::SetActiveTurn: serverLink.setActiveTurn(action.turn); break;
    }
  }
}
