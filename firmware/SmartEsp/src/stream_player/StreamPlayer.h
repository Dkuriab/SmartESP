#pragma once

// stream_player — поток звука с ядра (протокол 5): музыка, радио, звук Mac.
// Команда stream_start даёт ссылку; модуль сам качает PCM (16 кГц, 16 бит, моно) по HTTP/1.0
// в своей задаче FreeRTOS в буфер PSRAM и отдаёт его audio_out через read() (её задача
// смешивает музыку с голосом). Темп задаёт TCP: читаем ровно столько, сколько играет.
// Разговор (сценарий не в покое) — музыка глохнет сразу и возвращается через resumeDelayMs
// покоя: обычный поток стоит на паузе (буфер цел), живой (радио, звук Mac) читается дальше
// без звука. Отчёты stream_status — pollStatus(). Модуль не знает ни сценария, ни динамика.

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <atomic>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/stream_buffer.h"
#include "../common/Types.h"
#include "Ducker.h"

struct StreamPlayerConfig {
  const char* host;  // сервер ядра (тот же, что у server_link)
  uint16_t port;
  uint32_t bufferMs = 3000;      // ёмкость буфера (PSRAM)
  uint32_t prebufferMs = 500;    // сколько накопить перед звуком (и после опустошения)
  uint32_t resumeDelayMs = 1500; // музыка возвращается через столько покоя после разговора
  uint32_t reportMs = 1000;      // как часто слать playing
};

class StreamPlayer {
 public:
  // Буфер, очереди и задача скачивания. false — нет памяти.
  bool begin(const StreamPlayerConfig& config);

  // Новый поток (прежний останавливается без отчёта). Не блокирует. Из loop().
  void start(const StreamRequest& request);

  // Останавливает поток id (0 — любой); итог — stopped. Не блокирует. Из loop().
  void stop(uint32_t id);

  // Громкость музыки 0..1 (относительно общей громкости audio_out).
  void setVolume(float volume);

  // Сценарий не в покое — музыку глушить. Вызывать каждый loop().
  void setVoiceActive(bool active);

  // Есть ли связь с ядром; пропала — поток останавливается. Вызывать каждый loop().
  void setConnected(bool connected);

  // Вызывать из loop(): приглушение и отчёты playing.
  void loop(uint32_t nowMs);

  // Следующее событие stream_status для сервера.
  bool pollStatus(ClientEvent& event);

  // Звук музыки для audio_out (из её задачи): до samples отсчётов с громкостью и приглушением.
  // 0 — играть нечего. Безопасно вызывать до begin().
  size_t read(int16_t* dst, size_t samples);

 private:
  enum Phase : uint8_t { Idle, Connecting, Playing, Ended, Stopped, Failed };
  struct Command {
    bool start;
    StreamRequest request;  // для start; для стопа — только id
  };

  static void taskEntry(void* self);
  void run();
  void handle(const Command& command);
  void open(const StreamRequest& request);
  void pump();
  void close();
  void flush();
  void post(StreamState state, StreamError error);
  void finishDrained();

  StreamPlayerConfig config_{};
  StreamBufferHandle_t buffer_ = nullptr;
  QueueHandle_t commands_ = nullptr;  // loop() → задача
  QueueHandle_t events_ = nullptr;    // задача, звук, loop() → pollStatus
  std::atomic<bool> ready_{false};
  Ducker ducker_;

  std::atomic<uint8_t> phase_{Idle};
  std::atomic<uint32_t> id_{0};
  std::atomic<uint32_t> played_{0};       // байт, отданных audio_out (пишет задача звука)
  std::atomic<bool> eof_{false};          // ядро закрыло поток (пишет задача скачивания)
  std::atomic<bool> flushRequest_{false}; // задача скачивания просит задачу звука очистить буфер
  volatile bool live_ = false;
  volatile float volume_ = 1.0f;
  bool prebuffered_ = false;  // только задача звука

  // Только loop().
  bool voiceActive_ = false;
  bool connected_ = false;
  uint32_t reportedId_ = 0;
  uint32_t lastReportMs_ = 0;

  // Только задача скачивания.
  HTTPClient http_;
  WiFiClient client_;
  bool open_ = false;
  uint32_t lastDataMs_ = 0;
};
