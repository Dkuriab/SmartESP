#pragma once

// Шаблон секретов. Скопируйте в secrets.h (он в .gitignore) и заполните.
// Новый секрет добавляется и сюда, и в secrets.h.

#include <stdint.h>

constexpr const char* WIFI_SSID = "";
constexpr const char* WIFI_PASSWORD = "";

// Адрес сервера на ноутбуке в локальной сети, например "192.168.1.10".
constexpr const char* SERVER_HOST = "";
constexpr uint16_t SERVER_PORT = 8765;
