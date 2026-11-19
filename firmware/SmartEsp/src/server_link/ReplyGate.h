#pragma once

// Внутренний файл модуля server_link: решает, принимать ли бинарный звук
// ответа. Открыт только между reply_start и reply_end текущего хода —
// так запоздавший ответ на перебитый вопрос не проиграется.
//
// Объявление ядра: announce, reply_start и звук приходят подряд, раньше, чем
// loop() успеет выдать SetActiveTurn. Поэтому announce, пришедший при текущем
// ходе 0 (колонка свободна — session выдаёт SetActiveTurn(0) при каждом входе в
// Idle), сразу делает свой ход текущим. Занятой колонке announce шлюз не меняет:
// звук объявления, отправленный до ответа busy, отбрасывается.

#include <stdint.h>

#include "../common/Types.h"

class ReplyGate {
 public:
  // Новый текущий ход. Смена хода закрывает шлюз.
  void setActiveTurn(uint32_t turn);

  // ReplyStart текущего хода открывает; ReplyEnd текущего хода и StopPlayback закрывают;
  // Announce при текущем ходе 0 делает свой ход текущим.
  void onCommand(const ServerCommand& command);

  bool isOpen() const;

 private:
  uint32_t activeTurn_ = 0;
  bool open_ = false;
};
