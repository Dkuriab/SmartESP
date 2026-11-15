#pragma once

// Внутренний файл модуля server_link: решает, принимать ли бинарный звук
// ответа. Открыт только между reply_start и reply_end текущего хода —
// так запоздавший ответ на перебитый вопрос не проиграется.

#include <stdint.h>

#include "../common/Types.h"

class ReplyGate {
 public:
  // Новый текущий ход. Смена хода закрывает шлюз.
  void setActiveTurn(uint32_t turn);

  // ReplyStart текущего хода открывает; ReplyEnd текущего хода и StopPlayback закрывают.
  void onCommand(const ServerCommand& command);

  bool isOpen() const;

 private:
  uint32_t activeTurn_ = 0;
  bool open_ = false;
};
