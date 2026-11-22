#pragma once

// updater — обновление по воздуху: ядро присылает команду update, колонка сама скачивает файл
// с сервера ядра по HTTP и пишет его:
//   - прошивку — во вторую половину флеша (Update); загрузка переключается только после полной
//     записи и проверки SHA-256, иначе колонка остаётся на старой прошивке;
//   - модель слова — в LittleFS (раздел «spiffs»): временный файл, проверка SHA-256, переименование;
//   - свой звук сигнала — так же в LittleFS (/sounds/<tone>.pcm), без перезагрузки: готовый звук
//     отдаёт pollSound(); размер 0 — звук удаляется, снова встроенный.
// После успеха прошивки или модели — перезагрузка (через секунду: успеть отправить итог). Скачивание идёт в своей
// задаче FreeRTOS — loop() не блокируется. Ход и итог — события update_status (pollStatus).
// Ещё модуль хранит модель: loadModel() при загрузке отдаёт сохранённую (или false — встроенную),
// и свои звуки: сохранённые отдаёт pollSound() сразу после begin().

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "../common/Types.h"

struct UpdaterConfig {
  const char* host;  // сервер ядра (тот же, что у server_link)
  uint16_t port;
};

class Updater {
 public:
  // Монтирует LittleFS (раздел «spiffs»; пустой — форматирует, один раз до ~10 с) и читает
  // сохранённые звуки в PSRAM (их отдаст pollSound). false — нет файловой системы: модель и
  // звуки не сохранить, прошивку обновлять можно.
  bool begin(const UpdaterConfig& config);

  // Сохранённая обновлением модель слова (данные — в PSRAM). false — её нет или она испорчена.
  bool loadModel(StoredModel& out);

  // Удаляет сохранённую модель (она не запустилась): со следующей загрузки — встроенная.
  void forgetModel();

  // Запускает скачивание. false — уже идёт обновление (итог Busy придёт в pollStatus).
  bool start(const UpdateRequest& request);

  // Свой звук сигнала: сохранённый при загрузке или только что присланный (pcm == nullptr —
  // снова встроенный). Буфер (PSRAM) переходит вызывающему: его отдают audio_out.setSound.
  bool pollSound(StoredSound& sound);

  // Следующее событие update_status для сервера (ход — не чаще раза в 0,5 с, затем итог).
  bool pollStatus(ClientEvent& event);

  // Вызывать из loop(): после успеха перезагружает колонку.
  void loop(uint32_t nowMs);

 private:
  static void taskEntry(void* self);
  void run();
  bool download(UpdateError& error);
  bool finishModel(UpdateError& error);
  bool finishSound(UpdateError& error);
  bool finish(UpdateError& error);
  void report(UpdateState state, UpdateError error, bool force);

  UpdaterConfig config_{};
  bool storage_ = false;
  QueueHandle_t events_ = nullptr;  // задача скачивания → loop()
  QueueHandle_t sounds_ = nullptr;  // готовые звуки (StoredSound) → loop()
  UpdateRequest request_{};         // текущее обновление (пишет start, читает задача)
  volatile bool busy_ = false;
  volatile uint32_t restartAt_ = 0;  // millis() перезагрузки; 0 — нет
  uint32_t done_ = 0;                // скачано байт (только задача)
  uint32_t lastReportMs_ = 0;
};
