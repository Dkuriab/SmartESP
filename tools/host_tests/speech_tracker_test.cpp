// Тесты SpeechTracker (voice_frontend): события речи с паузой после слова.

#include "test.h"
#include "voice_frontend/SpeechTracker.h"

namespace {

constexpr uint32_t FRAME = 32;  // мс, кадр AFE

// Подаёт одно и то же состояние VAD ms миллисекунд; возвращает первое событие или None.
SpeechChange feed(SpeechTracker& tracker, bool speech, uint32_t ms) {
  SpeechChange first = SpeechChange::None;
  for (uint32_t t = 0; t < ms; t += FRAME) {
    const SpeechChange change = tracker.update(speech, FRAME);
    if (first == SpeechChange::None) first = change;
  }
  return first;
}

}  // namespace

TEST(tracker_ignores_wake_word_carryover) {
  SpeechTracker tracker(600);
  tracker.reset();
  // VAD ещё слышит слово-активатор, затем пауза перед вопросом.
  CHECK(feed(tracker, true, 400) == SpeechChange::None);
  CHECK(feed(tracker, false, 2000) == SpeechChange::None);
}

TEST(tracker_starts_after_grace_if_still_speaking) {
  SpeechTracker tracker(600);
  tracker.reset();
  CHECK(feed(tracker, true, 576) == SpeechChange::None);  // 18 кадров < 600 мс
  CHECK(tracker.update(true, FRAME) == SpeechChange::Start);  // 608 мс
}

TEST(tracker_start_then_end) {
  SpeechTracker tracker(600);
  tracker.reset();
  feed(tracker, false, 640);
  CHECK(tracker.update(true, FRAME) == SpeechChange::Start);
  CHECK(feed(tracker, true, 1000) == SpeechChange::None);
  CHECK(tracker.update(false, FRAME) == SpeechChange::End);
  CHECK(feed(tracker, false, 500) == SpeechChange::None);
}

TEST(tracker_reset_restarts_grace) {
  SpeechTracker tracker(600);
  tracker.reset();
  feed(tracker, false, 640);
  CHECK(tracker.update(true, FRAME) == SpeechChange::Start);
  tracker.reset();
  CHECK(feed(tracker, true, 576) == SpeechChange::None);
  CHECK(tracker.update(false, FRAME) == SpeechChange::None);  // речь не начиналась — конца нет
}
