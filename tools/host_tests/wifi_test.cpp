// Тесты wifi_link: когда пробовать сеть и открывать точку настройки (LinkPlan),
// проверка формы и страница настройки (SetupForm).

#include <cstring>
#include <string>

#include "test.h"
#include "wifi_link/LinkPlan.h"
#include "wifi_link/SetupForm.h"

namespace {

constexpr uint32_t PORTAL_AFTER = 120000;
constexpr uint32_t LINGER = 15000;

ScanEntry entry(const char* ssid, int8_t rssi, bool open = false) {
  ScanEntry e{};
  std::strncpy(e.ssid, ssid, sizeof(e.ssid) - 1);
  e.rssi = rssi;
  e.open = open;
  return e;
}

}  // namespace

TEST(plan_without_network_opens_portal_at_once) {
  LinkPlan plan;
  plan.begin(0, false);
  CHECK(!plan.update(0, false));
  CHECK(plan.portalOpen());
  CHECK(!plan.update(60000, false));  // пробовать нечего
}

TEST(plan_tries_at_once_then_backs_off) {
  LinkPlan plan;
  plan.begin(0, true);
  CHECK(plan.update(0, false));       // первая попытка сразу
  CHECK(!plan.update(4999, false));
  CHECK(plan.update(5000, false));    // через 5 с
  CHECK(!plan.update(14999, false));
  CHECK(plan.update(15000, false));   // затем 10 с
  CHECK(plan.update(35000, false));   // 20 с
  CHECK(plan.update(65000, false));   // 30 с — предел
  CHECK(!plan.update(94999, false));
  CHECK(plan.update(95000, false));
}

TEST(plan_opens_portal_after_two_minutes_and_keeps_trying) {
  LinkPlan plan;
  plan.begin(0, true);
  plan.update(0, false);
  plan.update(PORTAL_AFTER - 1, false);
  CHECK(!plan.portalOpen());
  plan.update(PORTAL_AFTER, false);
  CHECK(plan.portalOpen());
  bool tried = false;
  for (uint32_t t = PORTAL_AFTER; t < PORTAL_AFTER + 31000; t += 100) {
    tried = plan.update(t, false) || tried;
  }
  CHECK(tried);  // при открытой точке сохранённая сеть пробуется дальше
}

TEST(plan_closes_portal_after_linger_when_connected) {
  LinkPlan plan;
  plan.begin(0, false);
  plan.update(0, false);
  plan.setNetwork(1000);              // первую попытку wifi_link делает сам
  CHECK(!plan.update(1000, false));
  CHECK(plan.update(6000, false));    // следующая — через 5 с
  plan.update(3000, true);
  CHECK(plan.portalOpen());          // телефону видно «Подключено»
  plan.update(3000 + LINGER - 1, true);
  CHECK(plan.portalOpen());
  plan.update(3000 + LINGER, true);
  CHECK(!plan.portalOpen());
}

TEST(plan_short_connection_does_not_close_portal) {
  LinkPlan plan;
  plan.begin(0, true);
  plan.update(PORTAL_AFTER, false);
  CHECK(plan.portalOpen());
  plan.update(PORTAL_AFTER + 1000, true);
  plan.update(PORTAL_AFTER + 2000, false);  // связь мигнула
  plan.update(PORTAL_AFTER + 1000 + LINGER, false);
  CHECK(plan.portalOpen());
}

TEST(plan_lost_connection_retries_and_opens_portal_after_two_minutes) {
  LinkPlan plan;
  plan.begin(0, true);
  plan.update(0, false);
  plan.update(2000, true);
  CHECK(!plan.update(100000, true));
  CHECK(!plan.update(100001, false));  // пропала: первая попытка через 5 с
  CHECK(plan.update(105001, false));
  plan.update(100001 + PORTAL_AFTER - 1, false);
  CHECK(!plan.portalOpen());
  plan.update(100001 + PORTAL_AFTER, false);
  CHECK(plan.portalOpen());
}

TEST(plan_survives_millis_wrap) {
  LinkPlan plan;
  const uint32_t start = 0xFFFFFFFFu - 1000;
  plan.begin(start, true);
  CHECK(plan.update(start, false));
  CHECK(plan.update(start + 5000, false));  // переполнение millis() между вызовами
  CHECK(!plan.portalOpen());
}

TEST(form_accepts_wpa_and_open_networks) {
  WifiCredentials out{};
  CHECK(checkCredentials("Home", "secret12", out) == FormError::None);
  CHECK_EQ(std::string(out.ssid), "Home");
  CHECK_EQ(std::string(out.password), "secret12");
  CHECK(checkCredentials("Кафе & Co+%", "", out) == FormError::None);  // открытая сеть
  CHECK_EQ(std::string(out.ssid), "Кафе & Co+%");
  CHECK_EQ(std::string(out.password), "");
  const std::string psk(64, 'a');
  CHECK(checkCredentials("Home", psk.c_str(), out) == FormError::None);  // ключ 64 hex
}

TEST(form_rejects_bad_lengths) {
  WifiCredentials out{};
  CHECK(checkCredentials("", "secret12", out) == FormError::NoSsid);
  CHECK(checkCredentials(nullptr, "secret12", out) == FormError::NoSsid);
  CHECK(checkCredentials(std::string(33, 's').c_str(), "secret12", out) == FormError::SsidTooLong);
  CHECK(checkCredentials(std::string(32, 's').c_str(), "secret12", out) == FormError::None);
  CHECK(checkCredentials("Home", "short", out) == FormError::Password);
  CHECK(checkCredentials("Home", std::string(64, 'z').c_str(), out) == FormError::Password);  // не hex
  CHECK(checkCredentials("Home", std::string(65, 'a').c_str(), out) == FormError::Password);
  CHECK(checkCredentials("Home", std::string(63, 'z').c_str(), out) == FormError::None);
  CHECK(std::strlen(formErrorText(FormError::Password)) > 0);
}

TEST(html_escape_covers_markup_and_quotes) {
  std::string out;
  htmlEscape("<a href=\"x\">'&'</a>", out);
  CHECK_EQ(out, "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
}

TEST(scan_merge_dedupes_sorts_and_drops_hidden) {
  ScanEntry nets[5] = {entry("Home", -70), entry("", -30), entry("Cafe", -50, true), entry("Home", -40),
                       entry("Far", -90)};
  const size_t n = mergeScan(nets, 5);
  CHECK_EQ(n, 3u);
  CHECK_EQ(std::string(nets[0].ssid), "Home");  // сильнейшая копия, сверху
  CHECK_EQ(nets[0].rssi, -40);
  CHECK_EQ(std::string(nets[1].ssid), "Cafe");
  CHECK(nets[1].open);
  CHECK_EQ(std::string(nets[2].ssid), "Far");
}

TEST(setup_page_escapes_ssids_and_has_form) {
  ScanEntry nets[1] = {entry("<b>\"Evil\"</b>", -50)};
  const std::string page = setupPage("Kuzya-ab12", nets, 1, false, "");
  CHECK(page.find("<b>\"Evil\"") == std::string::npos);
  CHECK(page.find("&lt;b&gt;&quot;Evil&quot;&lt;/b&gt;") != std::string::npos);
  CHECK(page.find("action=\"/save\"") != std::string::npos);
  CHECK(page.find("name=\"ssid\"") != std::string::npos);
  CHECK(page.find("name=\"password\"") != std::string::npos);
  CHECK(page.find("Kuzya-ab12") != std::string::npos);
  CHECK(page.find("://") == std::string::npos);  // без внешних ресурсов
}

TEST(setup_page_while_scanning_refreshes_itself) {
  const std::string page = setupPage("Kuzya-ab12", nullptr, 0, true, "");
  CHECK(page.find("http-equiv=\"refresh\"") != std::string::npos);
}

TEST(saved_page_names_network_and_polls_status) {
  const std::string page = savedPage("Дом & сад");
  CHECK(page.find("Дом &amp; сад") != std::string::npos);
  CHECK(page.find("/status") != std::string::npos);
}
