#include "CoreChoice.h"

#include <string.h>

void CoreChoice::setPreferred(const char* id) {
  strncpy(preferred_, id ? id : "", sizeof(preferred_) - 1);
  preferred_[sizeof(preferred_) - 1] = '\0';
  misses_ = 0;
}

int CoreChoice::choose(const FoundCore* found, size_t count) {
  if (count == 0) {
    return -1;  // пустой поиск — не промах своего: могла пропасть вся сеть
  }
  if (preferred_[0] == '\0') {
    return 0;
  }
  for (size_t i = 0; i < count; i++) {
    if (strcmp(found[i].id, preferred_) == 0) {
      misses_ = 0;
      return static_cast<int>(i);
    }
  }
  if (misses_ < PREFERRED_MISSES) {
    misses_++;
  }
  return misses_ >= PREFERRED_MISSES ? 0 : -1;
}

int chooseAddress(const uint32_t* ips, size_t count, uint32_t localIp, uint32_t mask) {
  if (count == 0) {
    return -1;
  }
  for (size_t i = 0; i < count; i++) {
    if ((ips[i] & mask) == (localIp & mask)) {
      return static_cast<int>(i);
    }
  }
  return 0;
}
