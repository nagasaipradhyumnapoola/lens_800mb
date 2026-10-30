# Linux build and test image for the portable Lens core (engine/portable.cmake). Ubuntu 24.04 packages only, plus the
# official ONNX Runtime 1.24.4 release (the version pinned on Windows), checked against ci/linux/onnxruntime.sha256.
# GTK 4 + WebKitGTK 6 build the Linux app; Xvfb gives its self-test a virtual display.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build pkg-config git ca-certificates curl \
      libssl-dev libzstd-dev nlohmann-json3-dev libutf8proc-dev libsecret-1-dev \
      gnome-keyring dbus-x11 python3 tcl \
      libgtk-4-dev libwebkitgtk-6.0-dev xvfb xauth \
    && rm -rf /var/lib/apt/lists/*
COPY onnxruntime.sha256 /tmp/onnxruntime.sha256
RUN curl -fsSL -o /tmp/ort.tgz https://github.com/microsoft/onnxruntime/releases/download/v1.24.4/onnxruntime-linux-x64-1.24.4.tgz \
    && (cd /tmp && sha256sum -c onnxruntime.sha256) \
    && mkdir -p /opt/onnxruntime && tar -xzf /tmp/ort.tgz -C /opt/onnxruntime --strip-components=1 && rm /tmp/ort.tgz
WORKDIR /src
