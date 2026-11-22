#include "SoundFiles.h"

#include <LittleFS.h>
#include <string.h>

#include "esp_heap_caps.h"

namespace {

constexpr const char* FOLDER = "/sounds";
const char* const NAMES[] = {"wake", "error", "thinking", "listen", "attention"};  // порядок Tone
constexpr size_t TONES = sizeof(NAMES) / sizeof(NAMES[0]);
constexpr size_t PATH = 40;

// Путь файла звука tone с расширением ext в buffer.
const char* pathOf(Tone tone, const char* ext, char* buffer) {
  const size_t index = static_cast<size_t>(tone);
  snprintf(buffer, PATH, "%s/%s.%s", FOLDER, index < TONES ? NAMES[index] : "unknown", ext);
  return buffer;
}

bool isHex64(const char* text) {
  if (strlen(text) != 64) return false;
  for (const char* p = text; *p; ++p) {
    if (!((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f'))) return false;
  }
  return true;
}

// Хэш-файл звука в out (65 байт); false — нет или не 64 шестнадцатеричных символа.
bool readHash(Tone tone, char* out) {
  char path[PATH];
  File file = LittleFS.open(pathOf(tone, "sha", path), "r");
  const bool read = file && file.read((uint8_t*)out, 64) == 64;
  file.close();
  out[read ? 64 : 0] = '\0';
  return read && isHex64(out);
}

}  // namespace

void prepareSoundFolder() {
  if (!LittleFS.exists(FOLDER)) {
    LittleFS.mkdir(FOLDER);
  }
}

const char* soundTempPath(Tone tone) {
  static char path[PATH];
  return pathOf(tone, "tmp", path);
}

bool loadSoundFile(Tone tone, StoredSound& out) {
  char pcmPath[PATH];
  if (!LittleFS.exists(pathOf(tone, "pcm", pcmPath))) {
    return false;
  }
  out = StoredSound{tone, nullptr, 0, {}};
  const bool hashOk = readHash(tone, out.sha256);
  File pcm = LittleFS.open(pcmPath, "r");
  const size_t size = pcm ? pcm.size() : 0;
  bool ok = hashOk && size > 0 && size <= MAX_SOUND_BYTES && size % 2 == 0;
  if (ok) {
    out.pcm = (int16_t*)heap_caps_malloc(size, MALLOC_CAP_SPIRAM);
    ok = out.pcm && pcm.read((uint8_t*)out.pcm, size) == size;
  }
  pcm.close();
  if (!ok) {
    heap_caps_free(out.pcm);
    out = StoredSound{tone, nullptr, 0, {}};
    Serial.printf("updater: свой звук %s испорчен — будет встроенный\n", pcmPath);
    removeSoundFile(tone);
    return false;
  }
  out.samples = size / sizeof(int16_t);
  return true;
}

bool commitSoundFile(Tone tone, const char* sha256) {
  char pcmPath[PATH];
  char shaPath[PATH];
  LittleFS.remove(pathOf(tone, "pcm", pcmPath));
  File sha = LittleFS.open(pathOf(tone, "sha", shaPath), "w");
  const bool shaOk = sha && sha.write((const uint8_t*)sha256, 64) == 64;
  sha.close();
  if (!shaOk || !LittleFS.rename(soundTempPath(tone), pcmPath)) {
    removeSoundFile(tone);
    return false;
  }
  return true;
}

void removeSoundFile(Tone tone) {
  char path[PATH];
  LittleFS.remove(pathOf(tone, "pcm", path));
  LittleFS.remove(pathOf(tone, "sha", path));
  LittleFS.remove(soundTempPath(tone));
}
