#pragma once

// server_link — связь с сервером по WebSocket (протокол — дизайн, раздел 7).
// Только транспорт и разбор сообщений: о сценарии ничего не знает.
// Звук ответа принимается только между reply_start и reply_end текущего хода.

#include <Arduino.h>
#include <WebSocketsClient.h>
#include "freertos/FreeRTOS.h"
#include "freertos/stream_buffer.h"
#include "../common/Types.h"
#include "ReplyGate.h"

class ServerLink {
 public:
  // Запоминает адрес сервера ws://host:port/path. Подключение — в loop(),
  // когда есть Wi-Fi. Пустой host — не подключаться вовсе.
  bool begin(const char* host, uint16_t port, const char* path, const char* fwVersion);

  // Обслуживает соединение; переподключение раз в 2 с. Вызывать из loop().
  void loop();

  bool isConnected();

  // Отправляет звук (PCM 16 кГц, моно). false — нет соединения.
  bool sendAudio(const int16_t* pcm, size_t samples);

  // Отправляет событие JSON. false — нет соединения.
  bool sendEvent(const ClientEvent& event);

  // Принятый звук ответа текущего хода. Не блокирует. Возвращает число отсчётов.
  size_t readAudio(int16_t* dst, size_t maxSamples);

  // Следующая разобранная команда сервера, если есть.
  bool pollCommand(ServerCommand& command);

  // Текущий ход: звук ответа на другие ходы отбрасывается.
  void setActiveTurn(uint32_t turn);

 private:
  void onSocketEvent(WStype_t type, uint8_t* payload, size_t length);
  void onText(const char* json, size_t length);
  void onBinary(const uint8_t* data, size_t length);
  void storeAudio(const int16_t* samples, size_t count);

  WebSocketsClient socket_;
  ReplyGate gate_;
  const char* fwVersion_ = "";
  bool enabled_ = false;
  bool started_ = false;

  StreamBufferHandle_t audio_ = nullptr;
  uint8_t carryByte_ = 0;  // нечётный байт, ждущий пару из следующего куска
  bool hasCarry_ = false;
  uint32_t lastOverflowLogMs_ = 0;

  static constexpr size_t COMMAND_QUEUE = 16;
  ServerCommand commands_[COMMAND_QUEUE];
  size_t commandHead_ = 0;
  size_t commandCount_ = 0;
};
