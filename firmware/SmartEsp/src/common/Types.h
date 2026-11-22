#pragma once

// Общие типы, которыми модули обмениваются через SmartEsp.ino.
// Только перечисления и простые структуры: без функций, переменных и
// подключений модулей. Файл собирается и на ноутбуке (host-тесты),
// поэтому Arduino.h здесь не подключается.

#include <stddef.h>
#include <stdint.h>

// ---------- voice_frontend, wake_word → session ----------

enum class VoiceEventType : uint8_t {
  WakeWord,     // услышано слово-активатор (wake_word; громкость — voice_frontend)
  SpeechStart,  // началась речь (только при включённом захвате)
  SpeechEnd,    // речь закончилась (только при включённом захвате)
};

struct VoiceEvent {
  VoiceEventType type;
  float level;  // дБFS, только для WakeWord
};

// ---------- встроенные звуки audio_out ----------

enum class Tone : uint8_t {
  Wake,      // слово услышано
  Error,     // ошибка: нет связи, нет ответа
  Thinking,  // ждём ответ
  Listen,    // колонка сама начала слушать (команда listen)
  Attention, // перед объявлением ядра
};

// ---------- события ESP → сервер ----------

enum class UtteranceEndReason : uint8_t {
  Vad,       // детектор речи: тишина после фразы
  Timeout,   // вопрос длиннее максимума
  Server,    // сервер сам решил, что фраза закончилась
  NoSpeech,  // после слова так и не заговорили
};

// ---------- обновление по воздуху (updater) ----------

enum class UpdateKind : uint8_t {
  Firmware,  // новая прошивка: пишется во вторую половину флеша, затем перезагрузка
  Model,     // новая модель слова: в LittleFS, затем перезагрузка
};

enum class UpdateState : uint8_t {
  Progress,  // качается: done из total байт
  Done,      // записано и проверено; сейчас перезагрузка
  Failed,    // не вышло; колонка работает как раньше
};

enum class UpdateError : uint8_t {
  None,
  Busy,      // уже идёт другое обновление
  Download,  // HTTP-ошибка или обрыв
  Size,      // размер не тот, или не помещается
  Hash,      // SHA-256 не совпал
  Write,     // не записалось во флеш
  Storage,   // нет файловой системы для модели
};

// Что обновить (команда update): файл с ядра по пути path на SERVER_HOST:SERVER_PORT.
struct UpdateRequest {
  UpdateKind kind;
  uint32_t size;      // байт
  char path[96];      // «/device/files/<токен>»
  char sha256[65];    // 64 шестнадцатеричных символа
  // только для Model — параметры из манифеста
  float cutoff;
  uint8_t window;
  uint32_t arena;
  char word[48];      // UTF-8, для журнала
};

// Модель слова, сохранённая обновлением (updater.loadModel); данные — в PSRAM, выровнены на 16 байт.
struct StoredModel {
  const uint8_t* data;
  size_t size;
  size_t arena;
  float cutoff;
  uint8_t window;
  char word[48];
};

// hello шлёт сам server_link при подключении, поэтому его здесь нет.
enum class ClientEventType : uint8_t {
  Wake,
  UtteranceEnd,
  BargeIn,
  PlaybackDone,
  Busy,    // ответ на announce/listen, когда колонка занята
  Played,  // сколько звука ответа уже доиграно (раз в ~0,5 с и перед playback_done)
  UpdateStatus,  // ход и итог обновления по воздуху (updater)
};

struct ClientEvent {
  ClientEventType type;
  uint32_t turn;              // номер хода
  UtteranceEndReason reason;  // только для UtteranceEnd
  float level;                // дБFS, только для Wake
  uint32_t bytes;             // для Played: байт PCM ответа хода, отданных динамику; для UpdateStatus — скачано
  // только для UpdateStatus
  UpdateKind updateKind;
  UpdateState updateState;
  UpdateError updateError;
  uint32_t total;             // размер файла обновления, байт
};

// ---------- команды сервер → ESP ----------

enum class ServerCommandType : uint8_t {
  StopListening,
  ReplyStart,
  ReplyEnd,
  StopPlayback,
  Volume,
  PlayTone,
  CancelTurn,  // ядро отменило ход
  Announce,    // ядро само начинает ответ
  Listen,      // ядро просит слушать (вопрос от самой колонки)
  Update,      // ядро присылает обновление (прошивку или модель слова) — его делает updater
};

struct ServerCommand {
  ServerCommandType type;
  uint32_t turn;  // для StopListening, ReplyStart, ReplyEnd, CancelTurn, Announce, Listen; иначе 0
  float volume;   // для Volume, 0..1
  Tone tone;      // для PlayTone
  UpdateRequest update;  // для Update
};

// ---------- действия session → модули (выполняет SmartEsp.ino) ----------

enum class ActionType : uint8_t {
  StartCapture,   // voice_frontend.setCapture(true)
  StopCapture,    // voice_frontend.setCapture(false)
  SendEvent,      // server_link.sendEvent(event)
  StopPlayback,   // audio_out.stop()
  PlayTone,       // audio_out.playTone(tone)
  SetVolume,      // audio_out.setVolume(volume)
  SetActiveTurn,  // server_link.setActiveTurn(turn)
};

struct Action {
  ActionType type;
  ClientEvent event;  // для SendEvent
  Tone tone;          // для PlayTone
  float volume;       // для SetVolume
  uint32_t turn;      // для SetActiveTurn
};
