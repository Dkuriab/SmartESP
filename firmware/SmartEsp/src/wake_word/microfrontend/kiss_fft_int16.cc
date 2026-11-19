// Вендорено из pymicro-features 2.0.2 (PyPI, sdist): tensorflow/lite/experimental/
// microfrontend/lib/kiss_fft_int16.cc. Лицензия Apache-2.0 — LICENSE в этой папке.
// Изменено только: пути #include относительные (Arduino собирает лишь src/).
#include <cstdint>

#include "kiss_fft_common.h"

#define FIXED_POINT 16
namespace kissfft_fixed16 {
#include "kissfft/kiss_fft.ipp"
#include "kissfft/kiss_fftr.ipp"
}  // namespace kissfft_fixed16
#undef FIXED_POINT
