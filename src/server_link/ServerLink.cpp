#include "ServerLink.h"

#include <WiFi.h>
#include "freertos/idf_additions.h"
#include "Protocol.h"

namespace {

constexpr uint32_t RECONNECT_MS = 2000;
constexpr size_t AUDIO_BUFFER_SAMPLES = 16000 * 2;  // 2 с
constexpr size_t JSON_BUFFER = 192;
constexpr uint32_t LOG_PERIOD_MS = 1000;

}  // namespace

bool ServerLink::begin(const char* host, uint16_t port, const char* path, const char* fwVersion) {
  fwVersion_ = fwVersion;
  audio_ = xStreamBufferCreateWithCaps(AUDIO_BUFFER_SAMPLES * sizeof(int16_t), 1, MALLOC_CAP_SPIRAM);
  if (!audio_) {
    Serial.println("server_link: нет памяти под буфер звука");
    return false;
  }
  if (!host || host[0] == '\0') {
    Serial.println("server_link: SERVER_HOST не задан в secrets.h — связи не будет");
    return true;
  }
  socket_.begin(host, port, path);
  socket_.setReconnectInterval(RECONNECT_MS);
  socket_.onEvent([this](WStype_t type, uint8_t* payload, size_t length) { onSocketEvent(type, payload, length); });
  enabled_ = true;
  return true;
}

void ServerLink::loop() {
  // Без Wi-Fi не дёргаем сокет: попытка подключения подвесила бы loop().
  if (!enabled_ || !WiFi.isConnected()) {
    return;
  }
  socket_.loop();
}

bool ServerLink::isConnected() {
  return enabled_ && socket_.isConnected();
}

bool ServerLink::sendAudio(const int16_t* pcm, size_t samples) {
  if (!isConnected()) {
    return false;
  }
  return socket_.sendBIN(reinterpret_cast<const uint8_t*>(pcm), samples * sizeof(int16_t));
}

bool ServerLink::sendEvent(const ClientEvent& event) {
  if (!isConnected()) {
    return false;
  }
  char json[JSON_BUFFER];
  const size_t length = encodeClientEvent(event, json, sizeof(json));
  return length > 0 && socket_.sendTXT(json, length);
}

size_t ServerLink::readAudio(int16_t* dst, size_t maxSamples) {
  return xStreamBufferReceive(audio_, dst, maxSamples * sizeof(int16_t), 0) / sizeof(int16_t);
}

bool ServerLink::pollCommand(ServerCommand& command) {
  if (commandCount_ == 0) {
    return false;
  }
  const size_t tail = (commandHead_ + COMMAND_QUEUE - commandCount_) % COMMAND_QUEUE;
  command = commands_[tail];
  commandCount_--;
  return true;
}

void ServerLink::setActiveTurn(uint32_t turn) {
  gate_.setActiveTurn(turn);
  if (!gate_.isOpen()) {
    hasCarry_ = false;
  }
}

void ServerLink::onSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED: {
      Serial.println("server_link: connected");
      char json[JSON_BUFFER];
      const size_t n = encodeHello(fwVersion_, json, sizeof(json));
      if (n > 0) {
        socket_.sendTXT(json, n);
      }
      break;
    }
    case WStype_DISCONNECTED:
      if (started_) {
        Serial.println("server_link: disconnected");
      }
      break;
    case WStype_TEXT:
      onText(reinterpret_cast<const char*>(payload), length);
      break;
    case WStype_BIN:
      onBinary(payload, length);
      break;
    default:
      break;  // фрагменты, ping/pong — не используем
  }
  started_ = true;
}

void ServerLink::onText(const char* json, size_t length) {
  ServerCommand command;
  if (!decodeServerCommand(json, length, command)) {
    log_w("server_link: непонятное сообщение: %.*s", (int)length, json);
    return;
  }
  gate_.onCommand(command);
  if (!gate_.isOpen()) {
    hasCarry_ = false;
  }
  if (commandCount_ == COMMAND_QUEUE) {
    log_w("server_link: очередь команд полна, команда отброшена");
    return;
  }
  commands_[commandHead_] = command;
  commandHead_ = (commandHead_ + 1) % COMMAND_QUEUE;
  commandCount_++;
}

void ServerLink::onBinary(const uint8_t* data, size_t length) {
  if (!gate_.isOpen() || length == 0) {
    return;
  }
  // Отсчёт может разрезаться между кусками: нечётный байт ждёт пару.
  if (hasCarry_) {
    const int16_t sample = static_cast<int16_t>(carryByte_ | (data[0] << 8));
    storeAudio(&sample, 1);
    data++;
    length--;
    hasCarry_ = false;
  }
  const size_t whole = length / sizeof(int16_t);
  storeAudio(reinterpret_cast<const int16_t*>(data), whole);
  if (length % sizeof(int16_t)) {
    carryByte_ = data[length - 1];
    hasCarry_ = true;
  }
}

void ServerLink::storeAudio(const int16_t* samples, size_t count) {
  const size_t bytes = count * sizeof(int16_t);
  const size_t sent = xStreamBufferSend(audio_, samples, bytes, 0);
  if (sent < bytes && millis() - lastOverflowLogMs_ >= LOG_PERIOD_MS) {
    lastOverflowLogMs_ = millis();
    log_w("server_link: буфер звука полон, отброшено %u байт", (unsigned)(bytes - sent));
  }
}
