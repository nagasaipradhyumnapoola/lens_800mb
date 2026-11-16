package ai.secondbrain.lens

import com.google.android.gms.tasks.Task
import com.google.android.gms.tasks.TaskCompletionSource
import com.google.android.gms.wearable.WearableListenerService
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Lens on a Wear OS watch goes through this phone (the Wear Data Layer only connects this app to the same app, signed with
 * the same key, on a watch paired with this phone): questions are answered here (the laptop first, then this phone) and
 * notes are stored here. The watch keeps no memory, keys or history of its own.
 */
class WatchRelayService : WearableListenerService() {
    private val work = Executors.newSingleThreadExecutor()

    override fun onRequest(nodeId: String, path: String, request: ByteArray): Task<ByteArray> {
        val result = TaskCompletionSource<ByteArray>()
        work.execute {
            val reply = runCatching { handle(path, String(request, Charsets.UTF_8)) }
                .getOrElse { JSONObject().put("ok", false).put("error", "phone_failed") }
            result.setResult(reply.toString().toByteArray(Charsets.UTF_8))
        }
        return result.task
    }

    private fun handle(path: String, text: String): JSONObject {
        val repo = LensRepository(applicationContext)
        return when (path) {
            "/lens/ask" -> {
                val a = repo.ask(text.take(1000))
                JSONObject().put("ok", a.response.optBoolean("ok")).put("from_phone", a.fromPhone).put("unreachable", a.laptopUnreachable)
                    .put("response", a.response)
            }
            "/lens/note" -> {
                val saved = repo.remember(text.take(20000))
                JSONObject().put("ok", saved.error == null).put("error", saved.error).put("delivered", saved.delivered).put("paired", repo.laptop != null)
            }
            else -> JSONObject().put("ok", false).put("error", "unsupported_operation")
        }
    }

    override fun onDestroy() { work.shutdown(); super.onDestroy() }
}
