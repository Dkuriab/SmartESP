#include "ReplyGate.h"

void ReplyGate::setActiveTurn(uint32_t turn) {
  if (turn != activeTurn_) {
    open_ = false;
  }
  activeTurn_ = turn;
}

void ReplyGate::onCommand(const ServerCommand& command) {
  switch (command.type) {
    case ServerCommandType::ReplyStart:
      if (command.turn == activeTurn_) {
        open_ = true;
      }
      break;
    case ServerCommandType::ReplyEnd:
      if (command.turn == activeTurn_) {
        open_ = false;
      }
      break;
    case ServerCommandType::StopPlayback:
      open_ = false;
      break;
    case ServerCommandType::Announce:
      if (activeTurn_ == 0) {
        activeTurn_ = command.turn;
        open_ = false;
      }
      break;
    default:
      break;
  }
}

bool ReplyGate::isOpen() const {
  return open_;
}
