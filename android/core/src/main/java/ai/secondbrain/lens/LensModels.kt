package ai.secondbrain.lens

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.security.MessageDigest

/**
 * The retrieval models the APK ships (android/app build.gradle.kts `stageLensModels`): multilingual-e5-small INT8 and
 * the Lens answerability head v3c. ONNX Runtime needs files, so they are copied once into app-private storage and each
 * copy is checked against the SHA-256 in the APK's manifest; a later APK with other models replaces them.
 */
object LensModels {
    /** The engine's model configuration ([NativeCore.open]), or null when this APK ships no models (keyword-only). */
    fun install(context: Context, dir: File): JSONObject? {
        val manifest = try { context.assets.open("lens-models/manifest.json").use { String(it.readBytes(), Charsets.UTF_8) } }
                       catch (_: FileNotFoundException) { return null }
        val files = JSONObject(manifest).getJSONObject("files")
        val marker = File(dir, "installed.json")
        if (!marker.isFile || marker.readText() != manifest) {
            dir.deleteRecursively(); dir.mkdirs()
            for (name in files.keys()) {
                val digest = MessageDigest.getInstance("SHA-256"); val out = File(dir, name).apply { parentFile?.mkdirs() }
                context.assets.open("lens-models/$name").use { i -> out.outputStream().use { o -> val b = ByteArray(1 shl 20)
                    while (true) { val n = i.read(b); if (n < 0) break; digest.update(b, 0, n); o.write(b, 0, n) } } }
                if (digest.digest().joinToString("") { "%02x".format(it) } != files.getJSONObject(name).getString("sha256")) {
                    dir.deleteRecursively(); throw IllegalStateException("model_hash_mismatch")
                }
            }
            marker.writeText(manifest)
        }
        fun path(name: String) = File(dir, name).absolutePath
        return JSONObject().put("runtime", "libonnxruntime.so")  // from the ONNX Runtime AAR, found by the app's library path
            .put("embedding_model", path("e5/model.onnx")).put("embedding_tokenizer", path("e5/tokenizer.json"))
            .put("embedding_id", JSONObject(manifest).getString("embedding_id"))
            .put("reranker_model", path("v3c/model_int8.onnx")).put("reranker_tokenizer", path("v3c/tokenizer.json"))
            .put("verifier_model", path("v3c/model_int8.onnx")).put("verifier_tokenizer", path("v3c/tokenizer.json"))
    }
}
