package ai.secondbrain.lens

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import org.json.JSONObject
import java.io.Closeable
import java.io.File
import java.security.KeyStore
import java.security.SecureRandom
import java.time.Instant
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * This phone's own memory, usable with no laptop: the Lens store (SQLCipher) running in the app's process, in app-private
 * storage that is excluded from backups. Key chain, as on the desktop: the database key file beside the database is
 * wrapped (AES-256-GCM, native side) with a 32-byte master key; the master key is stored wrapped by an AES-256-GCM key
 * that never leaves Android Keystore (hardware-backed where the device has one). [erase] deletes that Keystore key, so
 * copies of the files are unreadable. One store per process ([shared]); requests are serialised.
 *
 * Recall here is keyword-only: the retrieval models (embedding, reranker) do not ship on Android yet.
 */
class LocalMemory private constructor(private var handle: Long, private val dir: File) : Closeable {
    companion object {
        const val WRAP_ALIAS = "lens-memory-master-wrap"
        private val MAGIC = "LENSMK01".toByteArray()
        private var instance: LocalMemory? = null

        /**
         * The process-wide store in [dir] (created on first use), its master key wrapped by Keystore key [alias]. The native
         * master key is per process, so a second directory is refused while one is open. Throws IllegalStateException(reason code).
         */
        @Synchronized fun shared(dir: File, alias: String = WRAP_ALIAS): LocalMemory {
            instance?.let { if (it.dir == dir.absoluteFile) return it else throw IllegalStateException("store_in_use") }
            dir.mkdirs()
            val master = masterKey(File(dir, "master.key"), alias)
            try { NativeCore.setMasterKey(master) } finally { master.fill(0) }
            val handle = try { NativeCore.open(File(dir, "memory.db").absolutePath.toByteArray()) } catch (e: Exception) { NativeCore.clearMasterKey(); throw e }
            return LocalMemory(handle, dir.absoluteFile).also { instance = it }
        }

        /** Closes the shared store and forgets the master key in native memory (the files and Keystore key stay). */
        @Synchronized fun release() { instance?.close(); instance = null; NativeCore.clearMasterKey() }

        /** Deletes a memory: closes it if open, deletes the Keystore key (copies of the files become unreadable) and the files. */
        @Synchronized fun erase(dir: File, alias: String = WRAP_ALIAS) {
            if (instance?.dir == dir.absoluteFile) release()
            val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            if (ks.containsAlias(alias)) ks.deleteEntry(alias)
            dir.deleteRecursively()
        }

        private fun wrappingKey(alias: String, create: Boolean): SecretKey? {
            val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (ks.getEntry(alias, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
            if (!create) return null
            val spec = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build()
            return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply { init(spec) }.generateKey()
        }

        /** File = "LENSMK01" | 12-byte IV | 32-byte ciphertext | 16-byte tag. Never falls back to an unwrapped key. */
        private fun masterKey(file: File, alias: String): ByteArray {
            if (file.exists()) {
                val raw = file.readBytes()
                if (raw.size != MAGIC.size + 12 + 48 || !raw.copyOfRange(0, MAGIC.size).contentEquals(MAGIC)) throw IllegalStateException("key_unavailable")
                val key = wrappingKey(alias, create = false) ?: throw IllegalStateException("key_unavailable")
                return try {
                    Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, raw, MAGIC.size, 12)) }
                        .doFinal(raw, MAGIC.size + 12, 48)
                } catch (e: Exception) { throw IllegalStateException("key_unavailable") }
            }
            if (File(file.parentFile, "memory.db").exists()) throw IllegalStateException("key_unavailable")  // never re-key silently
            val master = ByteArray(32).also { SecureRandom().nextBytes(it) }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, wrappingKey(alias, create = true)) }
            val sealed = cipher.doFinal(master)
            val tmp = File(file.parentFile, "master.key.tmp")
            tmp.writeBytes(MAGIC + cipher.iv + sealed)
            if (!tmp.renameTo(file)) { master.fill(0); throw IllegalStateException("key_write_failed") }
            return master
        }
    }

    @Synchronized fun request(request: JSONObject): JSONObject {
        check(handle != 0L) { "store_closed" }
        return JSONObject(String(NativeCore.request(handle, request.toString().toByteArray()), Charsets.UTF_8))
    }

    /** Stores one item the user gave or allowed (consent is the caller's), with the phone as device. */
    fun add(id: String, text: String, kind: String, timestamp: Instant, app: String, locator: String? = null, metadata: JSONObject? = null): JSONObject =
        request(JSONObject().put("op", "add").put("consent", true).put("id", id).put("text", text).put("language", "und")
            .put("timestamp", timestamp.toString()).put("kind", kind).put("device", "phone").put("provenance", "lens-companion")
            .put("source_application", app).apply { locator?.let { put("source_locator", it) } }
            .put("consent_context", JSONObject().put("mode", if (kind == "screen_observation") "android_accessibility" else "explicit_user_note"))
            .apply { metadata?.let { put("metadata", it) } })

    fun recall(query: String, limit: Int = 5): JSONObject =
        request(JSONObject().put("op", "recall").put("query", query).put("limit", limit).put("mode", "keyword"))

    @Synchronized override fun close() { if (handle != 0L) { NativeCore.close(handle); handle = 0L } }
}
