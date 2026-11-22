#include "Ducker.h"

Ducker::Ducker(uint32_t resumeDelayMs, uint32_t fadeOutMs, uint32_t fadeInMs, uint32_t sampleRate)
    : resumeDelayMs_(resumeDelayMs), fadeOutMs_(fadeOutMs), fadeInMs_(fadeInMs) {
  setSampleRate(sampleRate);
}

void Ducker::setSampleRate(uint32_t sampleRate) {
  const float out = static_cast<float>(sampleRate) * fadeOutMs_ / 1000.0f;
  const float in = static_cast<float>(sampleRate) * fadeInMs_ / 1000.0f;
  down_ = out >= 1.0f ? 1.0f / out : 1.0f;
  up_ = in >= 1.0f ? 1.0f / in : 1.0f;
}

void Ducker::update(bool voiceActive, uint32_t nowMs) {
  if (voiceActive) {
    voice_ = true;
    muted_ = true;
    return;
  }
  if (voice_) {
    voice_ = false;
    quietSinceMs_ = nowMs;
  }
  if (muted_ && nowMs - quietSinceMs_ >= resumeDelayMs_) {
    muted_ = false;
  }
}

bool Ducker::muted() const {
  return muted_;
}

float Ducker::next() {
  if (muted_) {
    gain_ = gain_ > down_ ? gain_ - down_ : 0.0f;
  } else {
    gain_ = gain_ + up_ < 1.0f ? gain_ + up_ : 1.0f;
  }
  return gain_;
}

bool Ducker::silent() const {
  return muted_ && gain_ <= 0.0f;
}

void Ducker::restart() {
  gain_ = 0.0f;
}

void Ducker::setResumeDelay(uint32_t resumeDelayMs) {
  resumeDelayMs_ = resumeDelayMs;
}
