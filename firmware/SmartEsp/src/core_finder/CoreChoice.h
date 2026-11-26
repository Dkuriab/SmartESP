#pragma once

// Внутренний файл модуля core_finder: какое ядро из найденных взять и по какому адресу.
// Своё ядро (id, к которому колонка подключалась в прошлый раз) — всегда оно. Своего нет,
// а другие есть — первые 2 поиска ждём (своё могло на миг не ответить), с 3-го подряд берём
// первое найденное. Чистая логика без Arduino — тестируется на ноутбуке.

#include <stddef.h>
#include <stdint.h>

// Ядро из ответа mDNS (адрес уже выбран).
struct FoundCore {
  char id[33];      // TXT id; пусто — ядро его не сообщило
  uint32_t ip;      // IPv4 в порядке байт lwip
  uint16_t port;
  char path[32];    // TXT path
};

class CoreChoice {
 public:
  // Сколько поисков подряд своё ядро может не отвечать, пока колонка ждёт его.
  static constexpr uint8_t PREFERRED_MISSES = 3;

  // Своё ядро (пусто — нет, берётся первое найденное).
  void setPreferred(const char* id);

  // Индекс выбранного ядра в found или -1 (ничего не найдено или ждём своё).
  int choose(const FoundCore* found, size_t count);

 private:
  char preferred_[33] = {};
  uint8_t misses_ = 0;
};

// Индекс адреса в своей подсети (localIp & mask) — у Mac их бывает несколько (Wi-Fi, VPN,
// мост виртуальных машин); такого нет — 0 (первый); пусто — -1.
int chooseAddress(const uint32_t* ips, size_t count, uint32_t localIp, uint32_t mask);
