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
      } else if (elapsed >= config_.maxUtteranceMs) {
        endUtterance(UtteranceEndReason::Timeout, SessionState::Waiting);
      }
      break;
    case SessionState::Waiting:
      if (elapsed >= config_.replyTimeoutMs) {
        pushTone(Tone::Error);
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
          startTurn();
        } else {
          pushTone(Tone::Error);
        }
      } else if (state_ == SessionState::Waiting || state_ == SessionState::Speaking) {
        // Перебивание: обрываем ответ, сообщаем серверу, начинаем новый ход.
        pushSimple(ActionType::StopPlayback);
        pushEvent(ClientEventType::BargeIn);
        startTurn();
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
      pushTone(command.tone);
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

void Session::startTurn() {
  turn_++;
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

void Session::enter(SessionState next) {
  state_ = next;
  stateSinceMs_ = nowMs_;
  speechStarted_ = false;
  replyEnded_ = false;
}

void Session::checkPlaybackDone() {
  if (replyEnded_ && !playbackActive_) {
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
  action.event = ClientEvent{type, turn_, reason};
  push(action);
}

void Session::pushTone(Tone tone) {
  Action action{};
  action.type = ActionType::PlayTone;
  action.tone = tone;
  push(action);
}
