// Тесты звука 48 кГц (прошивка 0.7.0): ×3 и ÷3 (Resampler), поиск задержки эха (Correlator),
// сообщения калибровки и частоты потоков в hello, шаги приглушения по частоте потока.

#include <ArduinoJson.h>

#include <cmath>
#include <cstring>
#include <string>
#include <vector>

#include "audio_out/Resampler.h"
#include "echo_calibrator/Correlator.h"
#include "server_link/Protocol.h"
#include "stream_player/Ducker.h"
#include "test.h"

namespace {

constexpr double PI = 3.14159265358979323846;

std::vector<int16_t> tone(double hz, double rate, size_t n, double amplitude = 10000.0) {
  std::vector<int16_t> out(n);
  for (size_t i = 0; i < n; ++i) out[i] = static_cast<int16_t>(amplitude * std::sin(2.0 * PI * hz * i / rate));
  return out;
}

// Амплитуда частоты hz в x (проекция на синус и косинус), без первых skip отсчётов.
double amplitudeAt(const std::vector<int16_t>& x, double hz, double rate, size_t skip) {
  double s = 0.0;
  double c = 0.0;
  for (size_t i = skip; i < x.size(); ++i) {
    s += x[i] * std::sin(2.0 * PI * hz * i / rate);
    c += x[i] * std::cos(2.0 * PI * hz * i / rate);
  }
  return 2.0 * std::sqrt(s * s + c * c) / (x.size() - skip);
}

double db(double ratio) {
  return 20.0 * std::log10(ratio);
}

std::vector<int16_t> upsample(const std::vector<int16_t>& in, size_t chunk) {
  Upsampler3 up;
  std::vector<int16_t> out(in.size() * 3);
  for (size_t i = 0; i < in.size(); i += chunk) {
    const size_t n = std::min(chunk, in.size() - i);
    up.process(in.data() + i, n, out.data() + 3 * i);
  }
  return out;
}

std::vector<int16_t> decimate(const std::vector<int16_t>& in, size_t chunk) {
  Decimator3 down;
  std::vector<int16_t> out(in.size() / 3 + 1);
  size_t produced = 0;
  for (size_t i = 0; i < in.size(); i += chunk) {
    const size_t n = std::min(chunk, in.size() - i);
    produced += down.process(in.data() + i, n, out.data() + produced);
  }
  out.resize(produced);
  return out;
}

}  // namespace

TEST(upsampler_keeps_voice_band) {
  for (double hz : {300.0, 1000.0, 4000.0, 6000.0}) {
    const auto out = upsample(tone(hz, 16000, 16000), 256);
    const double gain = amplitudeAt(out, hz, 48000, 480) / 10000.0;
    CHECK(std::fabs(db(gain)) < 0.5);  // полоса до 6 кГц — без потерь
  }
}

TEST(upsampler_suppresses_images) {
  for (double hz : {1000.0, 3000.0, 6000.0}) {
    const auto out = upsample(tone(hz, 16000, 16000), 256);
    const double image = amplitudeAt(out, 16000.0 - hz, 48000, 480) / 10000.0;
    CHECK(db(image) < -60.0);  // зеркала выше 8 кГц не слышны
  }
}

TEST(upsampler_chunks_do_not_matter) {
  const auto in = tone(1234.0, 16000, 4096);
  CHECK(upsample(in, 256) == upsample(in, 77));
}

TEST(decimator_passes_band_and_blocks_alias) {
  const auto low = decimate(tone(1000.0, 48000, 48000), 768);
  CHECK(low.size() == 16000);
  CHECK(std::fabs(db(amplitudeAt(low, 1000.0, 16000, 160) / 10000.0)) < 0.5);
  // 12 кГц после ÷3 сложился бы в 4 кГц — фильтр не пускает
  const auto alias = decimate(tone(12000.0, 48000, 48000), 768);
  CHECK(db(amplitudeAt(alias, 4000.0, 16000, 160) / 10000.0) < -60.0);
  CHECK(decimate(tone(500.0, 48000, 9000), 768) == decimate(tone(500.0, 48000, 9000), 100));
}

TEST(round_trip_delay_is_known) {
  // Щелчок 16 кГц → ×3 → ÷3: пик сдвигается на две задержки фильтра (≈ 2 мс ≈ 32 отсчёта).
  std::vector<int16_t> click(1600, 0);
  click[100] = 20000;
  const auto back = decimate(upsample(click, 256), 768);
  size_t peak = 0;
  for (size_t i = 0; i < back.size(); ++i) {
    if (std::abs(back[i]) > std::abs(back[peak])) peak = i;
  }
  const double expected = 100.0 + 2.0 * RESAMPLE_DELAY_MS * 16.0;
  CHECK(std::fabs(peak - expected) <= 1.0);
}

TEST(correlator_finds_echo_delay) {
  uint32_t seed = 7;
  const size_t n = 44800;
  std::vector<int16_t> ref(n, 0);
  for (size_t i = 3000; i < 27000; ++i) ref[i] = testNoise(seed, i - 3000, 24000, 160, 8000);
  for (int delay : {-200, 0, 37, 960, 2400}) {
    std::vector<int16_t> mic(n, 0);
    uint32_t hiss = 99;
    for (size_t i = 0; i < n; ++i) {
      const long src = static_cast<long>(i) - delay;
      const double echo = src >= 0 && src < static_cast<long>(n) ? 0.3 * ref[src] : 0.0;
      const double reflection = src - 300 >= 0 && src - 300 < static_cast<long>(n) ? 0.1 * ref[src - 300] : 0.0;
      mic[i] = static_cast<int16_t>(echo + reflection + testNoise(hiss, 1000, 2000, 0, 300));
    }
    const LagEstimate found = findLag(mic.data(), ref.data(), n, 3320, 16000, -320, 3200);
    CHECK_EQ(found.lag, delay);
    CHECK(found.confidence > 0.6f);
    CHECK(found.ratio > 1.5f);
  }
}

TEST(correlator_low_confidence_without_echo) {
  uint32_t seed = 3;
  uint32_t other = 11;
  const size_t n = 30000;
  std::vector<int16_t> ref(n);
  std::vector<int16_t> mic(n);
  for (size_t i = 0; i < n; ++i) {
    ref[i] = testNoise(seed, 1000, 2000, 0, 8000);
    mic[i] = testNoise(other, 1000, 2000, 0, 8000);
  }
  const LagEstimate found = findLag(mic.data(), ref.data(), n, 400, 16000, -320, 3200);
  CHECK(found.confidence < 0.1f);
}

TEST(test_noise_has_soft_edges_and_onset) {
  uint32_t seed = 1;
  std::vector<int16_t> x(1600);
  for (size_t i = 0; i < x.size(); ++i) x[i] = testNoise(seed, i, x.size(), 160, 8000);
  CHECK(std::abs(x[0]) < 100 && std::abs(x.back()) < 100);
  std::vector<int16_t> padded(500, 0);
  padded.insert(padded.end(), x.begin(), x.end());
  const size_t onset = findOnset(padded.data(), padded.size(), 1000);
  CHECK(onset > 500 && onset < 700);
  CHECK_EQ(findOnset(padded.data(), 500, 1000), 500u);
}

TEST(hello_has_echo_and_stream_rates) {
  char buffer[768];
  const size_t length = encodeHello("0.7.0", "AA:BB", buffer, sizeof(buffer));
  JsonDocument doc;
  CHECK(length > 0 && !deserializeJson(doc, buffer, length));
  CHECK_EQ(doc["protocol"].as<int>(), 5);  // номер тот же: калибровка — возможность «echo»
  CHECK_EQ(std::string(doc["caps"][1] | ""), "echo");
  CHECK_EQ(doc["stream_rates"][0].as<int>(), 16000);
  CHECK_EQ(doc["stream_rates"][1].as<int>(), 48000);
}

TEST(echo_commands_and_status) {
  ServerCommand cmd{};
  const char* calibrate = "{\"type\":\"echo_calibrate\"}";
  CHECK(decodeServerCommand(calibrate, std::strlen(calibrate), cmd));
  CHECK(cmd.type == ServerCommandType::EchoCalibrate);
  const char* delay = "{\"type\":\"echo_delay\",\"delay_ms\":42}";
  CHECK(decodeServerCommand(delay, std::strlen(delay), cmd));
  CHECK(cmd.type == ServerCommandType::EchoDelay);
  CHECK_EQ(cmd.delayMs, 42);
  const char* tooLong = "{\"type\":\"echo_delay\",\"delay_ms\":301}";
  CHECK(!decodeServerCommand(tooLong, std::strlen(tooLong), cmd));
  const char* missing = "{\"type\":\"echo_delay\"}";
  CHECK(!decodeServerCommand(missing, std::strlen(missing), cmd));

  ClientEvent event{};
  event.type = ClientEventType::EchoStatus;
  event.echoState = EchoState::Done;
  event.delayMs = 23;
  event.previousMs = 20;
  event.confidence = 0.734f;
  char buffer[192];
  const size_t length = encodeClientEvent(event, buffer, sizeof(buffer));
  JsonDocument doc;
  CHECK(length > 0 && !deserializeJson(doc, buffer, length));
  CHECK_EQ(std::string(doc["type"] | ""), "echo_status");
  CHECK_EQ(std::string(doc["state"] | ""), "done");
  CHECK_EQ(doc["delay_ms"].as<int>(), 23);
  CHECK_EQ(doc["previous_ms"].as<int>(), 20);
  CHECK(std::fabs(doc["confidence"].as<float>() - 0.73f) < 0.001f);
  CHECK_EQ(std::string(doc["error"] | "?"), "");
  CHECK(doc["turn"].isNull());
}

TEST(ducker_fade_follows_sample_rate) {
  Ducker ducker(1500, 30, 300, 48000);
  ducker.update(false, 0);
  size_t samples = 0;
  while (ducker.next() < 1.0f && samples < 100000) samples++;
  CHECK(samples > 14300 && samples < 14500);  // 300 мс при 48 кГц
  ducker.setSampleRate(16000);
  ducker.update(true, 100);
  samples = 0;
  while (!ducker.silent() && samples < 100000) {
    ducker.next();
    samples++;
  }
  CHECK(samples >= 479 && samples <= 481);  // 30 мс при 16 кГц
}
