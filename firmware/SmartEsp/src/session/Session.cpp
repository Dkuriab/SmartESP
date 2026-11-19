#include "Session.h"

void Session::begin(const SessionConfig& config) {
  config_ = config;
}

void Session::loop(uint32_t nowMs) {
  nowMs_ = nowMs;
  const uint32_t elapsed = nowMs_ - stateSinceMs_;

  switch (state_) {
    case SessionState::Listening:
      if (!speechStarted_ && elapsed >= config_.noSpeechTimeoutMs) {
        endUtterance(UtteranceEndReason::NoSpeech, SessionState::Idle);
        abandonTurn();
      } else if (elapsed >= config_.maxUtteranceMs) {
        endUtterance(UtteranceEndReason::Timeout, SessionState::Waiting);
      }
      break;
    case SessionState::Waiting:
      if (elapsed >= config_.replyTimeoutMs) {
        pushTone(Tone::Error);
        abandonTurn();
        enter(SessionState::Idle);
      }
      break;
    case SessionState::Speaking:
      checkPlaybackDone();
      break;
    case SessionState::Idle:
      break;
  }
}

void Session::onVoiceEvent(const VoiceEvent& event) {
  switch (event.type) {
    case VoiceEventType::WakeWord:
      if (state_ == SessionState::Idle) {
        if (connected_) {
          startTurn(event.level);
        } else {
          pushTone(Tone::Error);
        }
      } else if (state_ == SessionState::Waiting || state_ == SessionState::Speaking) {
        // Перебивание: обрываем ответ, сообщаем серверу, начинаем новый ход.
        pushSimple(ActionType::StopPlayback);
        pushEvent(ClientEventType::BargeIn);
        startTurn(event.level);
      }
      // В Listening слово игнорируется.
      break;
    case VoiceEventType::SpeechStart:
      if (state_ == SessionState::Listening) {
        speechStarted_ = true;
      }
      break;
    case VoiceEventType::SpeechEnd:
      if (state_ == SessionState::Listening) {
        endUtterance(UtteranceEndReason::Vad, SessionState::Waiting);
      }
      break;
  }
}

void Session::onServerCommand(const ServerCommand& command) {
  const bool currentTurn = command.turn == turn_;
  switch (command.type) {
    case ServerCommandType::StopListening:
      if (currentTurn && state_ == SessionState::Listening) {
        endUtterance(UtteranceEndReason::Server, SessionState::Waiting);
      }
      break;
    case ServerCommandType::ReplyStart:
      if (!currentTurn) {
        break;
      }
      if (state_ == SessionState::Listening) {
        // Сервер ответил раньше, чем мы заметили конец фразы.
        endUtterance(UtteranceEndReason::Server, SessionState::Speaking);
      } else if (state_ == SessionState::Waiting) {
        enter(SessionState::Speaking);
      }
      break;
    case ServerCommandType::ReplyEnd:
      // «Доиграно» проверяется в loop()/setPlaybackActive(): здесь флаг
      // воспроизведения может быть ещё старым, пока хвост ответа ставится в очередь.
      if (currentTurn && state_ == SessionState::Speaking) {
        replyEnded_ = true;
      }
      break;
    case ServerCommandType::StopPlayback:
      pushSimple(ActionType::StopPlayback);
      if (state_ == SessionState::Speaking) {
        abandonTurn();
        enter(SessionState::Idle);
      }
      break;
    case ServerCommandType::Volume: {
      Action action{};
      action.type = ActionType::SetVolume;
      action.volume = command.volume;
      push(action);
      break;
    }
    case ServerCommandType::PlayTone:
      if (command.tone == Tone::Thinking && state_ == SessionState::Waiting) {
        // Сервер ещё думает: продлеваем ожидание ответа ещё на replyTimeoutMs.
        stateSinceMs_ = nowMs_;
      }
      pushTone(command.tone);
      break;
    case ServerCommandType::CancelTurn:
      // Сервер отменил ход (например, ложное срабатывание): тихо возвращаемся в Idle.
      if (currentTurn && state_ != SessionState::Idle) {
        if (state_ == SessionState::Listening) {
          pushSimple(ActionType::StopCapture);
        } else if (state_ == SessionState::Speaking) {
          pushSimple(ActionType::StopPlayback);
        }
        abandonTurn();
        enter(SessionState::Idle);
      }
      break;
    case ServerCommandType::Announce:
      // Объявление по инициативе сервера: принимаем только в покое и при связи.
      // Ход серверный; сигнал «внимание» играем сами только при согласии (на busy —
      // тишина, разговор владельца не прерываем); дальше ждём reply_start, как после вопроса.
      if (state_ == SessionState::Idle) {
        if (connected_) {
          turn_ = command.turn;
          Action action{};
          action.type = ActionType::SetActiveTurn;
          action.turn = turn_;
          push(action);
          pushTone(Tone::Attention);
          enter(SessionState::Waiting);
        }
      } else {
        pushEventFor(ClientEventType::Busy, command.turn);
      }
      break;
    case ServerCommandType::Listen:
      // Ядро просит слушать: как после слова, но без события wake; ход серверный.
      if (state_ == SessionState::Idle) {
        if (connected_) {
          turn_ = command.turn;
          Action action{};
          action.type = ActionType::SetActiveTurn;
          action.turn = turn_;
          push(action);
          pushTone(Tone::Listen);
          pushSimple(ActionType::StartCapture);
          enter(SessionState::Listening);
        }
      } else {
        pushEventFor(ClientEventType::Busy, command.turn);
      }
      break;
  }
}

void Session::setConnected(bool connected) {
  const bool lost = connected_ && !connected;
  connected_ = connected;
  if (!lost || state_ == SessionState::Idle) {
    return;
  }
  if (state_ == SessionState::Listening) {
    pushSimple(ActionType::StopCapture);
  } else if (state_ == SessionState::Speaking) {
    pushSimple(ActionType::StopPlayback);
  }
  pushTone(Tone::Error);
  abandonTurn();
  enter(SessionState::Idle);
}

void Session::setPlaybackActive(bool active) {
  playbackActive_ = active;
  if (state_ == SessionState::Speaking) {
    checkPlaybackDone();
  }
}

bool Session::pollAction(Action& action) {
  if (actionCount_ == 0) {
    return false;
  }
  const uint32_t tail = (actionHead_ + ACTION_QUEUE - actionCount_) % ACTION_QUEUE;
  action = actions_[tail];
  actionCount_--;
  return true;
}

SessionState Session::state() const {
  return state_;
}

uint32_t Session::turn() const {
  return turn_;
}

void Session::startTurn(float level) {
  turn_ = ++localTurn_;
  pendingLevel_ = level;
  pushTone(Tone::Wake);
  Action action{};
  action.type = ActionType::SetActiveTurn;
  action.turn = turn_;
  push(action);
  pushEvent(ClientEventType::Wake);
  pushSimple(ActionType::StartCapture);
  enter(SessionState::Listening);
}

void Session::endUtterance(UtteranceEndReason reason, SessionState next) {
  pushSimple(ActionType::StopCapture);
  pushEvent(ClientEventType::UtteranceEnd, reason);
  enter(next);
}

void Session::abandonTurn() {
  // Ход закончен или брошен: закрываем приём звука ответа (запоздавший ответ на этот
  // ход не заиграет в Idle). Каждый вход в Idle идёт через это действие: шлюз звука
  // по «текущий ход 0» понимает, что колонка свободна и может принять announce.
  Action action{};
  action.type = ActionType::SetActiveTurn;
  action.turn = 0;
  push(action);
}

void Session::enter(SessionState next) {
  state_ = next;
  stateSinceMs_ = nowMs_;
  speechStarted_ = false;
  replyEnded_ = false;
}

void Session::checkPlaybackDone() {
  if (replyEnded_ && !playbackActive_) {
    abandonTurn();  // до события: к приходу следующего announce шлюз звука уже свободен
    pushEvent(ClientEventType::PlaybackDone);
    enter(SessionState::Idle);
  }
}

void Session::push(const Action& action) {
  if (actionCount_ == ACTION_QUEUE) {
    return;  // не бывает: за одно событие — не больше 6 действий, .ino выбирает их каждый loop
  }
  actions_[actionHead_] = action;
  actionHead_ = (actionHead_ + 1) % ACTION_QUEUE;
  actionCount_++;
}

void Session::pushSimple(ActionType type) {
  Action action{};
  action.type = type;
  push(action);
}

void Session::pushEvent(ClientEventType type, UtteranceEndReason reason) {
  Action action{};
  action.type = ActionType::SendEvent;
  action.event = ClientEvent{type, turn_, reason, type == ClientEventType::Wake ? pendingLevel_ : 0.0f};
  push(action);
}

void Session::pushEventFor(ClientEventType type, uint32_t turn) {
  Action action{};
  action.type = ActionType::SendEvent;
  action.event = ClientEvent{type, turn, UtteranceEndReason::Vad, 0.0f};
  push(action);
}

void Session::pushTone(Tone tone) {
  Action action{};
  action.type = ActionType::PlayTone;
  action.tone = tone;
  push(action);
}
