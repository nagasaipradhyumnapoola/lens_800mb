package ai.secondbrain.lens

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.UUID

/** Paired laptop, offline note queue and the operations the companion performs over the link. */
class LensRepository(private val context: Context) {
    private val prefs = context.getSharedPreferences("lens-link", Context.MODE_PRIVATE)
    private val queueFile = File(context.noBackupFilesDir, "pending-notes.jsonl")  // app-private, excluded from backups

    data class Laptop(val hosts: List<String>, val port: Int, val fingerprint: String)

    val laptop: Laptop?
        get() {
            val fp = prefs.getString("fp", null) ?: return null
            val hosts = prefs.getString("hosts", null)?.split(",")?.filter { it.isNotBlank() } ?: return null
            return Laptop(hosts, prefs.getInt("port", 0), fp)
        }

    /** Pairs with the laptop shown in the code. Returns null on success, or a user-facing reason. */
    fun pair(code: PairingCode, deviceName: String): String? = try {
        MeshClient.connect(code.hosts, code.port, code.fingerprint).use { link ->
            val r = link.ask(JSONObject().put("op", "pair").put("token", code.token).put("name", deviceName.take(64)))
            if (r.optBoolean("paired")) {
                prefs.edit().putString("fp", code.fingerprint).putString("hosts", code.hosts.joinToString(",")).putInt("port", code.port).apply()
                null
            } else "The laptop refused this code. Show a new pairing code on the laptop and try again."
        }
    } catch (e: Exception) { "Could not reach the laptop (${e.javaClass.simpleName}). Both devices must be on the same network." }

    fun unpair() { prefs.edit().clear().apply(); DeviceIdentity.forget() }

    private fun <T> withLink(block: (MeshClient) -> T): T {
        val l = laptop ?: throw IllegalStateException("not paired")
        return MeshClient.connect(l.hosts, l.port, l.fingerprint).use(block)
    }

    fun recall(query: String): JSONObject = withLink { it.ask(JSONObject().put("op", "recall").put("query", query).put("limit", 5)) }

    /** Queues a note (works offline) and tries to deliver everything pending. Returns how many were delivered. */
    fun addNote(text: String, kind: String = "note"): Int {
        val note = JSONObject().put("op", "add").put("consent", true).put("id", "phone-" + UUID.randomUUID()).put("text", text.take(20000))
            .put("language", "und").put("timestamp", Instant.now().toString()).put("kind", kind)
            .put("device", "phone").put("provenance", "lens-companion")  // the laptop replaces device and provenance
        synchronized(queueFile) { queueFile.appendText(note.toString() + "\n") }
        return flush()
    }

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
