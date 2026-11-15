#pragma once

// Минимальная обвязка для тестов на ноутбуке (без внешних зависимостей).
// TEST(name) { CHECK(...); CHECK_EQ(a, b); }  — запуск: tools/host_tests/run.sh

#include <cstdio>
#include <vector>

struct TestCase {
  const char* name;
  void (*fn)();
};

inline std::vector<TestCase>& testRegistry() {
  static std::vector<TestCase> tests;
  return tests;
}

inline bool& currentTestFailed() {
  static bool failed = false;
  return failed;
}

struct TestRegistrar {
  TestRegistrar(const char* name, void (*fn)()) { testRegistry().push_back({name, fn}); }
};

#define TEST(name)                                       \
  static void name();                                    \
  static TestRegistrar registrar_##name(#name, name);    \
  static void name()

#define CHECK(cond)                                                         \
  do {                                                                      \
    if (!(cond)) {                                                          \
      std::printf("    %s:%d: CHECK(%s)\n", __FILE__, __LINE__, #cond);     \
      currentTestFailed() = true;                                           \
    }                                                                       \
  } while (0)

#define CHECK_EQ(a, b)                                                      \
  do {                                                                      \
    if (!((a) == (b))) {                                                    \
      std::printf("    %s:%d: CHECK_EQ(%s, %s)\n", __FILE__, __LINE__, #a, #b); \
      currentTestFailed() = true;                                           \
    }                                                                       \
  } while (0)
