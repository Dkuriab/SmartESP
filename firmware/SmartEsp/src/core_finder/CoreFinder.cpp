#include "CoreFinder.h"

#include <ESPmDNS.h>
#include <WiFi.h>
#include <mdns.h>

namespace {

constexpr const char* SERVICE = "_smartesp";
constexpr const char* PROTO = "_tcp";
constexpr const char* DEFAULT_PATH = "/device";
constexpr size_t MAX_RESULTS = 8;
constexpr size_t MAX_ADDRESSES = 4;
constexpr uint32_t HOST_QUERY_MS = 1000;  // A-запись, если её не было в ответе
constexpr uint32_t STEP_MS = 100;

// Значение TXT key (или пусто) в out.
void txtValue(const mdns_result_t* result, const char* key, char* out, size_t size) {
  out[0] = '\0';
  for (size_t i = 0; i < result->txt_count; i++) {
    const mdns_txt_item_t& item = result->txt[i];
    if (item.key && item.value && strcmp(item.key, key) == 0) {
      strncpy(out, item.value, size - 1);
      out[size - 1] = '\0';
      return;
    }
  }
}

// IPv4-адреса ответа; нет — спросить A-запись по имени хоста.
size_t addressesOf(const mdns_result_t* result, uint32_t* ips) {
  size_t count = 0;
  for (const mdns_ip_addr_t* a = result->addr; a && count < MAX_ADDRESSES; a = a->next) {
    if (a->addr.type == ESP_IPADDR_TYPE_V4) {
      ips[count++] = a->addr.u_addr.ip4.addr;
    }
  }
  esp_ip4_addr_t ip{};
  if (count == 0 && result->hostname && mdns_query_a(result->hostname, HOST_QUERY_MS, &ip) == ESP_OK) {
    ips[count++] = ip.addr;
  }
  return count;
}

// Ответы mDNS → список ядер (одно ядро на id: оно приходит по каждому интерфейсу).
size_t collect(const mdns_result_t* results, FoundCore* found, size_t capacity) {
  const uint32_t localIp = static_cast<uint32_t>(WiFi.localIP());
  const uint32_t mask = static_cast<uint32_t>(WiFi.subnetMask());
  size_t count = 0;
  for (const mdns_result_t* r = results; r && count < capacity; r = r->next) {
    FoundCore core{};
    txtValue(r, "id", core.id, sizeof(core.id));
    bool duplicate = false;
    for (size_t i = 0; i < count && core.id[0]; i++) {
      duplicate = duplicate || strcmp(found[i].id, core.id) == 0;
    }
    uint32_t ips[MAX_ADDRESSES];
    const size_t ipCount = duplicate || r->port == 0 ? 0 : addressesOf(r, ips);
    const int pick = chooseAddress(ips, ipCount, localIp, mask);
    if (pick < 0) {
      continue;
    }
    core.ip = ips[pick];
    core.port = r->port;
    txtValue(r, "path", core.path, sizeof(core.path));
    if (core.path[0] != '/') {
      strncpy(core.path, DEFAULT_PATH, sizeof(core.path) - 1);
    }
    found[count++] = core;
  }
  return count;
}

}  // namespace

bool CoreFinder::begin(const CoreFinderConfig& config) {
  config_ = config;
  strncpy(preferred_, config.preferredId ? config.preferredId : "", sizeof(preferred_) - 1);
  choice_.setPreferred(preferred_);
  found_ = xQueueCreate(1, sizeof(CoreAddress));
  if (!found_) {
    Serial.println("core_finder: нет памяти под очередь");
    return false;
  }
  return xTaskCreatePinnedToCore(taskEntry, "core_finder", 6144, this, 1, nullptr, 0) == pdPASS;
}

void CoreFinder::setWifiConnected(bool connected) {
  wifiConnected_ = connected;
}

void CoreFinder::setServerConnected(bool connected) {
  serverConnected_ = connected;
}

bool CoreFinder::pollFound(CoreAddress& out) {
  return found_ && xQueueReceive(found_, &out, 0) == pdTRUE;
}

bool CoreFinder::pollRemember(char* id, size_t size) {
  if (size == 0) {
    return false;
  }
  taskENTER_CRITICAL(&rememberLock_);
  const bool has = hasRemember_;
  if (has) {
    strncpy(id, remember_, size - 1);
    id[size - 1] = '\0';
    hasRemember_ = false;
  }
  taskEXIT_CRITICAL(&rememberLock_);
  return has;
}

void CoreFinder::taskEntry(void* self) {
  static_cast<CoreFinder*>(self)->run();
}

void CoreFinder::run() {
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(STEP_MS));
    const bool wifi = wifiConnected_;
    const bool server = serverConnected_;
    if (wifi && !mdnsStarted_) {
      mdnsStarted_ = MDNS.begin(config_.hostname);
      Serial.printf(mdnsStarted_ ? "core_finder: колонка в сети — %s.local\n"
                                 : "core_finder: mDNS не запустился (%s)\n",
                    config_.hostname);
    }
    noteConnection(server);
    if (timer_.due(millis(), wifi && mdnsStarted_, server)) {
      search();
    }
  }
}

// Связь с ядром только что установилась: его id — «своё» ядро (запомнить, если сменилось).
void CoreFinder::noteConnection(bool serverConnected) {
  const bool connectedNow = serverConnected && !wasConnected_;
  wasConnected_ = serverConnected;
  if (!connectedNow || offered_[0] == '\0' || strcmp(offered_, preferred_) == 0) {
    return;
  }
  strncpy(preferred_, offered_, sizeof(preferred_) - 1);
  choice_.setPreferred(preferred_);
  taskENTER_CRITICAL(&rememberLock_);
  memcpy(remember_, preferred_, sizeof(remember_));
  hasRemember_ = true;
  taskEXIT_CRITICAL(&rememberLock_);
}

void CoreFinder::search() {
  mdns_result_t* results = nullptr;
  if (mdns_query_ptr(SERVICE, PROTO, config_.queryMs, MAX_RESULTS, &results) != ESP_OK || !results) {
    Serial.println("core_finder: ядро не найдено");
    if (results) {
      mdns_query_results_free(results);
    }
    return;
  }
  FoundCore found[MAX_RESULTS];
  const size_t count = collect(results, found, MAX_RESULTS);
  mdns_query_results_free(results);
  const int pick = choice_.choose(found, count);
  if (pick < 0 && count == 0) {
    Serial.println("core_finder: ответы есть, но без адреса ядра");
    return;
  }
  if (pick < 0) {
    Serial.printf("core_finder: найдено ядер %u, своего (%s) среди них нет — жду\n", (unsigned)count,
                  preferred_);
    return;
  }
  const FoundCore& core = found[pick];
  CoreAddress address{};
  strncpy(address.id, core.id, sizeof(address.id) - 1);
  IPAddress(core.ip).toString().toCharArray(address.host, sizeof(address.host));
  address.port = core.port;
  strncpy(address.path, core.path, sizeof(address.path) - 1);
  memcpy(offered_, address.id, sizeof(offered_));
  Serial.printf("core_finder: ядро %s — %s:%u\n", address.id, address.host, (unsigned)address.port);
  xQueueOverwrite(found_, &address);
}
