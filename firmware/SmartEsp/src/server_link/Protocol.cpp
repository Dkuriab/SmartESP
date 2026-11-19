#include "Protocol.h"

#include <ArduinoJson.h>
#include <math.h>
#include <string.h>

namespace {

constexpr int SAMPLE_RATE = 16000;
constexpr int PROTOCOL_VERSION = 3;

const char* eventTypeName(ClientEventType type) {
  switch (type) {
    case ClientEventType::Wake: return "wake";
    case ClientEventType::UtteranceEnd: return "utterance_end";
    case ClientEventType::BargeIn: return "barge_in";
    case ClientEventType::PlaybackDone: return "playback_done";
    case ClientEventType::Busy: return "busy";
  }
  return "";
}

const char* reasonName(UtteranceEndReason reason) {
  switch (reason) {
    case UtteranceEndReason::Vad: return "vad";
    case UtteranceEndReason::Timeout: return "timeout";
    case UtteranceEndReason::Server: return "server";
    case UtteranceEndReason::NoSpeech: return "no_speech";
  }
  return "";
}

// Пишет JSON в out, только если он помещается целиком (с нулём на конце).
size_t serializeInto(const JsonDocument& doc, char* out, size_t capacity) {
  if (measureJson(doc) + 1 > capacity) {
    return 0;
  }
  return serializeJson(doc, out, capacity);
}

bool readTurn(const JsonDocument& doc, uint32_t& turn) {
  JsonVariantConst value = doc["turn"];
  if (!value.is<uint32_t>()) {
    return false;
  }
  turn = value.as<uint32_t>();
  return true;
}

bool readTone(const char* name, Tone& tone) {
  if (strcmp(name, "wake") == 0) {
    tone = Tone::Wake;
  } else if (strcmp(name, "error") == 0) {
    tone = Tone::Error;
  } else if (strcmp(name, "thinking") == 0) {
    tone = Tone::Thinking;
  } else if (strcmp(name, "listen") == 0) {
    tone = Tone::Listen;
  } else if (strcmp(name, "attention") == 0) {
    tone = Tone::Attention;
  } else {
    return false;
  }
  return true;
}

}  // namespace

size_t encodeHello(const char* fwVersion, const char* deviceId, char* out, size_t capacity) {
  JsonDocument doc;
  doc["type"] = "hello";
  doc["fw"] = fwVersion;
  doc["device_id"] = deviceId;
  doc["protocol"] = PROTOCOL_VERSION;
  doc["sample_rate"] = SAMPLE_RATE;
  doc["format"] = "pcm_s16le";
  doc["channels"] = 1;
  return serializeInto(doc, out, capacity);
}

size_t encodeClientEvent(const ClientEvent& event, char* out, size_t capacity) {
  JsonDocument doc;
  doc["type"] = eventTypeName(event.type);
  doc["turn"] = event.turn;
  if (event.type == ClientEventType::UtteranceEnd) {
    doc["reason"] = reasonName(event.reason);
  }
  if (event.type == ClientEventType::Wake) {
    doc["level"] = roundf(event.level * 10.0f) / 10.0f;  // дБFS, одна цифра после запятой
  }
  return serializeInto(doc, out, capacity);
}

bool decodeServerCommand(const char* json, size_t length, ServerCommand& out) {
  JsonDocument doc;
  if (deserializeJson(doc, json, length) || !doc.is<JsonObject>()) {
    return false;
  }
  const char* type = doc["type"] | static_cast<const char*>(nullptr);
  if (!type) {
    return false;
  }

  ServerCommand cmd{};
  if (strcmp(type, "stop_listening") == 0) {
    cmd.type = ServerCommandType::StopListening;
    if (!readTurn(doc, cmd.turn)) return false;
  } else if (strcmp(type, "reply_start") == 0) {
    cmd.type = ServerCommandType::ReplyStart;
    if (!readTurn(doc, cmd.turn)) return false;
  } else if (strcmp(type, "reply_end") == 0) {
    cmd.type = ServerCommandType::ReplyEnd;
    if (!readTurn(doc, cmd.turn)) return false;
  } else if (strcmp(type, "cancel_turn") == 0) {
    cmd.type = ServerCommandType::CancelTurn;
    if (!readTurn(doc, cmd.turn)) return false;
  } else if (strcmp(type, "announce") == 0) {
    cmd.type = ServerCommandType::Announce;
    if (!readTurn(doc, cmd.turn)) return false;
  } else if (strcmp(type, "listen") == 0) {
    cmd.type = ServerCommandType::Listen;
    if (!readTurn(doc, cmd.turn)) return false;
  } else if (strcmp(type, "stop_playback") == 0) {
    cmd.type = ServerCommandType::StopPlayback;
  } else if (strcmp(type, "volume") == 0) {
    cmd.type = ServerCommandType::Volume;
    JsonVariantConst value = doc["value"];
    if (!value.is<float>()) return false;
    const float volume = value.as<float>();
    cmd.volume = volume < 0.0f ? 0.0f : (volume > 1.0f ? 1.0f : volume);
  } else if (strcmp(type, "tone") == 0) {
    cmd.type = ServerCommandType::PlayTone;
    const char* name = doc["name"] | static_cast<const char*>(nullptr);
    if (!name || !readTone(name, cmd.tone)) return false;
  } else {
    return false;
  }

  out = cmd;
  return true;
}
