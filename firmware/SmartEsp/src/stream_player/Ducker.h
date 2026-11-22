#pragma once

// Внутренний файл модуля stream_player: когда глушить музыку и плавное усиление.
// Сценарий ушёл из покоя (слово, вопрос, ответ, объявление) — музыка глохнет сразу
// (затухание fadeOutMs); вернулся в покой и пробыл в нём resumeDelayMs — возвращается
// (нарастание fadeInMs). Шаг усиления — на отсчёт частоты потока (setSampleRate). Чистая логика без Arduino — тестируется на ноутбуке.
// update() — из loop(), next()/silent()/restart() — из задачи звука.

#include <stddef.h>
#include <stdint.h>

class Ducker {
 public:
  Ducker(uint32_t resumeDelayMs = 1500, uint32_t fadeOutMs = 30, uint32_t fadeInMs = 300,
         uint32_t sampleRate = 16000);

  // Сценарий не в покое (voiceActive) или в покое; nowMs — millis().
  void update(bool voiceActive, uint32_t nowMs);

  // Музыка должна молчать (цель усиления — 0).
  bool muted() const;

  // Усиление следующего отсчёта 0..1: шаг к цели (0 — заглушено, 1 — нет).
  float next();

  // Заглушено и уже затихло: при паузе играть нечего.
  bool silent() const;

  // Новый поток: начать с тишины и нарасти.
  void restart();

  // Сколько покоя ждать перед возвратом музыки (до начала работы).
  void setResumeDelay(uint32_t resumeDelayMs);

  // Частота потока: шаги затухания и нарастания пересчитываются (из задачи звука).
  void setSampleRate(uint32_t sampleRate);

 private:
  uint32_t resumeDelayMs_;
  uint32_t fadeOutMs_;
  uint32_t fadeInMs_;
  float down_;  // шаг затухания на отсчёт
  float up_;    // шаг нарастания на отсчёт
  volatile bool muted_ = false;
  bool voice_ = false;           // последний update — сценарий не в покое
  uint32_t quietSinceMs_ = 0;    // когда сценарий вернулся в покой
  float gain_ = 0.0f;            // только задача звука
};
