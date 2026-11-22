// Тесты потока звука (протокол 5): команды stream_*, событие stream_status и приглушение Ducker.

#include <ArduinoJson.h>
#include <cstring>
#include <string>

#include "server_link/Protocol.h"
#include "stream_player/Ducker.h"
#include "test.h"

namespace {

bool decodeStream(const char* json, ServerCommand& out) {
  return decodeServerCommand(json, std::strlen(json), out);
}

}  // namespace

TEST(decode_stream_start) {
  ServerCommand cmd{};
  CHECK(decodeStream("{\"type\":\"stream_start\",\"stream\":7,\"path\":\"/device/stream/abc\","
                     "\"rate\":16000,\"volume\":0.6,\"live\":true}",
                     cmd));
  CHECK(cmd.type == ServerCommandType::StreamStart);
  CHECK_EQ(cmd.stream.id, 7u);
  CHECK_EQ(cmd.stream.rate, 16000u);
  CHECK(cmd.stream.volume > 0.59f && cmd.stream.volume < 0.61f);
  CHECK(cmd.stream.live);
  CHECK_EQ(std::string(cmd.stream.path), "/device/stream/abc");
}

TEST(decode_stream_start_defaults_and_clamps) {
  ServerCommand cmd{};
  CHECK(decodeStream("{\"type\":\"stream_start\",\"stream\":1,\"path\":\"/p\",\"rate\":48000}", cmd));
  CHECK(cmd.stream.volume == 1.0f);
  CHECK(!cmd.stream.live);
  CHECK_EQ(cmd.stream.rate, 48000u);  // частоту проверяет stream_player (failed/rate)
  CHECK(decodeStream("{\"type\":\"stream_start\",\"stream\":1,\"path\":\"/p\",\"rate\":16000,\"volume\":7}", cmd));
  CHECK(cmd.stream.volume == 1.0f);
}

TEST(decode_stream_start_rejects_bad) {
  ServerCommand cmd{};
  CHECK(!decodeStream("{\"type\":\"stream_start\",\"path\":\"/p\",\"rate\":16000}", cmd));             // нет номера
  CHECK(!decodeStream("{\"type\":\"stream_start\",\"stream\":0,\"path\":\"/p\",\"rate\":16000}", cmd));  // 0
  CHECK(!decodeStream("{\"type\":\"stream_start\",\"stream\":1,\"path\":\"p\",\"rate\":16000}", cmd));   // путь
  CHECK(!decodeStream("{\"type\":\"stream_start\",\"stream\":1,\"path\":\"/p\"}", cmd));               // частота
  const std::string longPath(120, 'a');
  const std::string json = "{\"type\":\"stream_start\",\"stream\":1,\"rate\":16000,\"path\":\"/" + longPath + "\"}";
  CHECK(!decodeServerCommand(json.c_str(), json.size(), cmd));
}

TEST(decode_stream_stop_and_volume) {
  ServerCommand cmd{};
  CHECK(decodeStream("{\"type\":\"stream_stop\",\"stream\":9}", cmd));
  CHECK(cmd.type == ServerCommandType::StreamStop);
  CHECK_EQ(cmd.turn, 9u);
  CHECK(decodeStream("{\"type\":\"stream_stop\"}", cmd));
  CHECK_EQ(cmd.turn, 0u);  // любой
  CHECK(decodeStream("{\"type\":\"stream_volume\",\"value\":1.5}", cmd));
  CHECK(cmd.type == ServerCommandType::StreamVolume);
  CHECK(cmd.volume == 1.0f);
  CHECK(!decodeStream("{\"type\":\"stream_volume\"}", cmd));
}

TEST(encode_stream_status) {
  ClientEvent event{};
  event.type = ClientEventType::StreamStatus;
  event.turn = 7;
  event.bytes = 96000;
  event.streamState = StreamState::Failed;
  event.streamError = StreamError::Download;
  char buffer[192];
  const size_t length = encodeClientEvent(event, buffer, sizeof(buffer));
  JsonDocument doc;
  CHECK(length > 0 && !deserializeJson(doc, buffer, length));
  CHECK_EQ(std::string(doc["type"] | ""), "stream_status");
  CHECK_EQ(doc["stream"].as<int>(), 7);
  CHECK_EQ(std::string(doc["state"] | ""), "failed");
  CHECK_EQ(doc["played"].as<int>(), 96000);
  CHECK_EQ(std::string(doc["error"] | "?"), "download");
  CHECK(!doc["turn"].is<int>());
  event.streamState = StreamState::Playing;
  event.streamError = StreamError::None;
  CHECK(encodeClientEvent(event, buffer, sizeof(buffer)) > 0);
  CHECK(std::string(buffer).find("\"state\":\"playing\"") != std::string::npos);
  CHECK(std::string(buffer).find("\"error\":\"\"") != std::string::npos);
}

TEST(ducker_mutes_at_once_and_resumes_after_quiet) {
  Ducker ducker(1500, 4, 8);
  ducker.update(false, 0);
  CHECK(!ducker.muted());
  for (int i = 0; i < 8; i++) ducker.next();
  CHECK(ducker.next() == 1.0f);  // нарос
  ducker.update(true, 100);      // слово: сразу
  CHECK(ducker.muted());
  CHECK(!ducker.silent());       // ещё затухает
  for (int i = 0; i < 4; i++) ducker.next();
  CHECK(ducker.silent());
  ducker.update(false, 5000);    // ответ кончился
  ducker.update(false, 6000);
  CHECK(ducker.muted());         // покой меньше 1,5 с
  ducker.update(true, 6200);     // уточняющий вопрос — снова разговор
  ducker.update(false, 6300);
  ducker.update(false, 7700);
  CHECK(ducker.muted());
  ducker.update(false, 7800);
  CHECK(!ducker.muted());
  const float first = ducker.next();
  CHECK(first > 0.0f && first < 1.0f);  // плавно, без щелчка
}

TEST(ducker_restart_fades_in) {
  Ducker ducker(1500, 4, 4);
  for (int i = 0; i < 4; i++) ducker.next();
  ducker.restart();
  CHECK(ducker.next() < 0.3f);
}
