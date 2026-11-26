#include "SearchTimer.h"

SearchTimer::SearchTimer(uint32_t firstMs, uint32_t maxMs) : firstMs_(firstMs), maxMs_(maxMs) {}

bool SearchTimer::due(uint32_t nowMs, bool wifiConnected, bool serverConnected) {
  if (!wifiConnected || serverConnected) {
    waiting_ = false;
    return false;
  }
  if (!waiting_) {
    waiting_ = true;
    lastMs_ = nowMs;
    delayMs_ = searched_ ? firstMs_ : 0;
  }
  if (nowMs - lastMs_ < delayMs_) {
    return false;
  }
  if (delayMs_ == 0) {
    delayMs_ = firstMs_;
  } else {
    delayMs_ = delayMs_ * 2 < maxMs_ ? delayMs_ * 2 : maxMs_;
  }
  lastMs_ = nowMs;
  searched_ = true;
  return true;
}
