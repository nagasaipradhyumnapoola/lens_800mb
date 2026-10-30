import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "ai.secondbrain.lens"
    compileSdk = 36
    defaultConfig {
        applicationId = "ai.secondbrain.lens.companion"
        minSdk = 29          // TLS 1.3 and Android Keystore EC keys for client authentication
        targetSdk = 36
        versionCode = 1
        versionName = "0.3.0-dev"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }  // liblens-core.so is built for these two only
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    ndkVersion = "27.1.12297006"  // strips liblens-core.so when packaging
    // liblens-core.so per ABI from ci/android/build.ps1 (arm64-v8a for phones, x86_64 for the emulator).
    sourceSets["main"].jniLibs.srcDirs("../native-libs")
    buildFeatures { compose = true }
    androidResources { noCompress += "onnx" }  // the models are copied out once; stored, they copy fast
    packaging {
        resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" }
        jniLibs { excludes += "**/libonnxruntime4j_jni.so" }  // ONNX Runtime's Java binding: the engine uses its C API
    }
}

/**
 * Retrieval models for the phone's own memory, staged from the repository's pinned models/ (never downloaded by the app):
 * multilingual-e5-small INT8 (embeddings) and the Lens answerability head v3c (reranker, verifier and answer gate, as on
 * the laptop). Every file is checked against the lock files; manifest.json carries the hashes the app re-checks when it
 * installs them. -PlensModels=false builds a keyword-only app.
 */
abstract class StageLensModels : DefaultTask() {
    @get:Internal abstract val repository: DirectoryProperty    // inputs: the lock files and model files (registration)
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction fun stage() {
        val root = repository.get().asFile
        @Suppress("UNCHECKED_CAST")
        fun json(path: String) = JsonSlurper().parse(File(root, path)) as Any
        val embedding = json("third_party/embedding-lock.json") as Map<String, Any>
        val pinned = (json("third_party/model-lock.json") as List<Map<String, Any>>).associate { it["path"] as String to it["sha256"] as String }
        val e5 = (embedding["files"] as List<Map<String, Any>>).associate { it["filename"] as String to it }
        val files = linkedMapOf(
            "e5/model.onnx" to e5.getValue("onnx/model_qint8_avx512_vnni.onnx").let { it["path"] as String to it["sha256"] as String },
            "e5/tokenizer.json" to e5.getValue("onnx/tokenizer.json").let { it["path"] as String to it["sha256"] as String })
        for (f in listOf("model_int8.onnx", "tokenizer.json", "gate.json"))
            "models/Lens--answerability-v3c/$f".let { files["v3c/$f"] = it to pinned.getValue(it) }
        val out = outputDir.get().asFile.resolve("lens-models"); out.deleteRecursively(); out.mkdirs()
        val manifest = linkedMapOf<String, Any>()
        for ((name, source) in files) {
            val (path, sha) = source; val from = File(root, path)
            if (!from.isFile) throw GradleException("missing $path (fetch the pinned models, or build with -PlensModels=false)")
            val digest = MessageDigest.getInstance("SHA-256"); val to = out.resolve(name).apply { parentFile.mkdirs() }
            from.inputStream().use { i -> to.outputStream().use { o -> val b = ByteArray(1 shl 20)
                while (true) { val n = i.read(b); if (n < 0) break; digest.update(b, 0, n); o.write(b, 0, n) } } }
            if (digest.digest().joinToString("") { "%02x".format(it) } != sha) throw GradleException("hash mismatch: $path")
            manifest[name] = mapOf("bytes" to from.length(), "sha256" to sha)
        }
        val sha = (e5.getValue("onnx/model_qint8_avx512_vnni.onnx")["sha256"] as String).take(16)
        val id = "intfloat/multilingual-e5-small@${(embedding["revision"] as String).take(12)}/onnx/model_qint8_avx512_vnni.onnx#sha256:$sha"
        out.resolve("manifest.json").writeText(JsonOutput.prettyPrint(JsonOutput.toJson(mapOf("embedding_id" to id, "files" to manifest))))
    }
}

if (providers.gradleProperty("lensModels").orNull != "false") {
    val stageLensModels = tasks.register<StageLensModels>("stageLensModels") {
        val root = rootProject.layout.projectDirectory.dir("..")
        repository.set(root)
        inputs.files(listOf("third_party/embedding-lock.json", "third_party/model-lock.json",
            "models/intfloat--multilingual-e5-small/onnx/model_qint8_avx512_vnni.onnx", "models/intfloat--multilingual-e5-small/onnx/tokenizer.json",
            "models/Lens--answerability-v3c/model_int8.onnx", "models/Lens--answerability-v3c/tokenizer.json",
            "models/Lens--answerability-v3c/gate.json").map { root.file(it) })
        outputDir.set(layout.buildDirectory.dir("generated/lens-models"))
    }
    androidComponents.onVariants { it.sources.assets?.addGeneratedSourceDirectory(stageLensModels, StageLensModels::outputDir) }
}

dependencies {
    implementation(project(":core"))
    implementation(platform("androidx.compose:compose-bom:2025.08.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    // libonnxruntime.so for the retrieval models (desktop pins 1.24.4; 1.24.3 is the newest 1.24 Android release, same C API 24)
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.24.3")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
}
