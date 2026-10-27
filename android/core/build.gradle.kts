plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

// Shared by the phone and watch apps: pairing codes, Keystore device identity, pinned TLS 1.3 link, repository.
android {
    namespace = "ai.secondbrain.lens.core"
    compileSdk = 36
    defaultConfig { minSdk = 29 }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    testImplementation("org.json:json:20250517")  // Android ships org.json; JVM unit tests need the real jar
    testImplementation("junit:junit:4.13.2")
}
