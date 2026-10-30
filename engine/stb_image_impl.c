// stb_image (third_party/stb, pinned in third_party/upstream-lock.json) for lens-ocr outside Windows: PNG, JPEG and BMP
// decoded from memory only (no stdio, no other formats).
#define STBI_ONLY_PNG
#define STBI_ONLY_JPEG
#define STBI_ONLY_BMP
#define STBI_NO_STDIO
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
