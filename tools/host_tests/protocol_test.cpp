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
  const size_t length = encodeHello("0.1.0", "AA:BB", buffer, sizeof(buffer));
  CHECK(length > 0);
  JsonDocument doc;
  CHECK(!deserializeJson(doc, buffer, length));
  CHECK_EQ(std::string(doc["type"] | ""), "hello");
  CHECK_EQ(std::string(doc["fw"] | ""), "0.1.0");
  CHECK_EQ(doc["sample_rate"].as<int>(), 16000);
  CHECK_EQ(std::string(doc["format"] | ""), "pcm_s16le");
  CHECK_EQ(doc["channels"].as<int>(), 1);
  CHECK_EQ(doc["protocol"].as<int>(), 5);  // 4: обновление по воздуху; 5: потоки звука
}

TEST(encode_update_status) {
  ClientEvent event{};
  event.type = ClientEventType::UpdateStatus;
  event.updateKind = UpdateKind::Model;
  event.updateState = UpdateState::Failed;
  event.updateError = UpdateError::Hash;
  event.bytes = 1000;
  event.total = 62304;
  const JsonDocument doc = encodeAndParse(event);
  CHECK_EQ(std::string(doc["type"] | ""), "update_status");
  CHECK_EQ(std::string(doc["what"] | ""), "model");
  CHECK_EQ(std::string(doc["state"] | ""), "failed");
  CHECK_EQ(std::string(doc["error"] | ""), "hash");
  CHECK_EQ(doc["done"].as<int>(), 1000);
  CHECK_EQ(doc["total"].as<int>(), 62304);
  CHECK(doc["turn"].isNull());
}

TEST(decode_update_firmware_and_model) {
  const std::string sha(64, 'a');
  ServerCommand cmd{};
  const std::string firmware = R"({"type":"update","what":"firmware","path":"/device/files/x","size":2900000,"sha256":")" + sha + "\"}";
  CHECK(decode(firmware.c_str(), cmd));
  CHECK(cmd.type == ServerCommandType::Update);
  CHECK(cmd.update.kind == UpdateKind::Firmware);
  CHECK_EQ(cmd.update.size, 2900000u);
  CHECK_EQ(std::string(cmd.update.path), "/device/files/x");
  CHECK_EQ(std::string(cmd.update.sha256), sha);
  const std::string model = R"({"type":"update","what":"model","path":"/f","size":62304,"sha256":")" + sha +
                            R"(","cutoff":0.9,"window":5,"arena":30000,"word":"Кузя"})";
  CHECK(decode(model.c_str(), cmd));
  CHECK(cmd.update.kind == UpdateKind::Model);
  CHECK_EQ(cmd.update.window, 5);
  CHECK_EQ(cmd.update.arena, 30000u);
  CHECK_EQ(std::string(cmd.update.word), "Кузя");
  CHECK(cmd.update.cutoff > 0.89f && cmd.update.cutoff < 0.91f);
}

TEST(decode_update_rejects_bad) {
  const std::string sha(64, 'a');
  ServerCommand cmd{};
  const std::string head = R"({"type":"update","what":"model","path":"/f","size":10,"sha256":")";
  CHECK(!decode((head + sha + R"(","cutoff":0.9,"window":5})").c_str(), cmd));  // нет arena
  CHECK(!decode((head + sha + R"(","cutoff":1.5,"window":5,"arena":1})").c_str(), cmd));
  CHECK(!decode((head + "xyz" + R"(","cutoff":0.9,"window":5,"arena":1})").c_str(), cmd));  // не SHA-256
  CHECK(!decode(R"({"type":"update","what":"rom","path":"/f","size":10,"sha256":"a"})", cmd));
  const std::string relative = R"({"type":"update","what":"firmware","path":"http://evil","size":10,"sha256":")" + sha + "\"}";
  CHECK(!decode(relative.c_str(), cmd));  // только путь на сервере ядра
}

TEST(encode_wake) {
  JsonDocument doc = encodeAndParse({ClientEventType::Wake, 3, UtteranceEndReason::Vad, 0.0f});
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

TEST(encode_played) {
  ClientEvent event{ClientEventType::Played, 0x80000001u, UtteranceEndReason::Vad, 0.0f, 0xFFFFFFF0u};
  JsonDocument doc = encodeAndParse(event);
  CHECK_EQ(std::string(doc["type"] | ""), "played");
  CHECK_EQ(doc["turn"].as<uint32_t>(), 0x80000001u);
  CHECK_EQ(doc["bytes"].as<uint32_t>(), 0xFFFFFFF0u);
  CHECK(doc["reason"].isNull());
  CHECK(doc["level"].isNull());
}

TEST(bytes_only_in_played) {
  ClientEvent event{ClientEventType::PlaybackDone, 2, UtteranceEndReason::Vad, 0.0f, 640};
  JsonDocument doc = encodeAndParse(event);
  CHECK_EQ(std::string(doc["type"] | ""), "playback_done");
  CHECK(doc["bytes"].isNull());
}

TEST(encode_playback_done) {
  JsonDocument doc = encodeAndParse({ClientEventType::PlaybackDone, 5, UtteranceEndReason::Vad});
  CHECK_EQ(std::string(doc["type"] | ""), "playback_done");
  CHECK_EQ(doc["turn"].as<int>(), 5);
}

TEST(encode_too_small_buffer) {
  char buffer[8];
  CHECK_EQ(encodeClientEvent({ClientEventType::Wake, 1, UtteranceEndReason::Vad}, buffer, sizeof(buffer)), 0u);
  CHECK_EQ(encodeHello("0.1.0", "AA:BB", buffer, sizeof(buffer)), 0u);
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

// Объявление ядра: announce, reply_start и звук приходят раньше, чем loop() выдаст
// SetActiveTurn, — свободная колонка (текущий ход 0) принимает ход объявления сразу.
TEST(gate_free_speaker_adopts_announce) {
  ReplyGate gate;
  gate.setActiveTurn(0);
  gate.onCommand(command(ServerCommandType::Announce, 0x80000001u));
  CHECK(!gate.isOpen());
  gate.onCommand(command(ServerCommandType::ReplyStart, 0x80000001u));
  CHECK(gate.isOpen());
  gate.setActiveTurn(0x80000001u);  // session согласилась позже — шлюз остаётся открытым
  CHECK(gate.isOpen());
}

// Занятая колонка: звук объявления, отправленный до ответа busy, не принимается.
TEST(gate_busy_speaker_drops_announce_audio) {
  ReplyGate gate;
  gate.setActiveTurn(2);  // идёт свой ход владельца, его ответ ещё не начался
  gate.onCommand(command(ServerCommandType::Announce, 0x80000001u));
  gate.onCommand(command(ServerCommandType::ReplyStart, 0x80000001u));
  CHECK(!gate.isOpen());
  gate.onCommand(command(ServerCommandType::ReplyEnd, 0x80000001u));
  gate.onCommand(command(ServerCommandType::ReplyStart, 2));  // ответ владельцу — как обычно
  CHECK(gate.isOpen());
}

// ---------- протокол v2 ----------

TEST(hello_has_device_id_and_protocol) {
  char buffer[192];
  const size_t length = encodeHello("0.2.0", "AA:BB:CC:DD:EE:FF", buffer, 192);
  CHECK(length > 0);
  const std::string json(buffer, length);
  CHECK(json.find("\"device_id\":\"AA:BB:CC:DD:EE:FF\"") != std::string::npos);
  CHECK(json.find("\"protocol\":5") != std::string::npos);
  JsonDocument doc;
  CHECK(!deserializeJson(doc, buffer, length));
  CHECK_EQ(std::string(doc["type"] | ""), "hello");
  CHECK_EQ(std::string(doc["fw"] | ""), "0.2.0");
  CHECK_EQ(doc["sample_rate"].as<int>(), 16000);
  CHECK_EQ(std::string(doc["format"] | ""), "pcm_s16le");
  CHECK_EQ(doc["channels"].as<int>(), 1);
}

TEST(wake_has_level) {
  char buffer[128];
  const ClientEvent wake{ClientEventType::Wake, 3, UtteranceEndReason::Vad, -31.25f};
  const size_t length = encodeClientEvent(wake, buffer, sizeof(buffer));
  CHECK_EQ(std::string(buffer, length), "{\"type\":\"wake\",\"turn\":3,\"level\":-31.3}");
}

TEST(non_wake_events_have_no_level) {
  const ClientEventType types[] = {ClientEventType::UtteranceEnd, ClientEventType::BargeIn,
                                   ClientEventType::PlaybackDone};
  for (const ClientEventType type : types) {
    JsonDocument doc = encodeAndParse({type, 3, UtteranceEndReason::Vad, -20.0f});
    CHECK(doc["level"].isNull());
  }
}

TEST(decode_cancel_turn) {
  ServerCommand cmd{};
  CHECK(decode("{\"type\":\"cancel_turn\",\"turn\":7}", cmd));
  CHECK(cmd.type == ServerCommandType::CancelTurn);
  CHECK_EQ(cmd.turn, 7u);
  CHECK(!decode("{\"type\":\"cancel_turn\"}", cmd));
}

TEST(decode_announce) {
  ServerCommand cmd{};
  CHECK(decode("{\"type\":\"announce\",\"turn\":2147483649}", cmd));
  CHECK(cmd.type == ServerCommandType::Announce);
  CHECK_EQ(cmd.turn, 0x80000001u);
  CHECK(!decode("{\"type\":\"announce\"}", cmd));
}

// ---------- протокол v3 ----------

TEST(hello_protocol_5) {
  char buffer[192];
  const size_t length = encodeHello("0.3.0", "AA:BB", buffer, sizeof(buffer));
  CHECK(length > 0);
  JsonDocument doc;
  CHECK(!deserializeJson(doc, buffer, length));
  CHECK_EQ(doc["protocol"].as<int>(), 5);
}

TEST(decode_listen) {
  ServerCommand cmd{};
  CHECK(decode("{\"type\":\"listen\",\"turn\":2147483650}", cmd));
  CHECK(cmd.type == ServerCommandType::Listen);
  CHECK_EQ(cmd.turn, 0x80000002u);
  CHECK(!decode("{\"type\":\"listen\"}", cmd));
}

TEST(encode_busy) {
  char buffer[128];
  const size_t length = encodeClientEvent({ClientEventType::Busy, 7, UtteranceEndReason::Vad, 0.0f}, buffer, sizeof(buffer));
  CHECK_EQ(std::string(buffer, length), "{\"type\":\"busy\",\"turn\":7}");
}

TEST(decode_tone_listen_attention) {
  ServerCommand cmd{};
  CHECK(decode(R"({"type":"tone","name":"listen"})", cmd));
  CHECK(cmd.type == ServerCommandType::PlayTone);
  CHECK(cmd.tone == Tone::Listen);
  CHECK(decode(R"({"type":"tone","name":"attention"})", cmd));
  CHECK(cmd.tone == Tone::Attention);
}
