plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Wear OS app: asks and takes notes through Lens on the paired phone over the Wear Data Layer, which connects only the same
// application id signed with the same key; the watch has no network access, memory or keys of its own.
android {
    namespace = "ai.secondbrain.lens.wear"
    compileSdk = 36
    defaultConfig {
        applicationId = "ai.secondbrain.lens.companion"  // same as the phone app: required by the Data Layer
        minSdk = 30          // Wear OS 3+
        targetSdk = 36
        versionCode = 1
        versionName = "0.3.0-dev"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
}

dependencies {
    implementation(project(":core"))
    implementation(platform("androidx.compose:compose-bom:2025.08.00"))
    implementation("androidx.wear.compose:compose-material:1.4.1")
    implementation("androidx.wear.compose:compose-foundation:1.4.1")
    implementation("androidx.wear:wear-input:1.2.0")  // the system voice and keyboard input
    implementation("androidx.compose.material:material-icons-core")
    implementation("com.google.android.gms:play-services-wearable:19.0.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
}
