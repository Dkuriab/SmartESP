#include "Protocol.h"

#include <ArduinoJson.h>
#include <math.h>
#include <string.h>

namespace {

constexpr int SAMPLE_RATE = 16000;
constexpr int PROTOCOL_VERSION = 4;  // 4: команда update и событие update_status; звуки — возможность sounds

const char* eventTypeName(ClientEventType type) {
  switch (type) {
    case ClientEventType::Wake: return "wake";
    case ClientEventType::UtteranceEnd: return "utterance_end";
    case ClientEventType::BargeIn: return "barge_in";
    case ClientEventType::PlaybackDone: return "playback_done";
    case ClientEventType::Busy: return "busy";
    case ClientEventType::Played: return "played";
    case ClientEventType::UpdateStatus: return "update_status";
  }
  return "";
}

const char* updateKindName(UpdateKind kind) {
  switch (kind) {
    case UpdateKind::Firmware: return "firmware";
    case UpdateKind::Model: return "model";
    case UpdateKind::Sound: return "sound";
  }
  return "";
}

// Имена сигналов по порядку Tone (для hello и update_status).
const char* const TONE_NAMES[TONE_COUNT] = {"wake", "error", "thinking", "listen", "attention"};

const char* toneName(Tone tone) {
  const size_t index = static_cast<size_t>(tone);
  return index < TONE_COUNT ? TONE_NAMES[index] : "";
}

const char* updateStateName(UpdateState state) {
  switch (state) {
    case UpdateState::Progress: return "progress";
    case UpdateState::Done: return "done";
    case UpdateState::Failed: return "failed";
  }
  return "";
}

const char* updateErrorName(UpdateError error) {
  switch (error) {
    case UpdateError::None: return "";
    case UpdateError::Busy: return "busy";
    case UpdateError::Download: return "download";
    case UpdateError::Size: return "size";
    case UpdateError::Hash: return "hash";
    case UpdateError::Write: return "write";
    case UpdateError::Storage: return "storage";
  }
  return "";
}

// Строка из JSON в буфер (с нулём); нет, не строка или длиннее буфера — false.
bool readText(const JsonDocument& doc, const char* key, char* out, size_t capacity) {
  const char* value = doc[key] | static_cast<const char*>(nullptr);
  if (!value || strlen(value) + 1 > capacity) {
    return false;
  }
  strcpy(out, value);
  return true;
}

bool isHex64(const char* text) {
  if (strlen(text) != 64) return false;
  for (const char* p = text; *p; ++p) {
    const bool hex = (*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f');
    if (!hex) return false;
  }
  return true;
}

bool readTone(const char* name, Tone& tone) {
  for (size_t i = 0; i < TONE_COUNT; ++i) {
    if (strcmp(name, TONE_NAMES[i]) == 0) {
      tone = static_cast<Tone>(i);
      return true;
    }
  }
  return false;
}

// Команда update: что, путь к файлу, размер, SHA-256; для модели — порог, окно, арена, слово.
bool readUpdate(const JsonDocument& doc, UpdateRequest& out) {
  const char* what = doc["what"] | "";
  if (strcmp(what, "firmware") == 0) {
    out.kind = UpdateKind::Firmware;
  } else if (strcmp(what, "model") == 0) {
    out.kind = UpdateKind::Model;
  } else if (strcmp(what, "sound") == 0) {
    out.kind = UpdateKind::Sound;
    const char* tone = doc["tone"] | "";
    if (!readTone(tone, out.tone)) return false;
  } else {
    return false;
  }
  JsonVariantConst size = doc["size"];
  if (!size.is<uint32_t>()) return false;
  out.size = size.as<uint32_t>();
  if (out.size == 0) return out.kind == UpdateKind::Sound;  // звук без файла — вернуть встроенный
  if (!readText(doc, "path", out.path, sizeof(out.path)) || out.path[0] != '/') return false;
  if (!readText(doc, "sha256", out.sha256, sizeof(out.sha256)) || !isHex64(out.sha256)) return false;
  if (out.kind != UpdateKind::Model) return true;
  JsonVariantConst cutoff = doc["cutoff"];
  JsonVariantConst window = doc["window"];
  JsonVariantConst arena = doc["arena"];
  if (!cutoff.is<float>() || !window.is<uint8_t>() || !arena.is<uint32_t>()) return false;
  out.cutoff = cutoff.as<float>();
  out.window = window.as<uint8_t>();
  out.arena = arena.as<uint32_t>();
  if (out.cutoff <= 0.0f || out.cutoff >= 1.0f || out.window == 0 || out.window > 32 || out.arena == 0) return false;
  if (!readText(doc, "word", out.word, sizeof(out.word))) out.word[0] = '\0';
  return true;
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

}  // namespace

size_t encodeHello(const char* fwVersion, const char* deviceId, char* out, size_t capacity,
                   const char (*sounds)[65]) {
  JsonDocument doc;
  doc["type"] = "hello";
  doc["fw"] = fwVersion;
  doc["device_id"] = deviceId;
  doc["protocol"] = PROTOCOL_VERSION;
  doc["sample_rate"] = SAMPLE_RATE;
  doc["format"] = "pcm_s16le";
  doc["channels"] = 1;
  doc["caps"].add("sounds");
  JsonObject stored = doc["sounds"].to<JsonObject>();
  for (size_t i = 0; sounds && i < TONE_COUNT; ++i) {
    if (sounds[i][0] != '\0') stored[TONE_NAMES[i]] = sounds[i];
  }
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
  if (event.type == ClientEventType::Played) {
    doc["bytes"] = event.bytes;
  }
  if (event.type == ClientEventType::UpdateStatus) {
    doc.remove("turn");
    doc["what"] = updateKindName(event.updateKind);
    doc["state"] = updateStateName(event.updateState);
    doc["done"] = event.bytes;
    doc["total"] = event.total;
    doc["error"] = updateErrorName(event.updateError);
    if (event.updateKind == UpdateKind::Sound) doc["tone"] = toneName(event.updateTone);
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
  } else if (strcmp(type, "update") == 0) {
    cmd.type = ServerCommandType::Update;
    if (!readUpdate(doc, cmd.update)) return false;
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
