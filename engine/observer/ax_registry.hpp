#pragma once
// The AX window element behind a Window id (macOS): owned by os_window_mac.mm's registry; never release the result.
#include "os_window.hpp"
#include <ApplicationServices/ApplicationServices.h>
namespace lens::observe {
AXUIElementRef ax_window(Window id);
}
