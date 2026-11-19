#include "WakeWord.h"

#include <new>

#include "WakeFeatures.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/stream_buffer.h"
#include "tensorflow/lite/micro/micro_allocator.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_resource_variable.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {

constexpr size_t AUDIO_QUEUE_SAMPLES = 16000;  // 1 с звука между loop() и задачей
constexpr size_t READ_SAMPLES = 480;           // за раз задача берёт до 30 мс
constexpr size_t OP_COUNT = 13;                // операций в resolver (см. addOps)
// Переменные потоковой модели (её память между вызовами): описания — в своей
// маленькой арене, как в ESPHome; «Миранде» нужно 6, запас — для других моделей.
constexpr int MAX_VARIABLES = 20;
constexpr size_t VARIABLE_ARENA_SIZE = 1024;
// Запас к арене из манифеста на расхождения версий TFLite Micro; сколько ушло
// на деле — печатается в Serial при запуске.
constexpr size_t ARENA_SLACK = 4096;
constexpr uint8_t MAX_WINDOW = 32;
constexpr uint32_t FEATURE_STEP_MS = 10;
constexpr uint32_t LOG_PERIOD_MS = 1000;

using OpResolver = tflite::MicroMutableOpResolver<OP_COUNT>;

// Ровно операции модели (список — LiteRT _get_ops_details на miranda.tflite).
// Новая модель с другими операциями не загрузится: begin() вернёт false.
bool addOps(OpResolver& resolver) {
  return resolver.AddAssignVariable() == kTfLiteOk && resolver.AddCallOnce() == kTfLiteOk &&
         resolver.AddConcatenation() == kTfLiteOk && resolver.AddConv2D() == kTfLiteOk &&
         resolver.AddDepthwiseConv2D() == kTfLiteOk && resolver.AddFullyConnected() == kTfLiteOk &&
         resolver.AddLogistic() == kTfLiteOk && resolver.AddQuantize() == kTfLiteOk &&
         resolver.AddReadVariable() == kTfLiteOk && resolver.AddReshape() == kTfLiteOk &&
         resolver.AddSplitV() == kTfLiteOk && resolver.AddStridedSlice() == kTfLiteOk &&
         resolver.AddVarHandle() == kTfLiteOk;
}

bool fail(const char* message) {
  Serial.printf("wake_word: %s\n", message);
  return false;
}

}  // namespace

struct WakeWord::State {
  WakeFeatures features;
  OpResolver resolver;
  tflite::MicroInterpreter* interpreter = nullptr;
  TfLiteTensor* input = nullptr;
  TfLiteTensor* output = nullptr;
  float inputScale = 1.0f;
  int inputZeroPoint = 0;
  int stride = 1;  // кадров признаков на один вызов модели

  float cutoff = 1.0f;
  uint8_t window = 1;
  uint32_t refractoryMs = 0;

  StreamBufferHandle_t audio = nullptr;  // loop() → задача
  uint32_t dropped = 0;                  // отброшено отсчётов (только loop())
  uint32_t lastDropLogMs = 0;

  // Только в задаче:
  int framesInInput = 0;
  uint8_t probabilities[MAX_WINDOW] = {};
  uint8_t probabilityPos = 0;
  uint8_t probabilityCount = 0;
  uint32_t quietMs = 0;  // сколько ещё молчать после срабатывания

  volatile uint32_t detections = 0;  // пишет задача
  uint32_t polled = 0;               // читает poll()

  static void taskEntry(void* self) { static_cast<State*>(self)->run(); }
  void run();
  void onFrame(const uint16_t* frame);
  void onProbability(uint8_t probability);
};

bool WakeWord::begin(const WakeWordConfig& config) {
  if (state_) {
    return true;
  }
  if (!psramFound()) {
    return fail("нет PSRAM (Tools → PSRAM → OPI PSRAM)");
  }
  if (config.window == 0 || config.window > MAX_WINDOW) {
    return fail("окно усреднения вне 1..32");
  }
  if (!config.model || config.modelSize < 8) {
    return fail("нет модели");
  }
  const tflite::Model* model = tflite::GetModel(config.model);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    return fail("модель не TFLite нужной версии");
  }

  State* st = new (std::nothrow) State();
  if (!st || !st->features.begin()) {
    return fail("нет памяти под признаки");
  }
  if (!addOps(st->resolver)) {
    return fail("не собран список операций");
  }

  const size_t arenaSize = config.arenaSize + ARENA_SLACK;
  uint8_t* arena = (uint8_t*)heap_caps_aligned_alloc(16, arenaSize, MALLOC_CAP_SPIRAM);
  uint8_t* variableArena = (uint8_t*)heap_caps_aligned_alloc(16, VARIABLE_ARENA_SIZE, MALLOC_CAP_INTERNAL);
  if (!arena || !variableArena) {
    return fail("нет памяти под арену модели");
  }
  tflite::MicroAllocator* variableAllocator = tflite::MicroAllocator::Create(variableArena, VARIABLE_ARENA_SIZE);
  tflite::MicroResourceVariables* variables =
      variableAllocator ? tflite::MicroResourceVariables::Create(variableAllocator, MAX_VARIABLES) : nullptr;
  if (!variables) {
    return fail("нет памяти под переменные модели");
  }
  st->interpreter =
      new (std::nothrow) tflite::MicroInterpreter(model, st->resolver, arena, arenaSize, variables);
  if (!st->interpreter || st->interpreter->AllocateTensors() != kTfLiteOk) {
    return fail("модель не разместилась (операции или арена) — см. сообщения TFLite выше");
  }

  st->input = st->interpreter->input(0);
  st->output = st->interpreter->output(0);
  const TfLiteIntArray* dims = st->input->dims;
  if (st->input->type != kTfLiteInt8 || dims->size != 3 || dims->data[0] != 1 || dims->data[1] < 1 ||
      dims->data[2] != (int)WakeFeatures::CHANNELS) {
    return fail("вход модели не int8 [1, N, 40]");
  }
  if (st->output->type != kTfLiteUInt8 || st->output->bytes < 1) {
    return fail("выход модели не uint8");
  }
  st->stride = dims->data[1];
  st->inputScale = st->input->params.scale;
  st->inputZeroPoint = st->input->params.zero_point;
  st->cutoff = config.cutoff;
  st->window = config.window;
  st->refractoryMs = config.refractoryMs;

  st->audio = xStreamBufferCreateWithCaps(AUDIO_QUEUE_SAMPLES * sizeof(int16_t),
                                          WakeFeatures::STEP_SAMPLES * sizeof(int16_t), MALLOC_CAP_SPIRAM);
  if (!st->audio) {
    return fail("нет памяти под очередь звука");
  }
  if (xTaskCreatePinnedToCore(State::taskEntry, "wake_word", 8192, st, 3, nullptr, 1) != pdPASS) {
    return fail("задача не создана");
  }
  Serial.printf("wake_word: модель %u байт, арена %u из %u байт, %d кадра на вызов, порог %.2f\n",
                (unsigned)config.modelSize, (unsigned)st->interpreter->arena_used_bytes(), (unsigned)arenaSize,
                st->stride, config.cutoff);
  state_ = st;
  return true;
}

void WakeWord::feed(const int16_t* pcm, size_t samples) {
  if (!state_ || samples == 0) {
    return;
  }
  State& st = *state_;
  const size_t bytes = samples * sizeof(int16_t);
  // Только целиком: так в очереди всегда чётное число байт (целые отсчёты).
  if (xStreamBufferSpacesAvailable(st.audio) >= bytes) {
    xStreamBufferSend(st.audio, pcm, bytes, 0);
  } else {
    st.dropped += samples;
  }
  if (st.dropped > 0 && millis() - st.lastDropLogMs >= LOG_PERIOD_MS) {
    st.lastDropLogMs = millis();
    Serial.printf("wake_word: не успевает, отброшено отсчётов: %u\n", (unsigned)st.dropped);
    st.dropped = 0;
  }
}

bool WakeWord::poll() {
  if (!state_ || state_->detections == state_->polled) {
    return false;
  }
  state_->polled++;
  return true;
}

void WakeWord::State::run() {
  int16_t pcm[READ_SAMPLES];
  uint16_t frame[WakeFeatures::CHANNELS];
  for (;;) {
    const size_t bytes = xStreamBufferReceive(audio, pcm, sizeof(pcm), portMAX_DELAY);
    const int16_t* next = pcm;
    size_t left = bytes / sizeof(int16_t);
    while (left > 0) {
      bool ready = false;
      const size_t used = features.process(next, left, frame, ready);
      if (ready) {
        onFrame(frame);
      }
      if (used == 0) {
        break;  // не должно случаться: фронтенд всегда берёт хотя бы отсчёт
      }
      next += used;
      left -= used;
    }
  }
}

void WakeWord::State::onFrame(const uint16_t* frame) {
  int8_t* slot = input->data.int8 + framesInInput * WakeFeatures::CHANNELS;
  for (size_t c = 0; c < WakeFeatures::CHANNELS; c++) {
    slot[c] = WakeFeatures::quantize(frame[c], inputScale, inputZeroPoint);
  }
  if (++framesInInput < stride) {
    return;
  }
  framesInInput = 0;
  if (interpreter->Invoke() != kTfLiteOk) {
    Serial.println("wake_word: ошибка вызова модели");
    return;
  }
  onProbability(output->data.uint8[0]);
}

void WakeWord::State::onProbability(uint8_t probability) {
  const uint32_t stepMs = stride * FEATURE_STEP_MS;
  quietMs = quietMs > stepMs ? quietMs - stepMs : 0;

  probabilities[probabilityPos] = probability;
  probabilityPos = (probabilityPos + 1) % window;
  if (probabilityCount < window) {
    probabilityCount++;
  }
  if (probabilityCount < window || quietMs > 0) {
    return;
  }
  uint32_t sum = 0;
  for (uint8_t i = 0; i < window; i++) {
    sum += probabilities[i];
  }
  const float mean = sum / (255.0f * window);
  if (mean <= cutoff) {
    return;
  }
  detections = detections + 1;
  quietMs = refractoryMs;
  probabilityCount = 0;  // после паузы окно набирается заново
  Serial.printf("wake_word: слово услышано, вероятность %.2f\n", mean);
}
