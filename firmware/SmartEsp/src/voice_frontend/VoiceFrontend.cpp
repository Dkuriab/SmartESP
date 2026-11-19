#include "VoiceFrontend.h"

// Обёртку ESP_SR не вызываем (она всегда грузит MultiNet, который падает,
// и не отдаёт очищенный звук), но подключаем: только тогда ядро кладёт
// srmodels.bin (модели AFE) в сборку и прошивает его в раздел model.
#include "ESP_SR.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_vad.h"
#include "freertos/idf_additions.h"
#include "model_path.h"

namespace {

constexpr size_t FEED_QUEUE_FRAMES = 32;          // ~1 с при кадре 32 мс
constexpr size_t CLEAN_QUEUE_SAMPLES = 16000 * 2;  // 2 с очищенного звука
constexpr size_t WAKE_QUEUE_SAMPLES = 16000;       // 1 с звука для слова пробуждения
constexpr UBaseType_t EVENT_QUEUE_LENGTH = 8;
constexpr uint32_t LOG_PERIOD_MS = 1000;

const esp_afe_sr_iface_t* iface(const void* handle) {
  return static_cast<const esp_afe_sr_iface_t*>(handle);
}

}  // namespace

bool VoiceFrontend::begin(const VoiceFrontendConfig& config) {
  if (!psramFound()) {
    Serial.println("voice_frontend: нет PSRAM (Tools → PSRAM → OPI PSRAM)");
    return false;
  }

  srmodel_list_t* models = esp_srmodel_init("model");
  if (!models || models->num == 0) {
    Serial.println("voice_frontend: модели не найдены (Partition Scheme → ESP SR 16M)");
    return false;
  }

  afe_config_t* afeConfig = afe_config_init("MR", models, AFE_TYPE_SR, AFE_MODE_LOW_COST);
  if (!afeConfig) {
    Serial.println("voice_frontend: afe_config_init вернул NULL");
    return false;
  }
  afeConfig->vad_min_noise_ms = config.vadSilenceMs;
  afeConfig->wakenet_init = false;  // слово ищет wake_word (microWakeWord)
  // Пока VAD «дослушивает» само слово (≈ vadSilenceMs), события речи не выдаём.
  speech_ = SpeechTracker(config.vadSilenceMs + 100);
  const esp_afe_sr_iface_t* afe = esp_afe_handle_from_config(afeConfig);
  afe_ = afe;
  afeData_ = afe ? afe->create_from_config(afeConfig) : nullptr;
  afe_config_free(afeConfig);
  if (!afeData_) {
    Serial.println("voice_frontend: AFE не создан");
    return false;
  }
  afe->print_pipeline(afeData_);

  chunk_ = afe->get_feed_chunksize(afeData_);
  channels_ = afe->get_feed_channel_num(afeData_);
  const size_t frameBytes = chunk_ * channels_ * sizeof(int16_t);

  frame_ = (int16_t*)heap_caps_calloc(chunk_ * channels_, sizeof(int16_t), MALLOC_CAP_INTERNAL);
  feedQueue_ = xStreamBufferCreateWithCaps(frameBytes * FEED_QUEUE_FRAMES, frameBytes, MALLOC_CAP_SPIRAM);
  cleanQueue_ = xStreamBufferCreateWithCaps(CLEAN_QUEUE_SAMPLES * sizeof(int16_t), 1, MALLOC_CAP_SPIRAM);
  wakeQueue_ = xStreamBufferCreateWithCaps(WAKE_QUEUE_SAMPLES * sizeof(int16_t), 1, MALLOC_CAP_SPIRAM);
  for (float& level : levels_) {
    level = -100.0f;  // тишина, чтобы нули не выдавали себя за 0 дБFS
  }
  events_ = xQueueCreate(EVENT_QUEUE_LENGTH, sizeof(VoiceEvent));
  if (!frame_ || !feedQueue_ || !cleanQueue_ || !wakeQueue_ || !events_) {
    Serial.println("voice_frontend: нет памяти под буферы");
    return false;
  }

  Serial.printf("voice_frontend: кадр %d x %d каналов\n", chunk_, channels_);
  return xTaskCreatePinnedToCore(feedTaskEntry, "vf_feed", 4096, this, 5, nullptr, 0) == pdPASS &&
         xTaskCreatePinnedToCore(fetchTaskEntry, "vf_fetch", 8192, this, 5, nullptr, 1) == pdPASS;
}

void VoiceFrontend::feed(const int16_t* mic, const int16_t* ref, size_t samples) {
  const size_t frameBytes = chunk_ * channels_ * sizeof(int16_t);
  for (size_t i = 0; i < samples; i++) {
    int16_t* slot = frame_ + filled_ * channels_;
    slot[0] = mic[i];
    slot[1] = ref[i];
    for (int c = 2; c < channels_; c++) {
      slot[c] = 0;
    }
    if (++filled_ < chunk_) {
      continue;
    }
    filled_ = 0;
    // Кадр отправляется только целиком, иначе собьётся разбиение на кадры.
    if (xStreamBufferSpacesAvailable(feedQueue_) >= frameBytes) {
      xStreamBufferSend(feedQueue_, frame_, frameBytes, 0);
    } else {
      droppedFrames_++;
    }
  }
  if (droppedFrames_ > 0 && millis() - lastDropLogMs_ >= LOG_PERIOD_MS) {
    lastDropLogMs_ = millis();
    Serial.printf("voice_frontend: AFE не успевает, отброшено кадров: %u\n", (unsigned)droppedFrames_);
    droppedFrames_ = 0;
  }
}

bool VoiceFrontend::pollEvent(VoiceEvent& event) {
  return xQueueReceive(events_, &event, 0) == pdTRUE;
}

void VoiceFrontend::setCapture(bool on) {
  capture_ = on;
  captureGeneration_ = captureGeneration_ + 1;
  drainClean();  // остатки прошлого захвата не должны попасть в новый
}

size_t VoiceFrontend::readClean(int16_t* dst, size_t maxSamples) {
  if (!capture_) {
    drainClean();
    return 0;
  }
  return xStreamBufferReceive(cleanQueue_, dst, maxSamples * sizeof(int16_t), 0) / sizeof(int16_t);
}

size_t VoiceFrontend::readForWake(int16_t* dst, size_t maxSamples) {
  return xStreamBufferReceive(wakeQueue_, dst, maxSamples * sizeof(int16_t), 0) / sizeof(int16_t);
}

float VoiceFrontend::level() const {
  return level_;
}

void VoiceFrontend::drainClean() {
  int16_t scratch[256];
  while (xStreamBufferReceive(cleanQueue_, scratch, sizeof(scratch), 0) > 0) {
  }
}

void VoiceFrontend::pushEvent(VoiceEventType type) {
  const VoiceEvent event{type, 0.0f};
  if (xQueueSend(events_, &event, 0) != pdTRUE) {
    Serial.println("voice_frontend: очередь событий полна");
  }
}

void VoiceFrontend::feedTaskEntry(void* self) {
  static_cast<VoiceFrontend*>(self)->feedTask();
}

void VoiceFrontend::fetchTaskEntry(void* self) {
  static_cast<VoiceFrontend*>(self)->fetchTask();
}

void VoiceFrontend::feedTask() {
  const size_t frameBytes = chunk_ * channels_ * sizeof(int16_t);
  int16_t* frame = (int16_t*)heap_caps_malloc(frameBytes, MALLOC_CAP_INTERNAL);
  for (;;) {
    if (xStreamBufferReceive(feedQueue_, frame, frameBytes, portMAX_DELAY) == frameBytes) {
      iface(afe_)->feed(afeData_, frame);
    }
  }
}

void VoiceFrontend::fetchTask() {
  uint32_t generation = captureGeneration_;
  for (;;) {
    afe_fetch_result_t* res = iface(afe_)->fetch(afeData_);
    if (!res || res->ret_value == ESP_FAIL) {
      continue;
    }

    levels_[levelPos_] = res->data_volume;
    levelPos_ = (levelPos_ + 1) % LEVEL_FRAMES;
    float level = levels_[0];
    for (int i = 1; i < LEVEL_FRAMES; i++) {
      if (levels_[i] > level) level = levels_[i];
    }
    level_ = level;

    // Звук для слова пробуждения — всегда; кадр только целиком, иначе
    // в очереди окажется полотсчёта. Не успевает читатель — кадр теряется.
    if (res->data && res->data_size > 0) {
      if (xStreamBufferSpacesAvailable(wakeQueue_) >= (size_t)res->data_size) {
        xStreamBufferSend(wakeQueue_, res->data, res->data_size, 0);
      } else {
        wakeDroppedFrames_++;
      }
    }
    if (wakeDroppedFrames_ > 0 && millis() - lastWakeDropLogMs_ >= LOG_PERIOD_MS) {
      lastWakeDropLogMs_ = millis();
      Serial.printf("voice_frontend: loop() не забирает звук слова, отброшено кадров: %u\n",
                    (unsigned)wakeDroppedFrames_);
      wakeDroppedFrames_ = 0;
    }

    if (generation != captureGeneration_) {
      generation = captureGeneration_;
      speech_.reset();  // новый захват — переходы VAD считаем заново, с паузой после слова
    }
    if (!capture_) {
      continue;
    }

    const uint32_t frameMs = res->data_size / sizeof(int16_t) / 16;  // 16 отсчётов = 1 мс
    switch (speech_.update(res->vad_state == VAD_SPEECH, frameMs)) {
      case SpeechChange::Start: pushEvent(VoiceEventType::SpeechStart); break;
      case SpeechChange::End: pushEvent(VoiceEventType::SpeechEnd); break;
      case SpeechChange::None: break;
    }

    if (res->data && res->data_size > 0) {
      xStreamBufferSend(cleanQueue_, res->data, res->data_size, 0);
    }
  }
}
