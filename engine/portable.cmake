# Portable build (Linux, macOS, iOS, Android) of the memory engine (store, retrieval, ASR) and the spoken-reply worker.
# Dependencies come from the system or the platform SDK: OpenSSL, SQLCipher, zstd, utf8proc, nlohmann-json, libsecret (Linux),
# Security.framework (Apple); ONNX Runtime from LENS_ORT_DIR (include/ and lib/ of an official release).
# Worker processes and libraries share one output folder, as on Windows (sibling workers, ggml CPU variants).
enable_language(C)  # SQLCipher's amalgamation and ggml are C
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(CMAKE_BUILD_RPATH "$ORIGIN")
if(APPLE)
  set(CMAKE_BUILD_RPATH "@loader_path")
endif()
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(LENS_WARN -Wall -Wextra -Wno-unused-parameter -Wno-misleading-indentation)  # the code base writes short if/for bodies on one line
set(LENS_ORT_DIR "" CACHE PATH "ONNX Runtime release folder (include/, lib/)")

find_package(nlohmann_json CONFIG REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(utf8proc CONFIG QUIET)  # grapheme clusters (UAX #29); vcpkg's package, else pkg-config
if(TARGET utf8proc::utf8proc)
  set(LENS_UTF8PROC utf8proc::utf8proc)
elseif(TARGET utf8proc)
  set(LENS_UTF8PROC utf8proc)
else()
  find_package(PkgConfig REQUIRED)
  pkg_check_modules(UTF8PROC REQUIRED IMPORTED_TARGET libutf8proc)
  set(LENS_UTF8PROC PkgConfig::UTF8PROC)
endif()
find_package(PkgConfig)
# SQLCipher: the system package (Linux, Homebrew), or the pinned amalgamation (Android, iOS; ci/sqlcipher/amalgamation.sh).
set(LENS_SQLCIPHER_AMALGAMATION "" CACHE PATH "folder with SQLCipher's sqlite3.c and include/sqlcipher/sqlite3.h")
if(LENS_SQLCIPHER_AMALGAMATION)
  add_library(lens-sqlcipher STATIC "${LENS_SQLCIPHER_AMALGAMATION}/sqlite3.c")
  target_include_directories(lens-sqlcipher PUBLIC "${LENS_SQLCIPHER_AMALGAMATION}/include")
  # Same definitions as the Windows build (third_party/overlays/sqlcipher/CMakeLists.txt, fts5 feature).
  target_compile_definitions(lens-sqlcipher PRIVATE SQLITE_HAS_CODEC SQLCIPHER_CRYPTO_OPENSSL SQLITE_TEMP_STORE=2 SQLITE_THREADSAFE=1
    SQLITE_ENABLE_FTS5 SQLITE_ENABLE_JSON1 SQLITE_ENABLE_RTREE SQLITE_ENABLE_UNLOCK_NOTIFY SQLITE_ENABLE_COLUMN_METADATA
    SQLITE_EXTRA_INIT=sqlcipher_extra_init SQLITE_EXTRA_SHUTDOWN=sqlcipher_extra_shutdown)
  find_package(Threads REQUIRED)
  target_link_libraries(lens-sqlcipher PUBLIC OpenSSL::Crypto Threads::Threads ${CMAKE_DL_LIBS})
  if(NOT APPLE AND NOT ANDROID)
    target_link_libraries(lens-sqlcipher PUBLIC m)
  endif()
  if(ANDROID)
    target_link_libraries(lens-sqlcipher PUBLIC log)  # sqlcipher_log writes to logcat
  endif()
  set(LENS_SQLCIPHER lens-sqlcipher)
else()
  pkg_check_modules(SQLCIPHER REQUIRED IMPORTED_TARGET sqlcipher)
  set(LENS_SQLCIPHER PkgConfig::SQLCIPHER)
endif()
find_package(zstd CONFIG QUIET)
if(TARGET zstd::libzstd_static)
  set(LENS_ZSTD zstd::libzstd_static)
elseif(TARGET zstd::libzstd)
  set(LENS_ZSTD zstd::libzstd)
else()
  pkg_check_modules(ZSTD REQUIRED IMPORTED_TARGET libzstd)
  set(LENS_ZSTD PkgConfig::ZSTD)
endif()

add_library(lens-embedding STATIC platform.cpp e5_tokenizer.cpp onnx_model.cpp embedder.cpp reranker.cpp)
target_include_directories(lens-embedding PUBLIC "${LENS_ORT_DIR}/include")
target_link_libraries(lens-embedding PUBLIC nlohmann_json::nlohmann_json ${LENS_UTF8PROC} ${CMAKE_DL_LIBS})
target_compile_options(lens-embedding PRIVATE ${LENS_WARN})

# Per-OS master key for wrapping the database key (adapters/posix/key_store.cpp).
if(APPLE)
  set(LENS_MASTER_KEY "${LENS_ROOT}/adapters/apple/master_key.cpp")
  set(LENS_MASTER_KEY_LIBS "-framework Security" "-framework CoreFoundation")
elseif(ANDROID)
  set(LENS_MASTER_KEY "${LENS_ROOT}/adapters/android/master_key.cpp")
  set(LENS_MASTER_KEY_LIBS "")
else()
  pkg_check_modules(LIBSECRET REQUIRED IMPORTED_TARGET libsecret-1)
  set(LENS_MASTER_KEY "${LENS_ROOT}/adapters/linux/master_key.cpp")
  set(LENS_MASTER_KEY_LIBS PkgConfig::LIBSECRET)
endif()
add_library(lens-store STATIC store.cpp memory_query.cpp retrieval.cpp temporal.cpp query_understanding.cpp text_codec.cpp episodes.cpp
  semantic_extract.cpp memory_layers.cpp lifecycle.cpp user_memory.cpp "${LENS_ROOT}/adapters/posix/key_store.cpp" "${LENS_MASTER_KEY}")
target_compile_definitions(lens-store PRIVATE SQLITE_HAS_CODEC)
target_link_libraries(lens-store PUBLIC lens-embedding ${LENS_SQLCIPHER} OpenSSL::Crypto ${LENS_ZSTD} ${LENS_MASTER_KEY_LIBS})
target_compile_options(lens-store PRIVATE ${LENS_WARN})

# LENS_CORE_ONLY (iOS, Android app libraries): the memory core only; the app links it and has no worker processes.
option(LENS_CORE_ONLY "build only lens-store and lens-embedding" OFF)
if(LENS_CORE_ONLY)
  return()
endif()

# whisper.cpp as shared libraries with runtime-selected ggml CPU variants: no binary requires AVX/AVX2 or a specific ARM
# feature unconditionally (docs/LENS_V1_SPEC.md §15).
set(BUILD_SHARED_LIBS ON CACHE BOOL "" FORCE)
set(GGML_BACKEND_DL ON CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)  # as on Windows (third_party/upstream-lock.json); whisper's own thread pool
set(GGML_METAL OFF CACHE BOOL "" FORCE)   # CPU-only on every OS (Apple defaults to Metal and Accelerate BLAS)
set(GGML_BLAS OFF CACHE BOOL "" FORCE)
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|aarch64|arm64")
  set(GGML_CPU_ALL_VARIANTS ON CACHE BOOL "" FORCE)
endif()
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
add_subdirectory("${LENS_ROOT}/third_party/whisper.cpp" whisper)  # all targets: the CPU variants are loaded, not linked
add_library(lens-whisper-common STATIC "${LENS_ROOT}/third_party/whisper.cpp/examples/common.cpp"
  "${LENS_ROOT}/third_party/whisper.cpp/examples/common-whisper.cpp")  # miniaudio decoder + WAV helpers
target_include_directories(lens-whisper-common PUBLIC "${LENS_ROOT}/third_party/whisper.cpp/examples")
target_link_libraries(lens-whisper-common PUBLIC whisper)

add_executable(lens-engine main.cpp asr.cpp)
target_link_libraries(lens-engine PRIVATE lens-store lens-whisper-common whisper)
target_compile_options(lens-engine PRIVATE ${LENS_WARN})

add_executable(lens-tts tts_main.cpp g2p_en.cpp)
target_link_libraries(lens-tts PRIVATE lens-embedding)
target_compile_options(lens-tts PRIVATE ${LENS_WARN})

# Speech input (lens-sherpa): sherpa-onnx is loaded at run time, so only its C API header is needed (ci/fetch_sherpa_header.sh).
set(LENS_SHERPA_INCLUDE "" CACHE PATH "folder holding sherpa-onnx/c-api/c-api.h")
if(LENS_SHERPA_INCLUDE)
  add_executable(lens-sherpa sherpa_main.cpp)
  target_include_directories(lens-sherpa PRIVATE "${LENS_SHERPA_INCLUDE}")
  target_link_libraries(lens-sherpa PRIVATE lens-embedding lens-whisper-common)  # platform layer; miniaudio decoder
  target_compile_options(lens-sherpa PRIVATE ${LENS_WARN})
endif()

# Screen text (lens-ocr): PaddleOCR detector and recognisers through ONNX Runtime; images decoded by stb_image (ci/fetch_stb.sh).
set(LENS_STB_DIR "${LENS_ROOT}/third_party/stb")
if(EXISTS "${LENS_STB_DIR}/stb_image.h")
  add_executable(lens-ocr ocr_main.cpp stb_image_impl.c)
  target_include_directories(lens-ocr PRIVATE "${LENS_STB_DIR}")
  target_link_libraries(lens-ocr PRIVATE lens-embedding)  # platform layer, ONNX Runtime headers
  target_compile_options(lens-ocr PRIVATE $<$<COMPILE_LANGUAGE:CXX>:${LENS_WARN}>)
  set_source_files_properties(stb_image_impl.c PROPERTIES COMPILE_OPTIONS -w)  # upstream code, unmodified
endif()

# Voice capture (lens-voice): miniaudio microphone (ALSA/PulseAudio, Core Audio, AAudio) + VAD -> engine ingest_audio;
# speaker profiles sealed under the OS-held master key. miniaudio is compiled here, so no lens-whisper-common.
add_executable(lens-voice voice/voice_main.cpp agent/os.cpp)
target_include_directories(lens-voice PRIVATE "${LENS_ROOT}/third_party/whisper.cpp/examples")
if(LENS_SHERPA_INCLUDE)
  target_include_directories(lens-voice PRIVATE "${LENS_SHERPA_INCLUDE}")  # speaker verification, loaded at run time
endif()
target_link_libraries(lens-voice PRIVATE lens-store OpenSSL::Crypto Threads::Threads ${CMAKE_DL_LIBS})
if(APPLE)
  target_link_libraries(lens-voice PRIVATE "-framework CoreFoundation" "-framework CoreAudio" "-framework AudioToolbox")
elseif(NOT ANDROID)
  target_link_libraries(lens-voice PRIVATE m)
endif()
target_compile_options(lens-voice PRIVATE ${LENS_WARN})

# Always-on agent (lens-agent): engine host, resource governor, spoken replies, user-only Unix socket (agent/os.cpp).
find_package(Threads REQUIRED)
add_executable(lens-agent agent/agent_main.cpp agent/child_process.cpp agent/actions.cpp agent/os.cpp)
target_link_libraries(lens-agent PRIVATE lens-embedding OpenSSL::Crypto Threads::Threads)
target_compile_options(lens-agent PRIVATE ${LENS_WARN})

# Linux screen observer (lens-observer): AT-SPI text of the followed frame, X11 capture for the OCR fallback; built when
# libatspi and Xlib are installed. lens-observer-testapp is the synthetic GTK window its tests read.
if(NOT APPLE AND NOT ANDROID)
  pkg_check_modules(LENS_ATSPI IMPORTED_TARGET atspi-2 gobject-2.0 glib-2.0 x11)
  if(LENS_ATSPI_FOUND)
    add_executable(lens-observer observer/observer_main.cpp observer/os_window_linux.cpp observer/uia_text_atspi.cpp
      observer/capture_x11.cpp observer/serve_worker_posix.cpp observer/capture_common.cpp agent/os.cpp)
    target_link_libraries(lens-observer PRIVATE lens-embedding OpenSSL::Crypto PkgConfig::LENS_ATSPI Threads::Threads)
    target_compile_options(lens-observer PRIVATE ${LENS_WARN})
  endif()
endif()

# Linux app (lens-app): GTK 4 + WebKitGTK 6 hosting engine/app/ui, relaying to lens-agent; built when both are installed.
if(NOT APPLE AND NOT ANDROID)
  pkg_check_modules(LENS_GTK IMPORTED_TARGET gtk4 webkitgtk-6.0)
  if(LENS_GTK_FOUND)
    add_executable(lens-app app/linux/app_gtk.cpp agent/os.cpp)
    target_link_libraries(lens-app PRIVATE lens-embedding OpenSSL::Crypto PkgConfig::LENS_GTK Threads::Threads)
    target_compile_options(lens-app PRIVATE ${LENS_WARN})
    add_custom_command(TARGET lens-app POST_BUILD COMMAND ${CMAKE_COMMAND} -E copy_directory
      "${CMAKE_CURRENT_SOURCE_DIR}/app/ui" "$<TARGET_FILE_DIR:lens-app>/ui")
    add_executable(lens-observer-testapp observer/testapp_gtk.cpp)
    target_link_libraries(lens-observer-testapp PRIVATE PkgConfig::LENS_GTK)
  endif()
endif()

# macOS app (lens-app): Cocoa + WKWebView hosting engine/app/ui, relaying to lens-agent.
if(APPLE)
  enable_language(OBJCXX)
  # Screen observer: Accessibility (AX) text of the frontmost window, ScreenCaptureKit for the OCR fallback. Needs the
  # user's Accessibility and Screen Recording permissions at run time.
  add_executable(lens-observer observer/observer_main.cpp observer/os_window_mac.mm observer/uia_text_ax.mm observer/capture_mac.mm
    observer/serve_worker_posix.cpp observer/capture_common.cpp agent/os.cpp)
  set_source_files_properties(observer/os_window_mac.mm observer/uia_text_ax.mm observer/capture_mac.mm PROPERTIES COMPILE_OPTIONS -fobjc-arc)
  target_link_libraries(lens-observer PRIVATE lens-embedding OpenSSL::Crypto Threads::Threads "-framework AppKit"
    "-framework ApplicationServices" "-framework ScreenCaptureKit" "-framework CoreGraphics" "-framework Foundation")
  target_compile_options(lens-observer PRIVATE ${LENS_WARN})
  add_executable(lens-app app/macos/app_mac.mm agent/os.cpp)
  target_link_libraries(lens-app PRIVATE lens-embedding OpenSSL::Crypto Threads::Threads "-framework Cocoa" "-framework WebKit")
  target_compile_options(lens-app PRIVATE -fobjc-arc ${LENS_WARN})
  add_custom_command(TARGET lens-app POST_BUILD COMMAND ${CMAKE_COMMAND} -E copy_directory
    "${CMAKE_CURRENT_SOURCE_DIR}/app/ui" "$<TARGET_FILE_DIR:lens-app>/ui")
endif()

add_executable(lens-embed embed_main.cpp)
target_link_libraries(lens-embed PRIVATE lens-embedding)
