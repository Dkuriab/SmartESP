#include "StreamPlayer.h"

#include "freertos/idf_additions.h"

namespace {

constexpr uint32_t SAMPLE_RATE = 16000;
constexpr uint32_t BYTES_PER_MS = SAMPLE_RATE * 2 / 1000;
constexpr size_t CHUNK = 1024;                // байт за одно чтение из сети
constexpr uint32_t HTTP_TIMEOUT_MS = 20000;   // ядро ждёт первый звук источника до 12 с
constexpr uint32_t STALL_MS = 20000;          // буфер пуст и данных нет столько — обрыв
constexpr uint32_t FLUSH_WAIT_MS = 200;       // задача звука забирает просьбу очистить за ~16 мс
constexpr UBaseType_t COMMANDS = 4;
constexpr UBaseType_t EVENTS = 8;

}  // namespace

bool StreamPlayer::begin(const StreamPlayerConfig& config) {
  config_ = config;
  ducker_.setResumeDelay(config_.resumeDelayMs);
  buffer_ = xStreamBufferCreateWithCaps(config_.bufferMs * BYTES_PER_MS, 1, MALLOC_CAP_SPIRAM);
  commands_ = xQueueCreate(COMMANDS, sizeof(Command));
  events_ = xQueueCreate(EVENTS, sizeof(ClientEvent));
  if (!buffer_ || !commands_ || !events_) {
    Serial.println("stream_player: нет памяти под буфер");
    return false;
  }
  ready_ = true;
  return xTaskCreatePinnedToCore(taskEntry, "stream", 6144, this, 3, nullptr, 1) == pdPASS;
}

void StreamPlayer::start(const StreamRequest& request) {
  Command command{true, request};
  if (!commands_ || xQueueSend(commands_, &command, 0) != pdTRUE) {
    Serial.println("stream_player: очередь команд полна");
  }
}

void StreamPlayer::stop(uint32_t id) {
  Command command{};
  command.start = false;
  command.request.id = id;
  if (commands_) xQueueSend(commands_, &command, 0);
}

void StreamPlayer::setVolume(float volume) {
  volume_ = volume < 0.0f ? 0.0f : (volume > 1.0f ? 1.0f : volume);
}

void StreamPlayer::setVoiceActive(bool active) {
  voiceActive_ = active;
}

void StreamPlayer::setConnected(bool connected) {
  const bool lost = connected_ && !connected;
  connected_ = connected;
  const uint8_t phase = phase_;
  if (lost && (phase == Connecting || phase == Playing)) {
    stop(0);  // без связи с ядром музыка не играет: ни паузы, ни стопа не дождаться
  }
}

void StreamPlayer::loop(uint32_t nowMs) {
  ducker_.update(voiceActive_, nowMs);
  if (phase_ != Playing) {
    return;
  }
  const uint32_t id = id_;
  if (id != reportedId_ || nowMs - lastReportMs_ >= config_.reportMs) {
    reportedId_ = id;
    lastReportMs_ = nowMs;
    post(StreamState::Playing, StreamError::None);
  }
}

bool StreamPlayer::pollStatus(ClientEvent& event) {
  return events_ && xQueueReceive(events_, &event, 0) == pdTRUE;
}

size_t StreamPlayer::read(int16_t* dst, size_t samples) {
  if (!ready_) {
    return 0;
  }
  if (flushRequest_) {
    xStreamBufferReset(buffer_);  // задача скачивания ждёт и не пишет
    prebuffered_ = false;
    ducker_.restart();
    flushRequest_ = false;
  }
  if (phase_ != Playing) {
    return 0;
  }
  const size_t available = xStreamBufferBytesAvailable(buffer_) & ~static_cast<size_t>(1);
  if (!prebuffered_) {
    prebuffered_ = available >= config_.prebufferMs * BYTES_PER_MS || (eof_ && available > 0);
    if (!prebuffered_) {
      if (eof_ && available == 0) finishDrained();
      return 0;
    }
  }
  if (ducker_.silent() && !live_) {
    return 0;  // пауза на время разговора: буфер стоит, сеть ждёт
  }
  const size_t want = samples * sizeof(int16_t) < available ? samples * sizeof(int16_t) : available;
  const size_t got = xStreamBufferReceive(buffer_, dst, want, 0) & ~static_cast<size_t>(1);
  const size_t n = got / sizeof(int16_t);
  if (n == 0) {
    if (eof_) {
      finishDrained();
    } else {
      prebuffered_ = false;  // сеть не успела — копим заново
    }
    return 0;
  }
  played_ += static_cast<uint32_t>(got);
  if (ducker_.silent()) {
    return 0;  // живой поток во время разговора: читаем и молчим
  }
  const float volume = volume_;
  for (size_t i = 0; i < n; i++) {
    dst[i] = static_cast<int16_t>(dst[i] * ducker_.next() * volume);
  }
  return n;
}

void StreamPlayer::finishDrained() {
  uint8_t expected = Playing;
  if (phase_.compare_exchange_strong(expected, Ended)) {
    post(StreamState::Ended, StreamError::None);
  }
}

void StreamPlayer::post(StreamState state, StreamError error) {
  ClientEvent event{};
  event.type = ClientEventType::StreamStatus;
  event.turn = id_;
  event.bytes = played_;
  event.streamState = state;
  event.streamError = error;
  if (events_) xQueueSend(events_, &event, 0);
}

void StreamPlayer::taskEntry(void* self) {
  static_cast<StreamPlayer*>(self)->run();
}

void StreamPlayer::run() {
  Command command;
  for (;;) {
    if (xQueueReceive(commands_, &command, open_ ? 0 : pdMS_TO_TICKS(50)) == pdTRUE) {
      handle(command);
    }
    if (open_) {
      pump();
    }
  }
}

void StreamPlayer::handle(const Command& command) {
  if (command.start) {
    open(command.request);
    return;
  }
  const uint8_t phase = phase_;
  const bool active = phase == Connecting || phase == Playing;
  if (!active || (command.request.id != 0 && command.request.id != id_)) {
    return;
  }
  close();
  flush();
  phase_ = Stopped;
  post(StreamState::Stopped, StreamError::None);
}

void StreamPlayer::open(const StreamRequest& request) {
  close();
  phase_ = Connecting;  // звук перестаёт брать буфер
  flush();
  played_ = 0;
  eof_ = false;
  live_ = request.live;
  volume_ = request.volume;
  id_ = request.id;
  if (request.rate != SAMPLE_RATE) {
    phase_ = Failed;
    post(StreamState::Failed, StreamError::Rate);
    return;
  }
  http_.useHTTP10(true);  // без chunked: поток кончается закрытием соединения
  http_.setReuse(false);
  http_.setTimeout(HTTP_TIMEOUT_MS);
  if (!http_.begin(client_, config_.host, config_.port, request.path) || http_.GET() != HTTP_CODE_OK) {
    http_.end();
    phase_ = Failed;
    post(StreamState::Failed, StreamError::Download);
    Serial.printf("stream_player: поток %u не открылся\n", (unsigned)request.id);
    return;
  }
  open_ = true;
  lastDataMs_ = millis();
  phase_ = Playing;
  Serial.printf("stream_player: поток %u\n", (unsigned)request.id);
}

void StreamPlayer::pump() {
  static uint8_t chunk[CHUNK];
  WiFiClient* stream = http_.getStreamPtr();
  const size_t space = xStreamBufferSpacesAvailable(buffer_);
  const int available = stream ? stream->available() : 0;
  if (available > 0 && space >= CHUNK / 2) {
    size_t want = space < CHUNK ? space : CHUNK;
    if ((size_t)available < want) want = available;
    const int got = stream->read(chunk, want);
    if (got > 0) {
      xStreamBufferSend(buffer_, chunk, got, 0);
      lastDataMs_ = millis();
      return;
    }
  }
  if (available <= 0 && (!stream || !stream->connected())) {
    close();
    eof_ = true;  // доиграет буфер и сообщит ended
    return;
  }
  if (available <= 0 && xStreamBufferIsEmpty(buffer_) && millis() - lastDataMs_ >= STALL_MS) {
    close();
    phase_ = Failed;
    post(StreamState::Failed, StreamError::Download);
    return;
  }
  vTaskDelay(pdMS_TO_TICKS(5));
}

void StreamPlayer::close() {
  if (open_) {
    http_.end();
    open_ = false;
  }
}

void StreamPlayer::flush() {
  flushRequest_ = true;
  const uint32_t since = millis();
  while (flushRequest_ && millis() - since < FLUSH_WAIT_MS) {
    vTaskDelay(1);
  }
}
