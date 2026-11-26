#pragma once

// Внутренний файл модуля wifi_link: проверка формы настройки, список найденных сетей и
// страницы портала (по-русски, без внешних ресурсов). Чистая логика без Arduino —
// тестируется на ноутбуке.

#include <stddef.h>
#include <stdint.h>
#include <string>
#include "../common/Types.h"

// Сеть из сканирования.
struct ScanEntry {
  char ssid[33];
  int8_t rssi;  // дБм
  bool open;    // без пароля
};

enum class FormError : uint8_t {
  None,
  NoSsid,       // сеть не выбрана
  SsidTooLong,  // больше 32 байт
  Password,     // пароль не пустой и не 8..63 знака (и не 64 hex)
};

// Проверяет сеть и пароль из формы (уже раскодированные); годные — в out.
FormError checkCredentials(const char* ssid, const char* password, WifiCredentials& out);

// Текст ошибки для страницы.
const char* formErrorText(FormError error);

// Дописывает text в out, экранируя & < > " ' для HTML (и в тексте, и в атрибутах).
void htmlEscape(const char* text, std::string& out);

// Убирает скрытые сети (пустой SSID) и повторы (оставляет сильнейшую), сортирует по силе.
// Возвращает новое число сетей в nets.
size_t mergeScan(ScanEntry* nets, size_t count);

// Страница настройки: name — имя точки, nets — найденные сети, scanning — поиск идёт
// (страница обновится сама), status — строка состояния (пусто — нет).
std::string setupPage(const char* name, const ScanEntry* nets, size_t count, bool scanning, const char* status);

// Страница «Сохранено»: опрашивает /status и показывает, подключилась ли колонка.
std::string savedPage(const char* ssid);
