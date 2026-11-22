#include "EchoMessages.h"

#include <math.h>
#include <string.h>

namespace {

constexpr uint32_t MAX_DELAY_MS = 300;

const char* echoStateName(EchoState state) {
  switch (state) {
    case EchoState::Current: return "current";
    case EchoState::Running: return "running";
    case EchoState::Done: return "done";
    case EchoState::Failed: return "failed";
  }
  return "";
}

const char* echoErrorName(EchoError error) {
  switch (error) {
    case EchoError::None: return "";
    case EchoError::Busy: return "busy";
    case EchoError::Quiet: return "quiet";
    case EchoError::Weak: return "weak";
  }
  return "";
}

}  // namespace

void addHelloExtras(JsonDocument& doc) {
  doc["caps"].add("echo");
  JsonArray rates = doc["stream_rates"].to<JsonArray>();
  for (uint32_t rate : STREAM_RATES) rates.add(rate);
}

void encodeEchoStatus(const ClientEvent& event, JsonDocument& doc) {
  doc.remove("turn");
  doc["state"] = echoStateName(event.echoState);
  doc["delay_ms"] = event.delayMs;
  doc["previous_ms"] = event.previousMs;
  doc["confidence"] = roundf(event.confidence * 100.0f) / 100.0f;
  doc["error"] = echoErrorName(event.echoError);
}

bool decodeEchoCommand(const char* type, const JsonDocument& doc, ServerCommand& out) {
  if (strcmp(type, "echo_calibrate") == 0) {
    out.type = ServerCommandType::EchoCalibrate;
    return true;
  }
  if (strcmp(type, "echo_delay") != 0) {
    return false;
  }
  JsonVariantConst delay = doc["delay_ms"];
  if (!delay.is<uint32_t>() || delay.as<uint32_t>() > MAX_DELAY_MS) {
    return false;
  }
  out.type = ServerCommandType::EchoDelay;
  out.delayMs = static_cast<uint16_t>(delay.as<uint32_t>());
  return true;
}
