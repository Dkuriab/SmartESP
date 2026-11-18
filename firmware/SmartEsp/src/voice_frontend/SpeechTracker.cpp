#include "SpeechTracker.h"

void SpeechTracker::reset() {
  elapsedMs_ = 0;
  speaking_ = false;
}

SpeechChange SpeechTracker::update(bool speech, uint32_t frameMs) {
  if (elapsedMs_ < graceMs_) {
    elapsedMs_ += frameMs;
    if (elapsedMs_ <= graceMs_) {
      return SpeechChange::None;  // ещё «хвост» слова-активатора
    }
  }
  if (speech && !speaking_) {
    speaking_ = true;
    return SpeechChange::Start;
  }
  if (!speech && speaking_) {
    speaking_ = false;
    return SpeechChange::End;
  }
  return SpeechChange::None;
}
