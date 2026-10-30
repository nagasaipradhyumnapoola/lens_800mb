#pragma once
// The AT-SPI frame behind a Window id (Linux): owned by os_window_linux.cpp's registry; never unref the result.
#include "os_window.hpp"
#include <atspi/atspi.h>
namespace lens::observe {
AtspiAccessible* atspi_frame(Window id);
}
