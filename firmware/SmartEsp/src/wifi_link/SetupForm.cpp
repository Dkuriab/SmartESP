#include "SetupForm.h"

#include <ctype.h>
#include <string.h>

namespace {

constexpr size_t SSID_MAX = 32;
constexpr size_t PASSWORD_MIN = 8;
constexpr size_t PASSWORD_MAX = 63;
constexpr size_t PSK_HEX = 64;

// Начало страницы: стиль, без внешних ресурсов.
constexpr const char* HEAD =
    "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">";
constexpr const char* STYLE =
    "<style>body{font-family:-apple-system,system-ui,sans-serif;margin:0 auto;max-width:28em;"
    "padding:16px;color:#222;background:#fafafa}h1{font-size:1.3em}"
    "button,input{font-size:1em;width:100%;box-sizing:border-box;padding:.7em;margin:.25em 0;"
    "border:1px solid #bbb;border-radius:8px;background:#fff}"
    "button.n{text-align:left}button.s{background:#2a6df4;color:#fff;border:0}"
    "label{display:block;margin-top:.8em}.st{padding:.7em;border-radius:8px;background:#eef}"
    "</style>";

bool isHex(const char* text) {
  for (; *text; text++) {
    if (!isxdigit(static_cast<unsigned char>(*text))) {
      return false;
    }
  }
  return true;
}

void appendNetwork(const ScanEntry& net, std::string& out) {
  out += "<button type=\"button\" class=\"n\" data-s=\"";
  htmlEscape(net.ssid, out);
  out += "\" onclick=\"pick(this)\">";
  htmlEscape(net.ssid, out);
  out += net.open ? " · открытая" : " · 🔒";
  out += net.rssi >= -60 ? " · сильный" : net.rssi >= -75 ? " · средний" : " · слабый";
  out += "</button>";
}

}  // namespace

FormError checkCredentials(const char* ssid, const char* password, WifiCredentials& out) {
  const size_t ssidLength = ssid ? strlen(ssid) : 0;
  const size_t passwordLength = password ? strlen(password) : 0;
  if (ssidLength == 0) {
    return FormError::NoSsid;
  }
  if (ssidLength > SSID_MAX) {
    return FormError::SsidTooLong;
  }
  const bool passphrase = passwordLength >= PASSWORD_MIN && passwordLength <= PASSWORD_MAX;
  const bool psk = passwordLength == PSK_HEX && isHex(password);
  if (passwordLength != 0 && !passphrase && !psk) {
    return FormError::Password;
  }
  memset(&out, 0, sizeof(out));
  memcpy(out.ssid, ssid, ssidLength);
  if (passwordLength) {
    memcpy(out.password, password, passwordLength);
  }
  return FormError::None;
}

const char* formErrorText(FormError error) {
  switch (error) {
    case FormError::None: return "";
    case FormError::NoSsid: return "Выберите сеть или впишите её имя.";
    case FormError::SsidTooLong: return "Имя сети длиннее 32 байт.";
    case FormError::Password: return "Пароль Wi-Fi — от 8 до 63 знаков (или пусто для открытой сети).";
  }
  return "";
}

void htmlEscape(const char* text, std::string& out) {
  for (; text && *text; text++) {
    switch (*text) {
      case '&': out += "&amp;"; break;
      case '<': out += "&lt;"; break;
      case '>': out += "&gt;"; break;
      case '"': out += "&quot;"; break;
      case '\'': out += "&#39;"; break;
      default: out += *text; break;
    }
  }
}

size_t mergeScan(ScanEntry* nets, size_t count) {
  size_t kept = 0;
  for (size_t i = 0; i < count; i++) {
    if (nets[i].ssid[0] == '\0') {
      continue;
    }
    size_t j = 0;
    while (j < kept && strcmp(nets[j].ssid, nets[i].ssid) != 0) {
      j++;
    }
    if (j == kept) {
      nets[kept++] = nets[i];
    } else if (nets[i].rssi > nets[j].rssi) {
      nets[j] = nets[i];
    }
  }
  // Вставками по силе: сетей десятки, порядок равных сохраняется.
  for (size_t i = 1; i < kept; i++) {
    const ScanEntry net = nets[i];
    size_t j = i;
    for (; j > 0 && nets[j - 1].rssi < net.rssi; j--) {
      nets[j] = nets[j - 1];
    }
    nets[j] = net;
  }
  return kept;
}

std::string setupPage(const char* name, const ScanEntry* nets, size_t count, bool scanning, const char* status) {
  std::string page = HEAD;
  if (scanning) {
    page += "<meta http-equiv=\"refresh\" content=\"3\">";
  }
  page += "<title>Настройка колонки</title>";
  page += STYLE;
  page += "</head><body><h1>Колонка ";
  htmlEscape(name, page);
  page += "</h1><p>Выберите домашнюю сеть Wi-Fi и введите пароль — колонка подключится к ней "
          "и сама найдёт ядро на Mac.</p>";
  if (status && *status) {
    page += "<p class=\"st\">";
    htmlEscape(status, page);
    page += "</p>";
  }
  if (scanning) {
    page += "<p>Ищу сети…</p>";
  }
  for (size_t i = 0; i < count; i++) {
    appendNetwork(nets[i], page);
  }
  page += "<p><a href=\"/?scan=1\">Обновить список</a></p>"
          "<form method=\"post\" action=\"/save\">"
          "<label>Сеть<input name=\"ssid\" id=\"s\" maxlength=\"32\" required autocapitalize=\"off\"></label>"
          "<label>Пароль<input name=\"password\" id=\"p\" type=\"password\" maxlength=\"64\"></label>"
          "<button class=\"s\">Сохранить</button></form>"
          "<script>function pick(b){document.getElementById('s').value=b.dataset.s;"
          "document.getElementById('p').focus()}</script></body></html>";
  return page;
}

std::string savedPage(const char* ssid) {
  std::string page = HEAD;
  page += "<title>Настройка колонки</title>";
  page += STYLE;
  page += "</head><body><h1>Сохранено</h1><p>Колонка подключается к сети «";
  htmlEscape(ssid, page);
  page += "».</p><p class=\"st\" id=\"st\">Подключаюсь…</p><p><a href=\"/\">Выбрать другую сеть</a></p>"
          "<script>function poll(){fetch('/status').then(function(r){return r.text()})"
          ".then(function(t){document.getElementById('st').textContent=t})"
          ".catch(function(){});setTimeout(poll,2000)}poll()</script></body></html>";
  return page;
}
