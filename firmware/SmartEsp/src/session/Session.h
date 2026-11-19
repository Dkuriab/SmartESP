#pragma once

// session — сценарий колонки (дизайн, раздел 5): ожидание → слушаем вопрос →
// ждём ответ → говорим, перебивание словом, таймауты.
// Команды сервера: cancel_turn (тихий возврат в Idle), announce (из Idle — сигнал
// «внимание» и ожидание reply_start), listen (из Idle сразу слушать вопрос; ход серверный).
// Если announce/listen пришли не в Idle — отвечаем событием busy с их номером хода, thinking-тон в Waiting продлевает ожидание ответа.
// Чистая логика: не трогает железо и сеть, только выдаёт «действия»,
// которые SmartEsp.ino передаёт модулям. Время передаётся снаружи,
// поэтому модуль тестируется на ноутбуке (tools/host_tests).

#include <stdint.h>

#include "../common/Types.h"

enum class SessionState : uint8_t { Idle, Listening, Waiting, Speaking };

struct SessionConfig {
  uint32_t noSpeechTimeoutMs = 5000;  // после слова так и не заговорили
  uint32_t maxUtteranceMs = 10000;    // максимум длины вопроса от слова
  uint32_t replyTimeoutMs = 15000;    // ответ так и не начался
};

class Session {
 public:
  void begin(const SessionConfig& config);

  // Текущее время (millis()); обработчики событий используют последнее переданное.
  void loop(uint32_t nowMs);

  void onVoiceEvent(const VoiceEvent& event);
  void onServerCommand(const ServerCommand& command);

  // Есть ли связь с сервером. Вызывать каждый loop.
  void setConnected(bool connected);

  // Играет ли динамик (очередь или тон). Вызывать каждый loop.
  void setPlaybackActive(bool active);

  // Следующее действие (по порядку), если есть.
  bool pollAction(Action& action);

  SessionState state() const;
  uint32_t turn() const;

 private:
  void startTurn(float level);
  void endUtterance(UtteranceEndReason reason, SessionState next);
  void abandonTurn();
  void enter(SessionState next);
  void checkPlaybackDone();

  void push(const Action& action);
  void pushSimple(ActionType type);
  void pushEvent(ClientEventType type, UtteranceEndReason reason = UtteranceEndReason::Vad);
  void pushEventFor(ClientEventType type, uint32_t turn);
  void pushTone(Tone tone);

  SessionConfig config_{};
  SessionState state_ = SessionState::Idle;
  uint32_t turn_ = 0;       // активный ход (свой или объявление ядра)
  uint32_t localTurn_ = 0;  // счётчик собственных ходов (по слову)
  float pendingLevel_ = 0;  // уровень слова для события wake, dBFS
  uint32_t nowMs_ = 0;
  uint32_t stateSinceMs_ = 0;
  bool speechStarted_ = false;
  bool replyEnded_ = false;
  bool connected_ = false;
  bool playbackActive_ = false;

  static constexpr uint32_t ACTION_QUEUE = 16;
  Action actions_[ACTION_QUEUE] = {};
  uint32_t actionHead_ = 0;
  uint32_t actionCount_ = 0;
};
