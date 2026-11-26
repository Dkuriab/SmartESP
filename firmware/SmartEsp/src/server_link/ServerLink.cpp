#include "ServerLink.h"

#include <WiFi.h>
#include "freertos/idf_additions.h"
#include "Protocol.h"

namespace {

constexpr uint32_t RECONNECT_MS = 2000;
// Пинг раз в 5 с; нет ответа 3 с два раза подряд — соединение мёртвое (сервер уснул, пропал).
constexpr uint32_t PING_INTERVAL_MS = 5000;
constexpr uint32_t PONG_TIMEOUT_MS = 3000;
constexpr uint8_t MISSED_PONGS = 2;

constexpr UBaseType_t OUTGOING_LENGTH = 64;  // ~2 с звука
constexpr UBaseType_t COMMAND_LENGTH = 16;
constexpr size_t AUDIO_BUFFER_SAMPLES = 16000 * 2;  // 2 с принятого звука
constexpr size_t SEND_PER_PASS = 8;  // сообщений за проход, чтобы приём не простаивал
constexpr size_t JSON_BUFFER = 192;
constexpr size_t HELLO_BUFFER = 768;  // hello с хэшами пяти звуков, caps и stream_rates
static_assert(TONE_COUNT == 5, "soundHashes_ в ServerLink.h — по строке на сигнал");
constexpr uint32_t LOG_PERIOD_MS = 1000;

}  // namespace

bool ServerLink::begin(const char* fwVersion) {
  fwVersion_ = fwVersion;
  outgoing_ = xQueueCreateWithCaps(OUTGOING_LENGTH, sizeof(Outgoing), MALLOC_CAP_SPIRAM);
  commands_ = xQueueCreate(COMMAND_LENGTH, sizeof(ServerCommand));
  audio_ = xStreamBufferCreateWithCaps(AUDIO_BUFFER_SAMPLES * sizeof(int16_t), 1, MALLOC_CAP_SPIRAM);
  if (!outgoing_ || !commands_ || !audio_) {
    Serial.println("server_link: нет памяти под очереди");
    return false;
  }
  socket_.onEvent([this](WStype_t type, uint8_t* payload, size_t length) { onSocketEvent(type, payload, length); });
  return xTaskCreatePinnedToCore(taskEntry, "server_link", 8192, this, 4, nullptr, 1) == pdPASS;
}

void ServerLink::setServer(const char* host, uint16_t port, const char* path) {
  if (!host || !path) {
    return;
  }
  taskENTER_CRITICAL(&serverLock_);
  if (strcmp(serverHost_, host) != 0 || serverPort_ != port || strcmp(serverPath_, path) != 0) {
    strncpy(serverHost_, host, sizeof(serverHost_) - 1);
    strncpy(serverPath_, path, sizeof(serverPath_) - 1);
    serverPort_ = port;
    serverChanged_ = true;
  }
  taskEXIT_CRITICAL(&serverLock_);
}

// Задача связи: новый адрес ядра → socket_ на него. false — адреса ещё нет.
bool ServerLink::applyServer() {
  char host[sizeof(serverHost_)];
  char path[sizeof(serverPath_)];
  uint16_t port;
  taskENTER_CRITICAL(&serverLock_);
  const bool changed = serverChanged_;
  serverChanged_ = false;
  memcpy(host, serverHost_, sizeof(host));
  memcpy(path, serverPath_, sizeof(path));
  port = serverPort_;
  taskEXIT_CRITICAL(&serverLock_);
  if (!changed) {
    return hasServer_;
  }
  if (hasServer_) {
    socket_.disconnect();  // прежнее ядро; событие DISCONNECTED сбросит connected_
    connected_ = false;
  }
  Serial.printf("server_link: ядро ws://%s:%u%s\n", host, (unsigned)port, path);
  socket_.begin(host, port, path);  // строки копируются внутрь библиотеки
  socket_.setReconnectInterval(RECONNECT_MS);
  socket_.enableHeartbeat(PING_INTERVAL_MS, PONG_TIMEOUT_MS, MISSED_PONGS);
  hasServer_ = true;
  return true;
}

void ServerLink::setSoundHash(Tone tone, const char* sha256) {
  const size_t index = static_cast<size_t>(tone);
  if (index >= TONE_COUNT) {
    return;
  }
  taskENTER_CRITICAL(&soundLock_);
  strncpy(soundHashes_[index], sha256 ? sha256 : "", sizeof(soundHashes_[index]) - 1);
  soundHashes_[index][sizeof(soundHashes_[index]) - 1] = '\0';
  taskEXIT_CRITICAL(&soundLock_);
}

bool ServerLink::isConnected() const {
  return connected_;
}

bool ServerLink::sendAudio(const int16_t* pcm, size_t samples) {
  if (!connected_) {
    return false;
  }
  bool ok = true;
  while (samples > 0) {
    const size_t n = samples < OUT_SAMPLES ? samples : OUT_SAMPLES;
    staging_.isAudio = true;
    staging_.samples = n;
    memcpy(staging_.pcm, pcm, n * sizeof(int16_t));
    ok = enqueue(staging_) && ok;
    pcm += n;
    samples -= n;
  }
  return ok;
}

bool ServerLink::sendEvent(const ClientEvent& event) {
  if (!connected_) {
    return false;
  }
  staging_.isAudio = false;
  staging_.event = event;
  staging_.samples = 0;
  return enqueue(staging_);
}

bool ServerLink::enqueue(const Outgoing& message) {
  if (xQueueSend(outgoing_, &message, 0) == pdTRUE) {
    return true;
  }
  droppedOut_++;
  if (millis() - lastOutLogMs_ >= LOG_PERIOD_MS) {
    lastOutLogMs_ = millis();
    Serial.printf("server_link: сеть не успевает, отброшено сообщений: %u\n", (unsigned)droppedOut_);
    droppedOut_ = 0;
  }
  return false;
}

size_t ServerLink::readAudio(int16_t* dst, size_t maxSamples) {
  return xStreamBufferReceive(audio_, dst, maxSamples * sizeof(int16_t), 0) / sizeof(int16_t);
}

bool ServerLink::pollCommand(ServerCommand& command) {
  return xQueueReceive(commands_, &command, 0) == pdTRUE;
}

void ServerLink::setActiveTurn(uint32_t turn) {
  taskENTER_CRITICAL(&gateLock_);
  gate_.setActiveTurn(turn);
  taskEXIT_CRITICAL(&gateLock_);
}

bool ServerLink::gateOpen() {
  taskENTER_CRITICAL(&gateLock_);
  const bool open = gate_.isOpen();
  taskEXIT_CRITICAL(&gateLock_);
  return open;
}

void ServerLink::taskEntry(void* self) {
  static_cast<ServerLink*>(self)->run();
}

void ServerLink::run() {
  for (;;) {
    if (!WiFi.isConnected() || !applyServer()) {
      // Без Wi-Fi библиотека сама не заметит обрыв — закрываем соединение явно.
      // Адреса ядра ещё не было — socket_ не настроен, закрывать нечего.
      if (hasServer_ && (connected_ || socket_.isConnected())) {
        socket_.disconnect();
        connected_ = false;
        Serial.println("server_link: disconnected (нет Wi-Fi)");
      }
      dropQueued();
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    socket_.loop();  // может зависнуть на подключении — но только эта задача
    if (connected_) {
      sendQueued();
    } else {
      dropQueued();  // устаревшее не отправляем после переподключения
    }
    vTaskDelay(1);
  }
}

void ServerLink::sendQueued() {
  for (size_t i = 0; i < SEND_PER_PASS && xQueueReceive(outgoing_, &sending_, 0) == pdTRUE; i++) {
    if (sending_.isAudio) {
      socket_.sendBIN(reinterpret_cast<const uint8_t*>(sending_.pcm), sending_.samples * sizeof(int16_t));
    } else {
      char json[JSON_BUFFER];
      const size_t length = encodeClientEvent(sending_.event, json, sizeof(json));
      if (length > 0) {
        socket_.sendTXT(json, length);
      }
    }
  }
}

void ServerLink::dropQueued() {
  while (xQueueReceive(outgoing_, &sending_, 0) == pdTRUE) {
  }
}

void ServerLink::onSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED: {
      Serial.println("server_link: connected");
      connected_ = true;
      char sounds[TONE_COUNT][65];
      taskENTER_CRITICAL(&soundLock_);
      memcpy(sounds, soundHashes_, sizeof(sounds));
      taskEXIT_CRITICAL(&soundLock_);
      char json[HELLO_BUFFER];
      const size_t n = encodeHello(fwVersion_, WiFi.macAddress().c_str(), json, sizeof(json), sounds);
      if (n > 0) {
        socket_.sendTXT(json, n);
      }
      break;
    }
    case WStype_DISCONNECTED:
      if (connected_) {
        Serial.println("server_link: disconnected");
      }
      connected_ = false;
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
}

void ServerLink::onText(const char* json, size_t length) {
  ServerCommand command;
  if (!decodeServerCommand(json, length, command)) {
    Serial.printf("server_link: непонятное сообщение: %.*s\n", (int)length, json);
    return;
  }
  taskENTER_CRITICAL(&gateLock_);
  gate_.onCommand(command);
  taskEXIT_CRITICAL(&gateLock_);
  if (xQueueSend(commands_, &command, 0) != pdTRUE) {
    Serial.println("server_link: очередь команд полна, команда отброшена");
  }
}

void ServerLink::onBinary(const uint8_t* data, size_t length) {
  if (!gateOpen()) {
    hasCarry_ = false;  // шлюз закрыт — недоделанный отсчёт больше не нужен
    return;
  }
  if (length == 0) {
    return;
  }
  // Отсчёт может разрезаться между кусками: нечётный байт ждёт пару.
  if (hasCarry_) {
    const int16_t sample = static_cast<int16_t>(carryByte_ | (data[0] << 8));
    storeAudio(&sample, sizeof(sample));
    data++;
    length--;
    hasCarry_ = false;
  }
  const size_t whole = length & ~static_cast<size_t>(1);
  storeAudio(data, whole);
  if (length != whole) {
    carryByte_ = data[length - 1];
    hasCarry_ = true;
  }
}

void ServerLink::storeAudio(const void* data, size_t bytes) {
  const size_t sent = xStreamBufferSend(audio_, data, bytes, 0);
  if (sent < bytes && millis() - lastLogMs_ >= LOG_PERIOD_MS) {
    lastLogMs_ = millis();
    Serial.printf("server_link: буфер звука полон, отброшено %u байт\n", (unsigned)(bytes - sent));
  }
}
