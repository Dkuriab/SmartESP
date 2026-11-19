#include "WakeFeatures.h"

#include <math.h>
#include <string.h>

#include <new>

#include "microfrontend/frontend.h"
#include "microfrontend/frontend_util.h"

namespace {

constexpr int SAMPLE_RATE = 16000;
constexpr float FLOAT32_SCALE = 0.0390625f;  // uint16 → float, как в microWakeWord

// Настройки — как в pymicro-features 2.0.2 (src/micro_features.cpp).
FrontendConfig makeConfig() {
  FrontendConfig config;
  FrontendFillConfigWithDefaults(&config);
  config.window.size_ms = 30;
  config.window.step_size_ms = 10;
  config.filterbank.num_channels = WakeFeatures::CHANNELS;
  config.filterbank.lower_band_limit = 125.0f;
  config.filterbank.upper_band_limit = 7500.0f;
  config.noise_reduction.smoothing_bits = 10;
  config.noise_reduction.even_smoothing = 0.025f;
  config.noise_reduction.odd_smoothing = 0.06f;
  config.noise_reduction.min_signal_remaining = 0.05f;
  config.pcan_gain_control.enable_pcan = 1;
  config.pcan_gain_control.strength = 0.95f;
  config.pcan_gain_control.offset = 80.0f;
  config.pcan_gain_control.gain_bits = 21;
  config.log_scale.enable_log = 1;
  config.log_scale.scale_shift = 6;
  return config;
}

}  // namespace

WakeFeatures::~WakeFeatures() {
  if (state_) {
    FrontendFreeStateContents(state_);
    delete state_;
  }
}

bool WakeFeatures::begin() {
  if (state_) return true;
  state_ = new (std::nothrow) FrontendState();
  if (!state_) return false;
  const FrontendConfig config = makeConfig();
  if (!FrontendPopulateState(&config, state_, SAMPLE_RATE)) {
    delete state_;
    state_ = nullptr;
    return false;
  }
  return true;
}

size_t WakeFeatures::process(const int16_t* pcm, size_t samples, uint16_t* frame, bool& ready) {
  ready = false;
  size_t used = 0;
  const FrontendOutput output = FrontendProcessSamples(state_, pcm, samples, &used);
  if (output.size == CHANNELS && output.values) {
    memcpy(frame, output.values, CHANNELS * sizeof(uint16_t));
    ready = true;
  }
  return used;
}

int8_t WakeFeatures::quantize(uint16_t value, float scale, int zeroPoint) {
  const long q = lroundf(value * FLOAT32_SCALE / scale) + zeroPoint;
  return static_cast<int8_t>(q < -128 ? -128 : (q > 127 ? 127 : q));
}
