// Тесты WakeFeatures (wake_word): признаки совпадают с pymicro-features,
// квантование — по параметрам входа модели.

#include <algorithm>
#include <cmath>
#include <vector>

#include "data/features_ref.h"
#include "test.h"
#include "wake_word/WakeFeatures.h"

namespace {

// Тот же звук, что в tools/make_features_ref.py: 1 с синуса, затем 1 с тишины.
// nearbyint округляет половины к чётному — как round() в Python.
std::vector<int16_t> makeSignal() {
  std::vector<int16_t> signal(2 * FEATURES_REF_SAMPLE_RATE, 0);
  for (int n = 0; n < FEATURES_REF_SAMPLE_RATE; n++) {
    const double phase = 2 * M_PI * FEATURES_REF_FREQUENCY * n / FEATURES_REF_SAMPLE_RATE;
    signal[n] = static_cast<int16_t>(std::nearbyint(FEATURES_REF_AMPLITUDE * std::sin(phase)));
  }
  return signal;
}

// Подаёт звук кусками по chunk отсчётов, собирает все кадры признаков.
std::vector<std::vector<uint16_t>> computeFeatures(WakeFeatures& features, size_t chunk) {
  const std::vector<int16_t> signal = makeSignal();
  std::vector<std::vector<uint16_t>> frames;
  uint16_t frame[WakeFeatures::CHANNELS];
  for (size_t start = 0; start < signal.size(); start += chunk) {
    const int16_t* pcm = signal.data() + start;
    size_t left = std::min(chunk, signal.size() - start);
    while (left > 0) {
      bool ready = false;
      const size_t used = features.process(pcm, left, frame, ready);
      pcm += used;
      left -= used;
      if (ready) frames.emplace_back(frame, frame + WakeFeatures::CHANNELS);
    }
  }
  return frames;
}

int countMismatches(const std::vector<std::vector<uint16_t>>& frames) {
  int mismatches = 0;
  for (int f = 0; f < FEATURES_REF_FRAMES && f < (int)frames.size(); f++) {
    for (int c = 0; c < FEATURES_REF_CHANNELS; c++) {
      if (frames[f][c] != FEATURES_REF[f][c]) mismatches++;
    }
  }
  return mismatches;
}

}  // namespace

TEST(wake_features_match_reference) {
  CHECK_EQ((int)WakeFeatures::CHANNELS, FEATURES_REF_CHANNELS);
  WakeFeatures features;
  CHECK(features.begin());
  const auto frames = computeFeatures(features, WakeFeatures::STEP_SAMPLES);
  CHECK_EQ((int)frames.size(), FEATURES_REF_FRAMES);
  CHECK_EQ(countMismatches(frames), 0);
}

TEST(wake_features_do_not_depend_on_chunk_size) {
  WakeFeatures features;
  CHECK(features.begin());
  const auto frames = computeFeatures(features, 333);  // куски не кратны шагу
  CHECK_EQ((int)frames.size(), FEATURES_REF_FRAMES);
  CHECK_EQ(countMismatches(frames), 0);
}

TEST(wake_features_quantize_by_input_params) {
  // Вход «Миранды»: scale 0.10196078, zero_point -128.
  const float scale = 0.10196078f;
  CHECK_EQ(WakeFeatures::quantize(0, scale, -128), -128);
  CHECK_EQ(WakeFeatures::quantize(100, scale, -128), -90);   // 3.906 / 0.102 = 38.3 → 38
  CHECK_EQ(WakeFeatures::quantize(400, scale, -128), 25);    // 15.625 / 0.102 = 153.2 → 153
  CHECK_EQ(WakeFeatures::quantize(1000, scale, -128), 127);  // больше предела — 127
}
