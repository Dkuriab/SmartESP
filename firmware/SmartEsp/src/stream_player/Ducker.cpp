#include "Ducker.h"

Ducker::Ducker(uint32_t resumeDelayMs, uint32_t fadeOutSamples, uint32_t fadeInSamples)
    : resumeDelayMs_(resumeDelayMs),
      down_(fadeOutSamples > 0 ? 1.0f / fadeOutSamples : 1.0f),
      up_(fadeInSamples > 0 ? 1.0f / fadeInSamples : 1.0f) {}

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
