package ai.secondbrain.lens

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.UUID

/**
 * This phone's memory ([LocalMemory], works with no laptop), the paired laptop, and the queue of items waiting for it.
 * Items are queued for the laptop only while a laptop is paired; pairing later never uploads earlier phone-only items.
 */
class LensRepository(private val context: Context) {
    private val prefs = context.getSharedPreferences("lens-link", Context.MODE_PRIVATE)
    private val queueFile = File(context.noBackupFilesDir, "pending-notes.jsonl")  // app-private, excluded from backups
    private val memoryDir = File(context.noBackupFilesDir, "lens-memory")

    /** This phone's encrypted store; throws IllegalStateException(reason code) when it cannot be opened. */
    val local: LocalMemory get() = LocalMemory.shared(memoryDir)

    /** Deletes everything Lens stored on this phone (memory, its keys, items waiting for the laptop). */
    fun eraseLocal() { LocalMemory.erase(memoryDir); synchronized(queueFile) { queueFile.delete() } }

    /** Result of saving one item: [error] is a reason code when this phone did not store it; [delivered] counts laptop deliveries. */
    data class Saved(val error: String?, val delivered: Int)

    /** An answer and where it came from: the laptop (whole memory) or, when it is unpaired or unreachable, this phone. */
    data class Answer(val response: JSONObject, val fromPhone: Boolean)

    data class Laptop(val hosts: List<String>, val port: Int, val fingerprint: String)

    val laptop: Laptop?
        get() {
            val fp = prefs.getString("fp", null) ?: return null
            val hosts = prefs.getString("hosts", null)?.split(",")?.filter { it.isNotBlank() } ?: return null
            return Laptop(hosts, prefs.getInt("port", 0), fp)
        }

    /** The Lens account this phone belongs to (set by its first pairing); a laptop of another account is refused. */
    val accountId: String? get() = prefs.getString("account", null)

    /**
     * Pairs with the laptop shown in the code. The laptop's user must approve this phone there: [onVerificationCode]
     * receives the 8-digit code to show, which must match the one on the laptop. Returns null once approved, or a
     * user-facing reason. Waits at most 5 minutes.
     */
    fun pair(code: PairingCode, deviceName: String, onVerificationCode: (String) -> Unit = {}): String? = try {
        MeshClient.connect(code.hosts, code.port, code.fingerprint).use { link ->
            val request = JSONObject().put("op", "pair").put("token", code.token).put("name", deviceName.take(64))
            accountId?.let { request.put("account_id", it) }
            var r = link.ask(request)
            if (r.optString("error") == "account_mismatch") return "This laptop belongs to a different Lens account. Lens never links devices of different accounts."
            if (!r.optBoolean("ok")) return "The laptop refused this code. Show a new pairing code on the laptop and try again."
            if (r.optBoolean("awaiting_approval")) onVerificationCode(r.optString("verification_code"))
            val deadline = System.currentTimeMillis() + 5 * 60 * 1000
            while (!r.optBoolean("paired")) {
                if (r.optString("error") == "pairing_denied") return "Pairing was declined on the laptop."
                if (!r.optBoolean("ok") || System.currentTimeMillis() > deadline) return "The laptop did not approve this phone. Start pairing again."
                Thread.sleep(2000); r = link.ask(JSONObject().put("op", "pair_status"))
            }
            val account = r.optString("account_id")
            if (!ACCOUNT.matches(account) || (accountId != null && accountId != account)) return "This laptop belongs to a different Lens account."
            prefs.edit().putString("fp", code.fingerprint).putString("hosts", code.hosts.joinToString(",")).putInt("port", code.port)
                .putString("account", account).apply()
            null
        }
    } catch (e: Exception) { "Could not reach the laptop (${e.javaClass.simpleName}). Both devices must be on the same network." }

    /** Forgets the laptop; the phone keeps its Lens account, so it can only ever re-pair within that account. */
    fun unpair() { val account = accountId; prefs.edit().clear().apply { account?.let { putString("account", it) } }.apply(); DeviceIdentity.forget() }

    private companion object { val ACCOUNT = Regex("^[0-9a-f]{32}$") }

    private fun <T> withLink(block: (MeshClient) -> T): T {
        val l = laptop ?: throw IllegalStateException("not paired")
        return MeshClient.connect(l.hosts, l.port, l.fingerprint).use(block)
    }

    fun recall(query: String): JSONObject = withLink { it.ask(JSONObject().put("op", "recall").put("query", query).put("limit", 5)) }

    /** Asks the paired laptop; falls back to this phone's memory when there is no laptop or it cannot be reached. */
    fun ask(query: String): Answer {
        if (laptop != null) runCatching { return Answer(recall(query), fromPhone = false) }
        return Answer(try { local.recall(query) } catch (e: IllegalStateException) { JSONObject().put("ok", false).put("error", e.message) }, fromPhone = true)
    }

    /** Stores a note on this phone and, when paired, queues it for the laptop and delivers what it can. */
    fun remember(text: String, kind: String = "note"): Saved =
        save("phone-" + UUID.randomUUID(), text.take(20000), kind, "Lens", null, null)

    fun addNote(text: String, kind: String = "note"): Int = remember(text, kind).delivered

    private fun save(id: String, text: String, kind: String, app: String, title: String?, metadata: JSONObject?): Saved {
        val now = Instant.now()
        val error = try { local.add(id, text, kind, now, app, title?.let { "window:$it" }, metadata).let { if (it.optBoolean("ok")) null else it.optString("error") } }
                    catch (e: IllegalStateException) { e.message ?: "store_unavailable" }
        if (error == "sensitive_content_excluded" || laptop == null) return Saved(error, 0)  // the laptop refuses the same content
        val item = JSONObject().put("op", "add").put("consent", true).put("id", id).put("text", text)
            .put("language", "und").put("timestamp", now.toString()).put("kind", kind)
            .put("device", "phone").put("provenance", "lens-companion")  // the laptop replaces device and provenance
        metadata?.let { item.put("metadata", it) }
        synchronized(queueFile) { queueFile.appendText(item.toString() + "\n") }
        return Saved(error, flush())
    }

    /**
     * Phone screen observation, off by default: on only while the user has switched it on in Lens *and* enabled the
     * Lens accessibility service in Android settings. Turning it off here stops capture at once.
     */
    var observeScreen: Boolean
        get() = prefs.getBoolean("observe_screen", false)
        set(on) { prefs.edit().putBoolean("observe_screen", on).apply() }

    /** Stores new screen text of one app window (only lines not stored before); queued for the laptop when paired. */
    fun addObservation(text: String, packageName: String, title: String): Int =
        save("phone-screen-" + UUID.randomUUID(), text.take(4000), "screen_observation", packageName.take(128), title.take(256),
            JSONObject().put("package", packageName.take(128)).put("window_title", title.take(256)).put("capture", "android_accessibility")).delivered

    fun pending(): Int = synchronized(queueFile) { if (queueFile.exists()) queueFile.readLines().count { it.isNotBlank() } else 0 }

    fun flush(): Int = synchronized(queueFile) {
        if (!queueFile.exists() || laptop == null) return 0
        val lines = queueFile.readLines().filter { it.isNotBlank() }
        if (lines.isEmpty()) return 0
        var delivered = 0
        try {
            withLink { link ->
                for (line in lines) {
                    val r = link.ask(JSONObject(line))
                    if (r.optBoolean("ok") || r.optString("error") == "immutable_source_conflict") delivered++ else break
                }
            }
        } catch (_: Exception) { }
        queueFile.writeText(lines.drop(delivered).joinToString("") { it + "\n" })
        delivered
    }
}

/** Evidence items from a recall response, for display. */
data class Evidence(val quote: String, val app: String, val window: String, val timestamp: String)

fun parseEvidence(response: JSONObject): List<Evidence> {
    if (!response.optBoolean("ok") || response.optBoolean("not_found")) return emptyList()
    val results: JSONArray = response.optJSONArray("results") ?: return emptyList()
    return (0 until results.length()).map { i ->
        val item = results.getJSONObject(i); val src = item.optJSONObject("source") ?: JSONObject()
        Evidence(item.optJSONObject("evidence")?.optString("quote").orEmpty().ifEmpty { src.optString("text") },
            src.optString("source_application").removeSuffix(".exe").replaceFirstChar { it.uppercase() },
            src.optString("source_locator").removePrefix("window:"), src.optString("timestamp"))
    }
}
