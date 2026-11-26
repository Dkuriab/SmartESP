// Тесты core_finder: выбор ядра из найденных, выбор адреса в своей подсети, паузы поиска.

#include <cstring>

#include "core_finder/CoreChoice.h"
#include "core_finder/SearchTimer.h"
#include "test.h"

namespace {

FoundCore core(const char* id) {
  FoundCore c{};
  std::strncpy(c.id, id, sizeof(c.id) - 1);
  return c;
}

// IPv4 a.b.c.d так же, как в памяти lwip (байты по порядку).
uint32_t ip(uint8_t a, uint8_t b, uint8_t c, uint8_t d) {
  const uint8_t bytes[4] = {a, b, c, d};
  uint32_t value;
  std::memcpy(&value, bytes, 4);
  return value;
}

}  // namespace

TEST(choice_without_preferred_takes_first) {
  CoreChoice choice;
  FoundCore found[2] = {core("aaa"), core("bbb")};
  CHECK_EQ(choice.choose(found, 2), 0);
  CHECK_EQ(choice.choose(found, 0), -1);
}

TEST(choice_prefers_remembered_core) {
  CoreChoice choice;
  choice.setPreferred("bbb");
  FoundCore found[3] = {core("aaa"), core("bbb"), core("")};
  CHECK_EQ(choice.choose(found, 3), 1);
}

TEST(choice_waits_for_own_core_before_falling_back) {
  CoreChoice choice;
  choice.setPreferred("mine");
  FoundCore others[1] = {core("other")};
  CHECK_EQ(choice.choose(others, 1), -1);  // своё на миг не ответило — не уходим
  CHECK_EQ(choice.choose(others, 1), -1);
  CHECK_EQ(choice.choose(others, 1), 0);   // третий поиск подряд без своего — берём чужое
}

TEST(choice_resets_misses_when_own_core_answers) {
  CoreChoice choice;
  choice.setPreferred("mine");
  FoundCore others[1] = {core("other")};
  FoundCore both[2] = {core("other"), core("mine")};
  CHECK_EQ(choice.choose(others, 1), -1);
  CHECK_EQ(choice.choose(others, 1), -1);
  CHECK_EQ(choice.choose(both, 2), 1);
  CHECK_EQ(choice.choose(others, 1), -1);  // счёт промахов заново
}

TEST(choice_empty_search_is_not_a_miss) {
  CoreChoice choice;
  choice.setPreferred("mine");
  FoundCore others[1] = {core("other")};
  CHECK_EQ(choice.choose(others, 1), -1);
  CHECK_EQ(choice.choose(others, 0), -1);
  CHECK_EQ(choice.choose(others, 0), -1);
  CHECK_EQ(choice.choose(others, 1), -1);  // второй промах, не третий
}

TEST(address_in_own_subnet_wins) {
  const uint32_t mask = ip(255, 255, 255, 0);
  const uint32_t local = ip(192, 168, 1, 50);
  const uint32_t ips[3] = {ip(10, 8, 0, 2), ip(192, 168, 64, 1), ip(192, 168, 1, 10)};  // VPN, мост ВМ, Wi-Fi
  CHECK_EQ(chooseAddress(ips, 3, local, mask), 2);
  const uint32_t foreign[2] = {ip(10, 8, 0, 2), ip(172, 16, 0, 1)};
  CHECK_EQ(chooseAddress(foreign, 2, local, mask), 0);  // своей подсети нет — первый
  CHECK_EQ(chooseAddress(ips, 0, local, mask), -1);
}

TEST(search_first_at_once_then_backs_off) {
  SearchTimer timer;
  CHECK(!timer.due(0, false, false));    // нет Wi-Fi — не ищем
  CHECK(timer.due(100, true, false));    // первый поиск сразу
  CHECK(!timer.due(5099, true, false));
  CHECK(timer.due(5100, true, false));   // 5 с
  CHECK(!timer.due(15099, true, false));
  CHECK(timer.due(15100, true, false));  // 10 с
  CHECK(timer.due(35100, true, false));  // 20 с
  CHECK(timer.due(65100, true, false));  // 30 с — предел
  CHECK(timer.due(95100, true, false));
}

TEST(search_stops_while_connected_and_resumes_after_loss) {
  SearchTimer timer;
  CHECK(timer.due(0, true, false));
  CHECK(!timer.due(1000, true, true));    // связь с ядром есть
  CHECK(!timer.due(100000, true, true));
  CHECK(!timer.due(100001, true, false)); // пропала: server_link сначала сам переподключается
  CHECK(!timer.due(105000, true, false));
  CHECK(timer.due(105001, true, false));  // через 5 с — ищем (мог смениться IP Mac)
}
