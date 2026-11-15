// SmartESP — связка модулей. Здесь нет логики: только создание модулей,
// вызовы begin()/loop() и передача данных между модулями.
// Правила — CLAUDE.md, устройство — docs/superpowers/specs/.

#include "secrets.h"
#include "src/common/Types.h"

constexpr const char* FW_VERSION = "0.1.0";

void setup() {
  Serial.begin(115200);
  Serial.printf("SmartESP %s\n", FW_VERSION);
}

void loop() {}
