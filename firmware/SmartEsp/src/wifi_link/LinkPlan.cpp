#include "LinkPlan.h"

LinkPlan::LinkPlan(uint32_t portalAfterMs, uint32_t lingerMs, uint32_t firstRetryMs, uint32_t maxRetryMs)
    : portalAfterMs_(portalAfterMs),
      lingerMs_(lingerMs),
      firstRetryMs_(firstRetryMs),
      maxRetryMs_(maxRetryMs),
      retryMs_(firstRetryMs) {}

void LinkPlan::begin(uint32_t nowMs, bool hasNetwork) {
  hasNetwork_ = hasNetwork;
  portal_ = !hasNetwork;
  connected_ = false;
  attemptNow_ = hasNetwork;
  retryMs_ = firstRetryMs_;
  lastAttemptMs_ = nowMs;
  downSinceMs_ = nowMs;
}

void LinkPlan::setNetwork(uint32_t nowMs) {
  hasNetwork_ = true;
  attemptNow_ = true;
  retryMs_ = firstRetryMs_;
  lastAttemptMs_ = nowMs;
}

bool LinkPlan::update(uint32_t nowMs, bool connected) {
  if (connected) {
    if (!connected_) {
      connected_ = true;
      connectedSinceMs_ = nowMs;
    }
    retryMs_ = firstRetryMs_;
    attemptNow_ = false;
    if (portal_ && nowMs - connectedSinceMs_ >= lingerMs_) {
      portal_ = false;
    }
    return false;
  }
  if (connected_) {  // связь пропала: первая попытка — через паузу (вдруг вернётся сама)
    connected_ = false;
    downSinceMs_ = nowMs;
    lastAttemptMs_ = nowMs;
  }
  if (!hasNetwork_) {
    portal_ = true;
    return false;
  }
  if (nowMs - downSinceMs_ >= portalAfterMs_) {
    portal_ = true;
  }
  if (attemptNow_) {
    attemptNow_ = false;
    lastAttemptMs_ = nowMs;
    return true;
  }
  if (nowMs - lastAttemptMs_ < retryMs_) {
    return false;
  }
  lastAttemptMs_ = nowMs;
  retryMs_ = retryMs_ * 2 < maxRetryMs_ ? retryMs_ * 2 : maxRetryMs_;
  return true;
}

bool LinkPlan::portalOpen() const {
  return portal_;
}
