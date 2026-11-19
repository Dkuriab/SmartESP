// Тесты сценария колонки (session). Проверяется точная последовательность действий.

#include <vector>

#include "session/Session.h"
#include "test.h"

namespace {

std::vector<Action> drain(Session& session) {
  std::vector<Action> actions;
  Action action;
  while (session.pollAction(action)) {
    actions.push_back(action);
  }
  return actions;
}

// Ожидаемое действие в компактной записи.
struct Expect {
  ActionType type;
  ClientEventType event = ClientEventType::Wake;
  uint32_t turn = 0;
  UtteranceEndReason reason = UtteranceEndReason::Vad;
  Tone tone = Tone::Wake;
  float volume = 0;
};

Expect sendEvent(ClientEventType event, uint32_t turn, UtteranceEndReason reason = UtteranceEndReason::Vad) {
  Expect e{ActionType::SendEvent};
  e.event = event;
  e.turn = turn;
  e.reason = reason;
  return e;
}

Expect playTone(Tone tone) {
  Expect e{ActionType::PlayTone};
  e.tone = tone;
  return e;
}

Expect setActiveTurn(uint32_t turn) {
  Expect e{ActionType::SetActiveTurn};
  e.turn = turn;
  return e;
}

Expect simple(ActionType type) {
  return Expect{type};
}

bool matches(const Action& a, const Expect& e) {
  if (a.type != e.type) return false;
  switch (e.type) {
    case ActionType::SendEvent:
      return a.event.type == e.event && a.event.turn == e.turn &&
             (e.event != ClientEventType::UtteranceEnd || a.event.reason == e.reason);
    case ActionType::PlayTone: return a.tone == e.tone;
    case ActionType::SetActiveTurn: return a.turn == e.turn;
    case ActionType::SetVolume: return a.volume == e.volume;
    default: return true;
  }
}

bool sameActions(const std::vector<Action>& actual, const std::vector<Expect>& expected) {
  if (actual.size() != expected.size()) {
    std::printf("    ожидалось действий: %zu, получено: %zu\n", expected.size(), actual.size());
    return false;
  }
  for (size_t i = 0; i < actual.size(); i++) {
    if (!matches(actual[i], expected[i])) {
      std::printf("    действие #%zu не совпало (тип %d)\n", i, (int)actual[i].type);
      return false;
    }
  }
  return true;
}

VoiceEvent voice(VoiceEventType type) {
  return VoiceEvent{type, 0.0f};
}

ServerCommand server(ServerCommandType type, uint32_t turn = 0) {
  ServerCommand cmd{};
  cmd.type = type;
  cmd.turn = turn;
  return cmd;
}

// Сессия с подключённым сервером в момент времени t.
Session connectedSession(uint32_t t = 1000) {
  Session session;
  session.begin(SessionConfig{});
  session.setConnected(true);
  session.loop(t);
  return session;
}

// Сессия в состоянии Listening (ход 1), начатом в момент t.
Session listeningSession(uint32_t t = 1000) {
  Session session = connectedSession(t);
  session.onVoiceEvent(voice(VoiceEventType::WakeWord));
  drain(session);
  return session;
}

Session waitingSession(uint32_t t = 1000) {
  Session session = listeningSession(t);
  session.onVoiceEvent(voice(VoiceEventType::SpeechStart));
  session.onVoiceEvent(voice(VoiceEventType::SpeechEnd));
  drain(session);
  return session;
}

Session speakingSession(uint32_t t = 1000) {
  Session session = waitingSession(t);
  session.onServerCommand(server(ServerCommandType::ReplyStart, 1));
  drain(session);
  return session;
}

}  // namespace

TEST(wake_from_idle) {
  Session session = connectedSession();
  session.onVoiceEvent(voice(VoiceEventType::WakeWord));
  CHECK(sameActions(drain(session), {playTone(Tone::Wake), setActiveTurn(1), sendEvent(ClientEventType::Wake, 1),
                                     simple(ActionType::StartCapture)}));
  CHECK(session.state() == SessionState::Listening);
  CHECK_EQ(session.turn(), 1u);
}

TEST(wake_when_disconnected) {
  Session session;
  session.begin(SessionConfig{});
  session.setConnected(false);
  session.loop(1000);
  session.onVoiceEvent(voice(VoiceEventType::WakeWord));
  CHECK(sameActions(drain(session), {playTone(Tone::Error)}));
  CHECK(session.state() == SessionState::Idle);
  CHECK_EQ(session.turn(), 0u);
}

TEST(speech_end) {
  Session session = listeningSession();
  session.onVoiceEvent(voice(VoiceEventType::SpeechStart));
  session.onVoiceEvent(voice(VoiceEventType::SpeechEnd));
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture),
                                     sendEvent(ClientEventType::UtteranceEnd, 1, UtteranceEndReason::Vad)}));
  CHECK(session.state() == SessionState::Waiting);
}

TEST(no_speech_timeout) {
  Session session = listeningSession(1000);
  session.loop(1000 + 4999);
  CHECK(drain(session).empty());
  session.loop(1000 + 5000);
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture),
                                     sendEvent(ClientEventType::UtteranceEnd, 1, UtteranceEndReason::NoSpeech),
                                     setActiveTurn(0)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(max_utterance_timeout) {
  Session session = listeningSession(1000);
  session.onVoiceEvent(voice(VoiceEventType::SpeechStart));
  session.loop(1000 + 9999);
  CHECK(drain(session).empty());
  session.loop(1000 + 10000);
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture),
                                     sendEvent(ClientEventType::UtteranceEnd, 1, UtteranceEndReason::Timeout)}));
  CHECK(session.state() == SessionState::Waiting);
}

TEST(server_stop_listening) {
  Session other = listeningSession();
  other.onServerCommand(server(ServerCommandType::StopListening, 7));
  CHECK(drain(other).empty());
  CHECK(other.state() == SessionState::Listening);

  Session session = listeningSession();
  session.onServerCommand(server(ServerCommandType::StopListening, 1));
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture),
                                     sendEvent(ClientEventType::UtteranceEnd, 1, UtteranceEndReason::Server)}));
  CHECK(session.state() == SessionState::Waiting);
}

TEST(wake_ignored_while_listening) {
  Session session = listeningSession();
  session.onVoiceEvent(voice(VoiceEventType::WakeWord));
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Listening);
  CHECK_EQ(session.turn(), 1u);
}

TEST(reply_flow) {
  Session session = waitingSession();
  session.onServerCommand(server(ServerCommandType::ReplyStart, 1));
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Speaking);
  session.setPlaybackActive(true);
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 1));
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Speaking);
  session.setPlaybackActive(false);
  CHECK(sameActions(drain(session), {sendEvent(ClientEventType::PlaybackDone, 1)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(reply_end_before_playback_started) {
  Session session = waitingSession();
  session.onServerCommand(server(ServerCommandType::ReplyStart, 1));
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 1));
  session.loop(2000);
  CHECK(sameActions(drain(session), {sendEvent(ClientEventType::PlaybackDone, 1)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(reply_start_while_listening) {
  Session session = listeningSession();
  session.onServerCommand(server(ServerCommandType::ReplyStart, 1));
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture),
                                     sendEvent(ClientEventType::UtteranceEnd, 1, UtteranceEndReason::Server)}));
  CHECK(session.state() == SessionState::Speaking);
}

TEST(reply_timeout) {
  Session session = waitingSession(1000);
  session.loop(1000 + 14999);
  CHECK(drain(session).empty());
  session.loop(1000 + 15000);
  CHECK(sameActions(drain(session), {playTone(Tone::Error), setActiveTurn(0)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(barge_in_while_speaking) {
  const std::vector<Expect> expected = {simple(ActionType::StopPlayback), sendEvent(ClientEventType::BargeIn, 1),
                                        playTone(Tone::Wake),            setActiveTurn(2),
                                        sendEvent(ClientEventType::Wake, 2), simple(ActionType::StartCapture)};

  Session speaking = speakingSession();
  speaking.onVoiceEvent(voice(VoiceEventType::WakeWord));
  CHECK(sameActions(drain(speaking), expected));
  CHECK(speaking.state() == SessionState::Listening);
  CHECK_EQ(speaking.turn(), 2u);

  Session waiting = waitingSession();
  waiting.onVoiceEvent(voice(VoiceEventType::WakeWord));
  CHECK(sameActions(drain(waiting), expected));
  CHECK(waiting.state() == SessionState::Listening);
}

TEST(stale_turn_commands_ignored) {
  Session session = speakingSession();
  session.onVoiceEvent(voice(VoiceEventType::WakeWord));
  drain(session);
  session.onServerCommand(server(ServerCommandType::ReplyStart, 1));
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 1));
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Listening);
}

TEST(server_stop_playback) {
  Session session = speakingSession();
  session.onServerCommand(server(ServerCommandType::StopPlayback));
  CHECK(sameActions(drain(session), {simple(ActionType::StopPlayback)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(volume_and_tone_any_state) {
  Session session = listeningSession();
  ServerCommand volume = server(ServerCommandType::Volume);
  volume.volume = 0.3f;
  session.onServerCommand(volume);
  Expect expectVolume{ActionType::SetVolume};
  expectVolume.volume = 0.3f;
  CHECK(sameActions(drain(session), {expectVolume}));

  ServerCommand tone = server(ServerCommandType::PlayTone);
  tone.tone = Tone::Thinking;
  session.onServerCommand(tone);
  CHECK(sameActions(drain(session), {playTone(Tone::Thinking)}));
  CHECK(session.state() == SessionState::Listening);
}

TEST(connection_lost_mid_turn) {
  Session listening = listeningSession();
  listening.setConnected(false);
  CHECK(sameActions(drain(listening), {simple(ActionType::StopCapture), playTone(Tone::Error), setActiveTurn(0)}));
  CHECK(listening.state() == SessionState::Idle);

  Session speaking = speakingSession();
  speaking.setConnected(false);
  CHECK(sameActions(drain(speaking), {simple(ActionType::StopPlayback), playTone(Tone::Error), setActiveTurn(0)}));
  CHECK(speaking.state() == SessionState::Idle);
}

// Ревью №7: после таймаута ожидания ответ на брошенный ход не должен играть.
TEST(late_reply_after_timeout_ignored) {
  Session session = waitingSession(1000);
  session.loop(1000 + 15000);
  drain(session);
  session.onServerCommand(server(ServerCommandType::ReplyStart, 1));
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 1));
  session.loop(1000 + 16000);
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Idle);
}

TEST(wake_event_carries_level) {
  Session session = connectedSession();
  session.onVoiceEvent(VoiceEvent{VoiceEventType::WakeWord, -28.0f});
  std::vector<Action> actions = drain(session);
  bool found = false;
  for (const Action& a : actions) {
    if (a.type == ActionType::SendEvent) {
      CHECK(a.event.type == ClientEventType::Wake);
      CHECK(a.event.level == -28.0f);
      found = true;
    }
  }
  CHECK(found);
}

TEST(cancel_turn_in_listening) {
  Session session = listeningSession();
  session.onServerCommand(server(ServerCommandType::CancelTurn, 1));
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture), setActiveTurn(0)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(cancel_turn_in_speaking) {
  Session session = speakingSession();
  session.onServerCommand(server(ServerCommandType::CancelTurn, 1));
  CHECK(sameActions(drain(session), {simple(ActionType::StopPlayback), setActiveTurn(0)}));
  CHECK(session.state() == SessionState::Idle);
  session.setPlaybackActive(false);
  CHECK(drain(session).empty());
}

TEST(cancel_turn_in_waiting) {
  Session session = waitingSession();
  session.onServerCommand(server(ServerCommandType::CancelTurn, 1));
  CHECK(sameActions(drain(session), {setActiveTurn(0)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(cancel_turn_other_turn_ignored) {
  Session session = waitingSession();
  session.onServerCommand(server(ServerCommandType::CancelTurn, 99));
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Waiting);
}

TEST(announce_from_idle) {
  Session session = connectedSession();
  session.onServerCommand(server(ServerCommandType::Announce, 0x80000001u));
  CHECK(sameActions(drain(session), {setActiveTurn(0x80000001u)}));
  CHECK(session.state() == SessionState::Waiting);
  session.onServerCommand(server(ServerCommandType::ReplyStart, 0x80000001u));
  CHECK(session.state() == SessionState::Speaking);
  session.setPlaybackActive(true);
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 0x80000001u));
  session.setPlaybackActive(false);
  CHECK(sameActions(drain(session), {sendEvent(ClientEventType::PlaybackDone, 0x80000001u)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(announce_when_busy_sends_busy) {
  Session session = listeningSession();
  session.onServerCommand(server(ServerCommandType::Announce, 0x80000001u));
  CHECK(sameActions(drain(session), {sendEvent(ClientEventType::Busy, 0x80000001u)}));
  CHECK(session.state() == SessionState::Listening);
}

TEST(listen_from_idle) {
  Session session = connectedSession();
  session.onServerCommand(server(ServerCommandType::Listen, 0x80000001u));
  CHECK(sameActions(drain(session), {setActiveTurn(0x80000001u), playTone(Tone::Listen),
                                     simple(ActionType::StartCapture)}));
  CHECK(session.state() == SessionState::Listening);
  CHECK_EQ(session.turn(), 0x80000001u);
}

TEST(listen_then_speech) {
  Session session = connectedSession();
  session.onServerCommand(server(ServerCommandType::Listen, 0x80000001u));
  drain(session);
  session.onVoiceEvent(voice(VoiceEventType::SpeechStart));
  session.onVoiceEvent(voice(VoiceEventType::SpeechEnd));
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture),
                                     sendEvent(ClientEventType::UtteranceEnd, 0x80000001u, UtteranceEndReason::Vad)}));
  CHECK(session.state() == SessionState::Waiting);
}

TEST(listen_no_speech) {
  Session session = connectedSession(1000);
  session.onServerCommand(server(ServerCommandType::Listen, 0x80000001u));
  drain(session);
  session.loop(1000 + 5000);
  CHECK(sameActions(drain(session), {simple(ActionType::StopCapture),
                                     sendEvent(ClientEventType::UtteranceEnd, 0x80000001u, UtteranceEndReason::NoSpeech),
                                     setActiveTurn(0)}));
  CHECK(session.state() == SessionState::Idle);
}

TEST(listen_when_busy_sends_busy) {
  Session session = speakingSession();
  session.onServerCommand(server(ServerCommandType::Listen, 0x80000002u));
  CHECK(sameActions(drain(session), {sendEvent(ClientEventType::Busy, 0x80000002u)}));
  CHECK(session.state() == SessionState::Speaking);
  CHECK_EQ(session.turn(), 1u);
}

TEST(listen_when_disconnected_ignored) {
  Session session;
  session.begin(SessionConfig{});
  session.onServerCommand(server(ServerCommandType::Listen, 0x80000001u));
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Idle);
}

TEST(wake_after_listen_turn_uses_local_counter) {
  Session session = connectedSession();
  session.onServerCommand(server(ServerCommandType::Listen, 0x80000001u));
  session.onVoiceEvent(voice(VoiceEventType::SpeechStart));
  session.onVoiceEvent(voice(VoiceEventType::SpeechEnd));
  session.onServerCommand(server(ServerCommandType::ReplyStart, 0x80000001u));
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 0x80000001u));
  session.loop(3000);
  drain(session);
  CHECK(session.state() == SessionState::Idle);
  session.onVoiceEvent(voice(VoiceEventType::WakeWord));
  CHECK(sameActions(drain(session), {playTone(Tone::Wake), setActiveTurn(1), sendEvent(ClientEventType::Wake, 1),
                                     simple(ActionType::StartCapture)}));
}

TEST(announce_when_disconnected_ignored) {
  Session session;
  session.begin(SessionConfig{});
  session.onServerCommand(server(ServerCommandType::Announce, 0x80000001u));
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Idle);
}

TEST(wake_after_announce_uses_local_counter) {
  Session session = speakingSession();
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 1));
  session.loop(2000);
  drain(session);
  CHECK(session.state() == SessionState::Idle);
  session.onServerCommand(server(ServerCommandType::Announce, 0x80000001u));
  session.onServerCommand(server(ServerCommandType::ReplyStart, 0x80000001u));
  session.onServerCommand(server(ServerCommandType::ReplyEnd, 0x80000001u));
  session.loop(3000);
  drain(session);
  CHECK(session.state() == SessionState::Idle);
  session.onVoiceEvent(voice(VoiceEventType::WakeWord));
  CHECK(sameActions(drain(session), {playTone(Tone::Wake), setActiveTurn(2), sendEvent(ClientEventType::Wake, 2),
                                     simple(ActionType::StartCapture)}));
}

TEST(thinking_extends_waiting) {
  Session session = waitingSession(1000);  // Waiting с t=1000
  session.loop(1000 + 14000);
  ServerCommand thinking = server(ServerCommandType::PlayTone);
  thinking.tone = Tone::Thinking;
  session.onServerCommand(thinking);
  drain(session);
  session.loop(1000 + 28000);
  CHECK(drain(session).empty());
  CHECK(session.state() == SessionState::Waiting);
  session.loop(1000 + 29100);
  CHECK(sameActions(drain(session), {playTone(Tone::Error), setActiveTurn(0)}));
}
