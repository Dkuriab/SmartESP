// Запускает все зарегистрированные тесты. Код выхода ≠ 0, если хоть один упал.

#include "test.h"

int main() {
  int failed = 0;
  for (const TestCase& test : testRegistry()) {
    currentTestFailed() = false;
    test.fn();
    if (currentTestFailed()) {
      std::printf("FAIL %s\n", test.name);
      failed++;
    }
  }
  std::printf("%zu tests, %d failed\n", testRegistry().size(), failed);
  return failed == 0 ? 0 : 1;
}
