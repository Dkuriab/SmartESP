#include "Updater.h"

#include <HTTPClient.h>
#include <LittleFS.h>
#include <Update.h>
#include <WiFi.h>
#include <string.h>

#include "SoundFiles.h"
#include "esp_heap_caps.h"
#include "mbedtls/sha256.h"

namespace {

constexpr const char* PARTITION = "spiffs";  // раздел LittleFS (partitions.csv)
constexpr const char* MODEL_FILE = "/wakeword.bin";
constexpr const char* MODEL_TEMP = "/wakeword.tmp";
constexpr const char* MODEL_META = "/wakeword.cfg";
constexpr uint32_t META_MAGIC = 0x4B5A5731;  // «KZW1»
constexpr size_t CHUNK = 4096;
constexpr uint32_t REPORT_MS = 500;
constexpr uint32_t RESTART_DELAY_MS = 1500;  // успеть отправить итог
constexpr uint32_t HTTP_TIMEOUT_MS = 15000;
constexpr size_t MAX_MODEL = 1024 * 1024;  // модель слова — десятки КБ; больше — ошибка
constexpr UBaseType_t SOUND_QUEUE = 10;     // пять звуков при загрузке и запас на обновления
const Tone ALL_TONES[] = {Tone::Wake, Tone::Error, Tone::Thinking, Tone::Listen, Tone::Attention};

// Параметры сохранённой модели (файл MODEL_META).
struct Meta {
  uint32_t magic;
  uint32_t size;
  uint32_t arena;
  float cutoff;
  uint8_t window;
  char word[48];
};

void toHex(const uint8_t* digest, char* out) {
  static const char* digits = "0123456789abcdef";
  for (int i = 0; i < 32; ++i) {
    out[2 * i] = digits[digest[i] >> 4];
    out[2 * i + 1] = digits[digest[i] & 0x0F];
  }
  out[64] = '\0';
}

}  // namespace

bool Updater::begin() {
  events_ = xQueueCreate(8, sizeof(ClientEvent));
  sounds_ = xQueueCreate(SOUND_QUEUE, sizeof(StoredSound));
  storage_ = LittleFS.begin(true, "/littlefs", 10, PARTITION);
  if (!storage_) {
    Serial.println("updater: нет LittleFS — модель и звуки по воздуху не сохранить");
    return false;
  }
  prepareSoundFolder();
  for (Tone tone : ALL_TONES) {
    StoredSound sound{};
    if (sounds_ && loadSoundFile(tone, sound) && xQueueSend(sounds_, &sound, 0) != pdTRUE) {
      heap_caps_free(sound.pcm);
    }
  }
  return events_ != nullptr && sounds_ != nullptr;
}

void Updater::setServer(const char* host, uint16_t port) {
  taskENTER_CRITICAL(&serverLock_);
  strncpy(host_, host ? host : "", sizeof(host_) - 1);
  port_ = port;
  taskEXIT_CRITICAL(&serverLock_);
}

bool Updater::loadModel(StoredModel& out) {
  if (!storage_ || !LittleFS.exists(MODEL_META) || !LittleFS.exists(MODEL_FILE)) {
    return false;
  }
  Meta meta{};
  File metaFile = LittleFS.open(MODEL_META, "r");
  const bool metaOk = metaFile && metaFile.read((uint8_t*)&meta, sizeof(meta)) == sizeof(meta);
  metaFile.close();
  File model = LittleFS.open(MODEL_FILE, "r");
  if (!metaOk || meta.magic != META_MAGIC || !model || model.size() != meta.size || meta.size > MAX_MODEL) {
    model.close();
    Serial.println("updater: сохранённая модель испорчена — будет встроенная");
    return false;
  }
  uint8_t* data = (uint8_t*)heap_caps_aligned_alloc(16, meta.size, MALLOC_CAP_SPIRAM);
  const bool read = data && model.read(data, meta.size) == meta.size;
  model.close();
  if (!read) {
    heap_caps_free(data);
    return false;
  }
  meta.word[sizeof(meta.word) - 1] = '\0';
  out = StoredModel{data, meta.size, meta.arena, meta.cutoff, meta.window, {}};
  strncpy(out.word, meta.word, sizeof(out.word) - 1);
  Serial.printf("updater: модель «%s» из памяти, %u байт\n", out.word, (unsigned)out.size);
  return true;
}

void Updater::forgetModel() {
  if (storage_) {
    LittleFS.remove(MODEL_FILE);
    LittleFS.remove(MODEL_META);
  }
}

bool Updater::start(const UpdateRequest& request) {
  if (busy_ || restartAt_ != 0) {
    ClientEvent event{};
    event.type = ClientEventType::UpdateStatus;
    event.updateKind = request.kind;
    event.updateTone = request.tone;
    event.updateState = UpdateState::Failed;
    event.updateError = UpdateError::Busy;
    event.total = request.size;
    if (events_) xQueueSend(events_, &event, 0);
    return false;
  }
  request_ = request;
  busy_ = true;
  done_ = 0;
  lastReportMs_ = 0;
  if (xTaskCreatePinnedToCore(taskEntry, "updater", 8192, this, 1, nullptr, 0) != pdPASS) {
    busy_ = false;
    report(UpdateState::Failed, UpdateError::Write, true);
    return false;
  }
  return true;
}

void Updater::taskEntry(void* self) {
  static_cast<Updater*>(self)->run();
  vTaskDelete(nullptr);
}

void Updater::run() {
  static const char* const KINDS[] = {"прошивка", "модель", "звук"};
  Serial.printf("updater: %s, %u байт\n", KINDS[static_cast<int>(request_.kind)], (unsigned)request_.size);
  UpdateError error = UpdateError::None;
  const bool sound = request_.kind == UpdateKind::Sound;
  // звук размера 0 — не качаем: удалить свой, вернуть встроенный
  const bool ok = (sound && request_.size == 0) ? finishSound(error) : download(error) && finish(error);
  report(ok ? UpdateState::Done : UpdateState::Failed, error, true);
  Serial.printf("updater: %s\n", !ok ? "не удалось" : sound ? "готово" : "готово, перезагрузка");
  if (ok && !sound) {
    restartAt_ = millis() + RESTART_DELAY_MS;
  }
  busy_ = false;
}

// Скачанный и проверенный файл — на место: прошивку уже закончил Update.end().
bool Updater::finish(UpdateError& error) {
  switch (request_.kind) {
    case UpdateKind::Firmware: return true;
    case UpdateKind::Model: return finishModel(error);
    case UpdateKind::Sound: return finishSound(error);
  }
  return false;
}

// Звук: временный файл — на место и в PSRAM (его заберёт pollSound); размер 0 — удалить свой.
bool Updater::finishSound(UpdateError& error) {
  const Tone tone = request_.tone;
  StoredSound sound{tone, nullptr, 0, {}};
  if (!storage_) {
    error = UpdateError::Storage;
    return false;
  }
  if (request_.size == 0) {
    removeSoundFile(tone);
  } else if (!commitSoundFile(tone, request_.sha256) || !loadSoundFile(tone, sound)) {
    error = UpdateError::Storage;
    return false;
  }
  if (xQueueSend(sounds_, &sound, pdMS_TO_TICKS(1000)) != pdTRUE) {
    heap_caps_free(sound.pcm);  // loop() не забирает звуки — заиграет после перезагрузки
  }
  return true;
}

bool Updater::pollSound(StoredSound& sound) {
  return sounds_ && xQueueReceive(sounds_, &sound, 0) == pdTRUE;
}

// Скачивает файл и пишет его (прошивку — через Update, модель и звук — во временный файл), считая SHA-256.
bool Updater::download(UpdateError& error) {
  const bool firmware = request_.kind == UpdateKind::Firmware;
  const bool sound = request_.kind == UpdateKind::Sound;
  const bool fits = sound ? request_.size <= MAX_SOUND_BYTES && request_.size % 2 == 0 : request_.size <= MAX_MODEL;
  if (!firmware && (!storage_ || !fits)) {
    error = storage_ ? UpdateError::Size : UpdateError::Storage;
    return false;
  }
  const char* tempPath = sound ? soundTempPath(request_.tone) : MODEL_TEMP;
  char host[sizeof(host_)];
  taskENTER_CRITICAL(&serverLock_);
  memcpy(host, host_, sizeof(host));
  const uint16_t port = port_;
  taskEXIT_CRITICAL(&serverLock_);
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (host[0] == '\0' || !http.begin(client, host, port, request_.path) || http.GET() != HTTP_CODE_OK) {
    error = UpdateError::Download;
    http.end();
    return false;
  }
  if (http.getSize() != (int)request_.size) {
    error = UpdateError::Size;
    http.end();
    return false;
  }
  if (firmware ? !Update.begin(request_.size, U_FLASH) : false) {
    error = UpdateError::Size;  // не помещается в слот (старая разметка — 3 МБ)
    http.end();
    return false;
  }
  File temp = firmware ? File() : LittleFS.open(tempPath, "w");
  uint8_t* buffer = (uint8_t*)malloc(CHUNK);
  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  mbedtls_sha256_starts(&sha, 0);
  WiFiClient* stream = http.getStreamPtr();
  bool ok = buffer && (firmware || temp);
  while (ok && done_ < request_.size) {
    const size_t want = min((size_t)CHUNK, (size_t)(request_.size - done_));
    const size_t got = stream->readBytes(buffer, want);  // ждёт не дольше таймаута клиента
    if (got == 0) {
      error = UpdateError::Download;
      ok = false;
      break;
    }
    mbedtls_sha256_update(&sha, buffer, got);
    const size_t written = firmware ? Update.write(buffer, got) : temp.write(buffer, got);
    if (written != got) {
      error = UpdateError::Write;
      ok = false;
      break;
    }
    done_ += got;
    report(UpdateState::Progress, UpdateError::None, false);
  }
  uint8_t digest[32];
  mbedtls_sha256_finish(&sha, digest);
  mbedtls_sha256_free(&sha);
  free(buffer);
  if (temp) temp.close();
  http.end();
  char hex[65];
  toHex(digest, hex);
  if (ok && strcmp(hex, request_.sha256) != 0) {
    error = UpdateError::Hash;
    ok = false;
  }
  if (firmware) {
    if (!ok) {
      Update.abort();
    } else if (!Update.end(true)) {
      error = UpdateError::Write;
      ok = false;
    }
  } else if (!ok) {
    LittleFS.remove(tempPath);
  }
  if (!ok && error == UpdateError::None) {
    error = UpdateError::Write;
  }
  return ok;
}

// Модель скачана и проверена: параметры — в MODEL_META, временный файл — на место MODEL_FILE.
bool Updater::finishModel(UpdateError& error) {
  Meta meta{META_MAGIC, request_.size, request_.arena, request_.cutoff, request_.window, {}};
  strncpy(meta.word, request_.word, sizeof(meta.word) - 1);
  LittleFS.remove(MODEL_FILE);
  LittleFS.remove(MODEL_META);
  File metaFile = LittleFS.open(MODEL_META, "w");
  const bool metaOk = metaFile && metaFile.write((const uint8_t*)&meta, sizeof(meta)) == sizeof(meta);
  metaFile.close();
  if (!metaOk || !LittleFS.rename(MODEL_TEMP, MODEL_FILE)) {
    LittleFS.remove(MODEL_TEMP);
    LittleFS.remove(MODEL_META);
    error = UpdateError::Storage;
    return false;
  }
  return true;
}

void Updater::report(UpdateState state, UpdateError error, bool force) {
  const uint32_t now = millis();
  if (!force && now - lastReportMs_ < REPORT_MS) {
    return;
  }
  lastReportMs_ = now;
  ClientEvent event{};
  event.type = ClientEventType::UpdateStatus;
  event.updateKind = request_.kind;
  event.updateTone = request_.tone;
  event.updateState = state;
  event.updateError = error;
  event.bytes = done_;
  event.total = request_.size;
  if (events_) {
    // ход можно пропустить (очередь полна), итог — подождать места
    xQueueSend(events_, &event, force ? pdMS_TO_TICKS(1000) : 0);
  }
}

bool Updater::pollStatus(ClientEvent& event) {
  return events_ && xQueueReceive(events_, &event, 0) == pdTRUE;
}

void Updater::loop(uint32_t nowMs) {
  if (restartAt_ != 0 && (int32_t)(nowMs - restartAt_) >= 0) {
    ESP.restart();
  }
}
