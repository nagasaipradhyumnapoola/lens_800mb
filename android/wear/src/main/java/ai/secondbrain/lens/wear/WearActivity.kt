package ai.secondbrain.lens.wear

import ai.secondbrain.lens.Evidence
import ai.secondbrain.lens.parseEvidence
import android.app.Activity
import android.app.RemoteInput
import android.content.Context
import android.os.Bundle
import android.text.format.DateUtils
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Search
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.material.*
import androidx.wear.input.RemoteInputIntentHelper
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.Instant
import java.util.concurrent.TimeUnit

/**
 * Lens on the wrist: ask your memory and take notes by voice or keyboard. Everything goes through the Lens app on the
 * paired phone (which asks the laptop); the watch keeps no memory, keys or history of its own.
 */
class WearActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme(colors = Colors(primary = Color(0xFFB4B3FF), onPrimary = Color(0xFF1A1966))) { WearLens(applicationContext) } }
    }
}

/** One request to the phone app over the Wear Data Layer; null when no phone with Lens is reachable. */
private fun askPhone(context: Context, path: String, text: String): JSONObject? = runCatching {
    val nodes = Tasks.await(Wearable.getNodeClient(context).connectedNodes, 5, TimeUnit.SECONDS)
    val phone = nodes.firstOrNull { it.isNearby } ?: nodes.firstOrNull() ?: return null
    val reply = Tasks.await(Wearable.getMessageClient(context).sendRequest(phone.id, path, text.toByteArray(Charsets.UTF_8)), 60, TimeUnit.SECONDS)
    JSONObject(String(reply, Charsets.UTF_8))
}.getOrNull()

private const val INPUT = "lens_input"

@Composable
fun WearLens(context: Context) {
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var asked by remember { mutableStateOf<String?>(null) }
    var results by remember { mutableStateOf<List<Evidence>>(emptyList()) }
    var origin by remember { mutableStateOf("") }

    fun ask(q: String) {
        busy = true; status = null; asked = q; results = emptyList()
        scope.launch {
            val r = withContext(Dispatchers.IO) { askPhone(context, "/lens/ask", q) }
            busy = false
            if (r == null) { status = "Your phone is not reachable. Keep it nearby with Lens installed."; return@launch }
            results = parseEvidence(r.optJSONObject("response") ?: JSONObject())
            origin = if (r.optBoolean("from_phone")) "From your phone" else "From your laptop"
            status = when {
                !r.optBoolean("ok") -> "Lens could not search (${r.optJSONObject("response")?.optString("error").orEmpty()})."
                results.isEmpty() -> "No reliable memory. Lens won't guess."
                r.optBoolean("unreachable") -> "Laptop not reachable; searched your phone."
                else -> null
            }
        }
    }

    fun remember(t: String) {
        busy = true; status = null
        scope.launch {
            val r = withContext(Dispatchers.IO) { askPhone(context, "/lens/note", t) }
            busy = false
            status = when {
                r == null -> "Your phone is not reachable, so this was not saved."
                r.optString("error") == "sensitive_content_excluded" -> "Not saved: Lens never stores passwords, codes or card details."
                !r.optBoolean("ok") -> "Not saved (${r.optString("error")})."
                r.optInt("delivered") > 0 -> "Saved on your phone and laptop."
                else -> "Saved on your phone."
            }
        }
    }

    var pending by remember { mutableStateOf<String?>(null) }
    val input = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val text = result.data?.takeIf { result.resultCode == Activity.RESULT_OK }
            ?.let { RemoteInput.getResultsFromIntent(it)?.getCharSequence(INPUT)?.toString()?.trim() }
        if (!text.isNullOrEmpty()) { if (pending == "ask") ask(text) else remember(text) }
    }
    fun open(kind: String, label: String) {
        pending = kind
        val intent = RemoteInputIntentHelper.createActionRemoteInputIntent()
        RemoteInputIntentHelper.putRemoteInputsExtra(intent, listOf(RemoteInput.Builder(INPUT).setLabel(label).build()))
        input.launch(intent)
    }

    Scaffold(timeText = { TimeText() }) {
        ScalingLazyColumn(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
            item { Text("Lens", style = MaterialTheme.typography.title3, modifier = Modifier.padding(bottom = 4.dp)) }
            item {
                Chip(label = { Text("Ask") }, secondaryLabel = { Text("Speak or type a question") },
                    icon = { Icon(Icons.Filled.Search, null) }, onClick = { open("ask", "Ask your memory") },
                    enabled = !busy, colors = ChipDefaults.primaryChipColors(), modifier = Modifier.fillMaxWidth())
            }
            item {
                Chip(label = { Text("Remember") }, secondaryLabel = { Text("Save a quick note") },
                    icon = { Icon(Icons.Filled.Add, null) }, onClick = { open("note", "What should Lens remember?") },
                    enabled = !busy, colors = ChipDefaults.secondaryChipColors(), modifier = Modifier.fillMaxWidth())
            }
            if (busy) item { CircularProgressIndicator(Modifier.size(28.dp).padding(top = 6.dp)) }
            status?.let { s -> item { Text(s, style = MaterialTheme.typography.caption2, textAlign = TextAlign.Center, modifier = Modifier.padding(8.dp)) } }
            if (results.isNotEmpty()) {
                item { ListHeader { Text(origin) } }
                items(results.take(3)) { e ->
                    TitleCard(onClick = {}, title = { Text(e.app, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        time = { Text(e.time()) }, modifier = Modifier.fillMaxWidth()) {
                        Text(e.quote, maxLines = 5, overflow = TextOverflow.Ellipsis)
                    }
                }
                asked?.let { q -> item { Text("“$q”", style = MaterialTheme.typography.caption3, textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 4.dp, start = 12.dp, end = 12.dp)) } }
            }
            item { Text("Goes through Lens on your phone. Nothing is kept on the watch.", style = MaterialTheme.typography.caption3,
                textAlign = TextAlign.Center, color = MaterialTheme.colors.onSurfaceVariant, modifier = Modifier.padding(top = 10.dp, start = 10.dp, end = 10.dp)) }
        }
    }
}

private fun Evidence.time(): String = runCatching {
    DateUtils.getRelativeTimeSpanString(Instant.parse(timestamp).toEpochMilli(), System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString()
}.getOrDefault("")
