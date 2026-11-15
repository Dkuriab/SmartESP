#pragma once

// server_link — связь с сервером по WebSocket (протокол — дизайн, раздел 7).
// Только транспорт и разбор сообщений: о сценарии ничего не знает.
// Звук ответа принимается только между reply_start и reply_end текущего хода.
//
// Сеть обслуживает своя задача FreeRTOS: подключение, отправка и приём могут
// зависать на секунды (недоступный хост, мёртвое соединение), и это не должно
// останавливать loop(). Публичные методы только кладут в очереди и забирают из них.

#include <Arduino.h>
#include <WebSocketsClient.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/stream_buffer.h"
#include "../common/Types.h"
#include "ReplyGate.h"

class ServerLink {
 public:
  // Запускает задачу связи с ws://host:port/path. Подключается, когда есть Wi-Fi.
  // Пустой host — связи не будет (isConnected() всегда false).
  bool begin(const char* host, uint16_t port, const char* path, const char* fwVersion);

  bool isConnected() const;

  // Ставит звук (PCM 16 кГц, моно) в очередь на отправку. Не блокирует.
  // false — нет соединения или очередь полна (звук отброшен).
  bool sendAudio(const int16_t* pcm, size_t samples);

  // Ставит событие в очередь на отправку (в общем порядке со звуком). Не блокирует.
  bool sendEvent(const ClientEvent& event);

  // Принятый звук ответа текущего хода. Не блокирует. Возвращает число отсчётов.
  size_t readAudio(int16_t* dst, size_t maxSamples);

  // Следующая разобранная команда сервера, если есть.
  bool pollCommand(ServerCommand& command);

  // Текущий ход: звук ответа на другие ходы отбрасывается. 0 — ни один.
  void setActiveTurn(uint32_t turn);

 private:
  static constexpr size_t OUT_SAMPLES = 512;  // кадр звука на отправку (32 мс)

  // Исходящее сообщение: звук или событие — в одной очереди, чтобы сохранить порядок.
  struct Outgoing {
    bool isAudio;
    ClientEvent event;
    uint16_t samples;
    int16_t pcm[OUT_SAMPLES];
  };

  static void taskEntry(void* self);
  void run();
  bool enqueue(const Outgoing& message);
  void sendQueued();
  void dropQueued();
  void onSocketEvent(WStype_t type, uint8_t* payload, size_t length);
  void onText(const char* json, size_t length);
  void onBinary(const uint8_t* data, size_t length);
  void storeAudio(const void* data, size_t bytes);
  bool gateOpen();

  WebSocketsClient socket_;
  const char* fwVersion_ = "";
  volatile bool connected_ = false;

  ReplyGate gate_;  // доступ — под gateLock_ (loop() и задача связи)
  portMUX_TYPE gateLock_ = portMUX_INITIALIZER_UNLOCKED;

  QueueHandle_t outgoing_ = nullptr;    // loop() → задача
  QueueHandle_t commands_ = nullptr;    // задача → loop()
  StreamBufferHandle_t audio_ = nullptr;  // задача → loop()
  Outgoing staging_{};                  // сборка сообщения в sendAudio/sendEvent (только loop())

  // Только в задаче связи.
  uint8_t carryByte_ = 0;  // нечётный байт, ждущий пару из следующего куска
  bool hasCarry_ = false;
  Outgoing sending_{};
  uint32_t lastLogMs_ = 0;
  uint32_t droppedOut_ = 0;  // меняется в loop()
  uint32_t lastOutLogMs_ = 0;
};
