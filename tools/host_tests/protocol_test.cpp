// Тесты протокола WebSocket (кодирование событий, разбор команд)
// и шлюза звука ответа ReplyGate.

#include <ArduinoJson.h>
#include <cstring>

#include "server_link/Protocol.h"
#include "server_link/ReplyGate.h"
#include "test.h"

namespace {

// Кодирует событие и разбирает результат обратно в JSON для проверок.
JsonDocument encodeAndParse(const ClientEvent& event) {
  char buffer[256];
  const size_t length = encodeClientEvent(event, buffer, sizeof(buffer));
  JsonDocument doc;
  if (length == 0 || deserializeJson(doc, buffer, length)) {
    doc.clear();
  }
  return doc;
}

bool decode(const char* json, ServerCommand& out) {
  return decodeServerCommand(json, std::strlen(json), out);
}

ServerCommand command(ServerCommandType type, uint32_t turn) {
  ServerCommand cmd{};
  cmd.type = type;
  cmd.turn = turn;
  return cmd;
}

}  // namespace

// ---------- кодирование ESP → сервер ----------

TEST(encode_hello) {
  char buffer[256];
  const size_t length = encodeHello("0.1.0", buffer, sizeof(buffer));
  CHECK(length > 0);
  JsonDocument doc;
  CHECK(!deserializeJson(doc, buffer, length));
  CHECK_EQ(std::string(doc["type"] | ""), "hello");
  CHECK_EQ(std::string(doc["fw"] | ""), "0.1.0");
  CHECK_EQ(doc["sample_rate"].as<int>(), 16000);
  CHECK_EQ(std::string(doc["format"] | ""), "pcm_s16le");
  CHECK_EQ(doc["channels"].as<int>(), 1);
}

TEST(encode_wake) {
  JsonDocument doc = encodeAndParse({ClientEventType::Wake, 3, UtteranceEndReason::Vad});
  CHECK_EQ(std::string(doc["type"] | ""), "wake");
  CHECK_EQ(doc["turn"].as<int>(), 3);
}

TEST(encode_utterance_end_reasons) {
  const struct {
    UtteranceEndReason reason;
    const char* text;
  } cases[] = {
      {UtteranceEndReason::Vad, "vad"},
      {UtteranceEndReason::Timeout, "timeout"},
      {UtteranceEndReason::Server, "server"},
      {UtteranceEndReason::NoSpeech, "no_speech"},
  };
  for (const auto& c : cases) {
    JsonDocument doc = encodeAndParse({ClientEventType::UtteranceEnd, 7, c.reason});
    CHECK_EQ(std::string(doc["type"] | ""), "utterance_end");
    CHECK_EQ(doc["turn"].as<int>(), 7);
    CHECK_EQ(std::string(doc["reason"] | ""), c.text);
  }
}

TEST(encode_barge_in) {
  JsonDocument doc = encodeAndParse({ClientEventType::BargeIn, 4, UtteranceEndReason::Vad});
  CHECK_EQ(std::string(doc["type"] | ""), "barge_in");
  CHECK_EQ(doc["turn"].as<int>(), 4);
}

TEST(encode_playback_done) {
  JsonDocument doc = encodeAndParse({ClientEventType::PlaybackDone, 5, UtteranceEndReason::Vad});
  CHECK_EQ(std::string(doc["type"] | ""), "playback_done");
  CHECK_EQ(doc["turn"].as<int>(), 5);
}

TEST(encode_too_small_buffer) {
  char buffer[8];
  CHECK_EQ(encodeClientEvent({ClientEventType::Wake, 1, UtteranceEndReason::Vad}, buffer, sizeof(buffer)), 0u);
  CHECK_EQ(encodeHello("0.1.0", buffer, sizeof(buffer)), 0u);
}

// ---------- разбор сервер → ESP ----------

TEST(decode_reply_start) {
  ServerCommand cmd{};
  CHECK(decode(R"({"type":"reply_start","turn":5})", cmd));
  CHECK(cmd.type == ServerCommandType::ReplyStart);
  CHECK_EQ(cmd.turn, 5u);
}

TEST(decode_stop_listening) {
  ServerCommand cmd{};
  CHECK(decode(R"({"type":"stop_listening","turn":2})", cmd));
  CHECK(cmd.type == ServerCommandType::StopListening);
  CHECK_EQ(cmd.turn, 2u);
}

TEST(decode_reply_end) {
  ServerCommand cmd{};
  CHECK(decode(R"({"type":"reply_end","turn":9})", cmd));
  CHECK(cmd.type == ServerCommandType::ReplyEnd);
  CHECK_EQ(cmd.turn, 9u);
}

TEST(decode_stop_playback) {
  ServerCommand cmd{};
  CHECK(decode(R"({"type":"stop_playback"})", cmd));
  CHECK(cmd.type == ServerCommandType::StopPlayback);
}

TEST(decode_volume) {
  ServerCommand cmd{};
  CHECK(decode(R"({"type":"volume","value":0.25})", cmd));
  CHECK(cmd.type == ServerCommandType::Volume);
  CHECK_EQ(cmd.volume, 0.25f);
  CHECK(decode(R"({"type":"volume","value":1.7})", cmd));
  CHECK_EQ(cmd.volume, 1.0f);
  CHECK(decode(R"({"type":"volume","value":-0.5})", cmd));
  CHECK_EQ(cmd.volume, 0.0f);
}

TEST(decode_tone) {
  ServerCommand cmd{};
  CHECK(decode(R"({"type":"tone","name":"wake"})", cmd));
  CHECK(cmd.type == ServerCommandType::PlayTone);
  CHECK(cmd.tone == Tone::Wake);
  CHECK(decode(R"({"type":"tone","name":"error"})", cmd));
  CHECK(cmd.tone == Tone::Error);
  CHECK(decode(R"({"type":"tone","name":"thinking"})", cmd));
  CHECK(cmd.tone == Tone::Thinking);
}

TEST(decode_rejects_garbage) {
  ServerCommand cmd{};
  CHECK(!decode("not json", cmd));
  CHECK(!decode("", cmd));
  CHECK(!decode(R"({"turn":1})", cmd));
  CHECK(!decode(R"({"type":"dance"})", cmd));
  CHECK(!decode(R"({"type":"reply_start"})", cmd));
  CHECK(!decode(R"({"type":"reply_start","turn":"x"})", cmd));
  CHECK(!decode(R"({"type":"volume"})", cmd));
  CHECK(!decode(R"({"type":"tone","name":"siren"})", cmd));
  CHECK(!decode(R"([1,2,3])", cmd));
}

// ---------- шлюз звука ответа ----------

TEST(gate_opens_on_active_reply_start) {
  ReplyGate gate;
  gate.setActiveTurn(2);
  CHECK(!gate.isOpen());
  gate.onCommand(command(ServerCommandType::ReplyStart, 2));
  CHECK(gate.isOpen());
}

TEST(gate_ignores_other_turn) {
  ReplyGate gate;
  gate.setActiveTurn(2);
  gate.onCommand(command(ServerCommandType::ReplyStart, 1));
  CHECK(!gate.isOpen());
}

TEST(gate_closes_on_reply_end) {
  ReplyGate gate;
  gate.setActiveTurn(2);
  gate.onCommand(command(ServerCommandType::ReplyStart, 2));
  gate.onCommand(command(ServerCommandType::ReplyEnd, 1));  // чужой ход — не закрывает
  CHECK(gate.isOpen());
  gate.onCommand(command(ServerCommandType::ReplyEnd, 2));
  CHECK(!gate.isOpen());
}

TEST(gate_closes_on_stop_playback) {
  ReplyGate gate;
  gate.setActiveTurn(2);
  gate.onCommand(command(ServerCommandType::ReplyStart, 2));
  gate.onCommand(command(ServerCommandType::StopPlayback, 0));
  CHECK(!gate.isOpen());
}

TEST(gate_closes_on_turn_change) {
  ReplyGate gate;
  gate.setActiveTurn(2);
  gate.onCommand(command(ServerCommandType::ReplyStart, 2));
  gate.setActiveTurn(3);
  CHECK(!gate.isOpen());
}
