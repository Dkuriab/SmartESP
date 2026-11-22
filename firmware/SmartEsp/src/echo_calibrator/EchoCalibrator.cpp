#include "EchoCalibrator.h"

#include <Preferences.h>
#include <string.h>
#include "Correlator.h"
#include "esp_heap_caps.h"

namespace {

constexpr uint32_t SAMPLE_RATE = 16000;
constexpr uint32_t PER_MS = SAMPLE_RATE / 1000;
constexpr const char* NVS_SPACE = "echo";
constexpr const char* NVS_KEY = "delay_ms";
constexpr uint32_t FADE_MS = 10;          // края шума
constexpr int16_t ONSET_THRESHOLD = 1000; // шум в образце громче этого — начался
constexpr uint32_t SKIP_MS = 20;          // окно — чуть после начала шума
constexpr uint32_t WINDOW_MS = 1000;      // окно корреляции
constexpr UBaseType_t EVENTS = 4;

}  // namespace

bool EchoCalibrator::begin(const EchoCalibratorConfig& config) {
  config_ = config;
  Preferences prefs;
  delayMs_ = config_.defaultDelayMs;
  if (prefs.begin(NVS_SPACE, true)) {
    delayMs_ = prefs.getUInt(NVS_KEY, config_.defaultDelayMs);
    prefs.end();
  }
  if (delayMs_ > config_.maxDelayMs) delayMs_ = config_.defaultDelayMs;
  events_ = xQueueCreate(EVENTS, sizeof(ClientEvent));
  Serial.printf("echo_calibrator: сдвиг образца %u мс\n", (unsigned)delayMs_);
  return events_ != nullptr;
}

uint32_t EchoCalibrator::delayMs() const {
  return delayMs_;
}

void EchoCalibrator::start() {
  if (phase_ != Idle) {
    post(EchoState::Failed, EchoError::Busy, delayMs_, 0.0f);
    return;
  }
  recordSamples_ = config_.recordMs * PER_MS;
  mic_ = static_cast<int16_t*>(heap_caps_malloc(recordSamples_ * sizeof(int16_t), MALLOC_CAP_SPIRAM));
  ref_ = static_cast<int16_t*>(heap_caps_malloc(recordSamples_ * sizeof(int16_t), MALLOC_CAP_SPIRAM));
  if (!mic_ || !ref_) {
    release();
    post(EchoState::Failed, EchoError::Busy, delayMs_, 0.0f);
    return;
  }
  recorded_ = 0;
  signalSamples_ = config_.signalMs * PER_MS;
  signalPos_ = 0;
  seed_ = 0x5EED1234u;
  startDelayMs_ = delayMs_;
  phase_ = Recording;
  post(EchoState::Running, EchoError::None, delayMs_, 0.0f);
  Serial.println("echo_calibrator: калибровка — шум 1,5 с");
}

void EchoCalibrator::setDelay(uint32_t ms) {
  if (ms > config_.maxDelayMs) ms = config_.maxDelayMs;
  const uint32_t previous = delayMs_;
  store(ms);
  post(EchoState::Current, EchoError::None, previous, 0.0f);
}

void EchoCalibrator::setConnected(bool connected) {
  if (connected && !connected_) {
    post(EchoState::Current, EchoError::None, delayMs_, 0.0f);
  }
  connected_ = connected;
}

void EchoCalibrator::feed(const int16_t* mic, const int16_t* ref, size_t samples) {
  if (phase_ != Recording) {
    return;
  }
  const size_t n = samples < recordSamples_ - recorded_ ? samples : recordSamples_ - recorded_;
  memcpy(mic_ + recorded_, mic, n * sizeof(int16_t));
  memcpy(ref_ + recorded_, ref, n * sizeof(int16_t));
  recorded_ += n;
  if (recorded_ < recordSamples_) {
    return;
  }
  phase_ = Analyzing;
  // Низкий приоритет на ядре 1: AFE и сеть важнее, счёт подождёт.
  if (xTaskCreatePinnedToCore(taskEntry, "echo_cal", 6144, this, 1, nullptr, 1) != pdPASS) {
    resultQuiet_ = false;
    resultConfidence_ = 0.0f;
    phase_ = Finished;
  }
}

size_t EchoCalibrator::readSignal(int16_t* dst, size_t maxSamples) {
  if (phase_ != Recording || signalPos_ >= signalSamples_) {
    return 0;
  }
  size_t n = 0;
  const size_t fade = FADE_MS * PER_MS;
  while (n < maxSamples && signalPos_ < signalSamples_) {
    dst[n++] = testNoise(seed_, signalPos_++, signalSamples_, fade, config_.amplitude);
  }
  return n;
}

bool EchoCalibrator::pollDelay(uint32_t& ms) {
  if (!hasPending_) {
    return false;
  }
  hasPending_ = false;
  ms = pendingDelay_;
  return true;
}

bool EchoCalibrator::pollStatus(ClientEvent& event) {
  return events_ && xQueueReceive(events_, &event, 0) == pdTRUE;
}

void EchoCalibrator::loop(uint32_t nowMs) {
  (void)nowMs;
  if (phase_ == Finished) {
    finish();
  }
}

void EchoCalibrator::taskEntry(void* self) {
  static_cast<EchoCalibrator*>(self)->analyze();
  vTaskDelete(nullptr);
}

// Задача счёта: где в образце начался шум, окно 1 с, сдвиг от −прежнего до +maxLagMs.
void EchoCalibrator::analyze() {
  const size_t onset = findOnset(ref_, recordSamples_, ONSET_THRESHOLD);
  const int minLag = -static_cast<int>(startDelayMs_ * PER_MS);
  const int maxLag = static_cast<int>(config_.maxLagMs * PER_MS);
  size_t start = onset + SKIP_MS * PER_MS;
  if (start < static_cast<size_t>(-minLag)) start = -minLag;
  const size_t need = start + static_cast<size_t>(maxLag);
  resultQuiet_ = onset >= recordSamples_ || need >= recordSamples_;
  if (!resultQuiet_) {
    size_t window = WINDOW_MS * PER_MS;
    if (need + window > recordSamples_) window = recordSamples_ - need;
    const LagEstimate estimate = findLag(mic_, ref_, recordSamples_, start, window, minLag, maxLag);
    resultLag_ = estimate.lag;
    resultConfidence_ = estimate.confidence;
    resultRatio_ = estimate.ratio;
  }
  phase_ = Finished;
}

// Итог в loop(): уверенно — новый сдвиг в NVS и audio_out; иначе прежний и причина.
void EchoCalibrator::finish() {
  release();
  phase_ = Idle;
  if (resultQuiet_) {
    post(EchoState::Failed, EchoError::Quiet, delayMs_, 0.0f);
    return;
  }
  Serial.printf("echo_calibrator: сдвиг эха %d отсчётов, уверенность %.2f, пик ×%.1f\n", resultLag_,
                resultConfidence_, resultRatio_);
  if (resultConfidence_ < config_.minConfidence || resultRatio_ < config_.minRatio) {
    post(EchoState::Failed, EchoError::Weak, delayMs_, resultConfidence_);
    return;
  }
  long delay = static_cast<long>(startDelayMs_) + resultLag_ / static_cast<long>(PER_MS) -
               static_cast<long>(config_.leadMs);
  if (delay < 0) delay = 0;
  if (delay > static_cast<long>(config_.maxDelayMs)) delay = config_.maxDelayMs;
  const uint32_t previous = delayMs_;
  store(static_cast<uint32_t>(delay));
  post(EchoState::Done, EchoError::None, previous, resultConfidence_);
}

void EchoCalibrator::store(uint32_t ms) {
  delayMs_ = ms;
  pendingDelay_ = ms;
  hasPending_ = true;
  Preferences prefs;
  if (prefs.begin(NVS_SPACE, false)) {
    prefs.putUInt(NVS_KEY, ms);
    prefs.end();
  }
}

void EchoCalibrator::post(EchoState state, EchoError error, uint32_t previous, float confidence) {
  ClientEvent event{};
  event.type = ClientEventType::EchoStatus;
  event.echoState = state;
  event.echoError = error;
  event.delayMs = static_cast<uint16_t>(delayMs_);
  event.previousMs = static_cast<uint16_t>(previous);
  event.confidence = confidence;
  if (events_) xQueueSend(events_, &event, 0);
}

void EchoCalibrator::release() {
  heap_caps_free(mic_);
  heap_caps_free(ref_);
  mic_ = nullptr;
  ref_ = nullptr;
}
