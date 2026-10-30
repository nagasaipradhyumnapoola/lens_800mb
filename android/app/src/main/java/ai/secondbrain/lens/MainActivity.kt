package ai.secondbrain.lens

import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val Graphite = darkColorScheme(
    background = Color(0xFF111214), surface = Color(0xFF1C1D21), surfaceVariant = Color(0xFF222328),
    primary = Color(0xFFE7E8EC), onPrimary = Color(0xFF121316), onBackground = Color(0xFFE9E9EC), onSurface = Color(0xFFE9E9EC),
    onSurfaceVariant = Color(0xFF9B9CA4), outline = Color(0xFF383A41), error = Color(0xFFEF8A8A))

/** A stored ISO-8601 instant in this phone's time zone ("2026-10-30 14:21"); anything else as stored. */
fun localTime(timestamp: String): String = runCatching {
    java.time.OffsetDateTime.parse(timestamp).atZoneSameInstant(java.time.ZoneId.systemDefault())
        .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
}.getOrDefault(timestamp.take(16).replace('T', ' '))

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repo = LensRepository(applicationContext)
        setContent { MaterialTheme(colorScheme = Graphite) { Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { LensApp(repo) } } }
    }
}

/** This phone's memory works on its own; pairing with a laptop is optional and adds the laptop's whole memory. */
@Composable
fun LensApp(repo: LensRepository) {
    var paired by remember { mutableStateOf(repo.laptop != null) }
    var pairing by remember { mutableStateOf(false) }
    if (pairing) PairScreen(repo, onCancel = { pairing = false }) { paired = true; pairing = false }
    else HomeScreen(repo, paired, onPair = { pairing = true }) { repo.unpair(); paired = false }
}

@Composable
fun PairScreen(repo: LensRepository, onCancel: () -> Unit, onPaired: () -> Unit) {
    var code by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var verification by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Lens", fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
        verification?.let {
            Text("Approve this phone on the laptop only if it shows the same code:", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(it, fontSize = 32.sp, fontWeight = FontWeight.SemiBold)
        }
        Text("Pair this phone with Lens on your laptop: open Lens › Privacy › Phone link, then paste the pairing code shown there.",
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(code, { code = it }, label = { Text("Pairing code") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
        Button(enabled = !busy && code.isNotBlank(), onClick = {
            val parsed = PairingCode.parse(code)
            if (parsed == null) { message = "That is not a Lens pairing code."; return@Button }
            busy = true
            scope.launch {
                val error = withContext(Dispatchers.IO) {
                    repo.pair(parsed, Build.MODEL ?: "Phone") { shown -> verification = shown }
                }
                busy = false; verification = null; if (error == null) onPaired() else message = error
            }
        }) { Text(if (verification != null) "Waiting for approval…" else if (busy) "Pairing…" else "Pair") }
        TextButton(enabled = !busy, onClick = onCancel) { Text("Not now") }
        message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable
fun HomeScreen(repo: LensRepository, paired: Boolean, onPair: () -> Unit, onUnpair: () -> Unit) {
    var query by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<Evidence>?>(null) }
    var status by remember { mutableStateOf<String?>(null) }
    var note by remember { mutableStateOf("") }
    var confirmErase by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    if (confirmErase) AlertDialog(onDismissRequest = { confirmErase = false },
        title = { Text("Erase this phone's memory?") },
        text = { Text("Deletes every note and screen memory Lens stored on this phone, and its encryption keys. Your laptop's memory is not touched. This cannot be undone.") },
        confirmButton = { TextButton(onClick = { confirmErase = false; results = null
            scope.launch { withContext(Dispatchers.IO) { repo.eraseLocal() }; status = "This phone's memory was erased." } }) { Text("Erase") } },
        dismissButton = { TextButton(onClick = { confirmErase = false }) { Text("Cancel") } })
    // Android 15+ draws edge to edge: keep clear of the status bar, navigation bar and keyboard.
    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Text("Ask your memory", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            if (paired) TextButton(onClick = onUnpair) { Text("Unpair") } else TextButton(onClick = onPair) { Text("Pair laptop") }
        }
        OutlinedTextField(query, { query = it }, placeholder = { Text("What did Priya say about the budget?") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Button(enabled = query.isNotBlank(), onClick = {
            status = if (paired) "Asking your laptop…" else "Searching this phone…"; results = null
            scope.launch {
                val a = withContext(Dispatchers.IO) { repo.ask(query) }
                results = parseEvidence(a.response)
                status = when {
                    !a.response.optBoolean("ok") -> "Lens could not search (${a.response.optString("error")})."
                    a.fromPhone && paired -> "Your laptop is not reachable; these are from this phone's memory only."
                    else -> null
                }
            }
        }) { Text("Ask") }
        status?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        results?.let { list ->
            if (list.isEmpty()) Card { Column(Modifier.padding(16.dp)) { Text("No reliable evidence found", fontWeight = FontWeight.SemiBold)
                Text("Lens did not find a memory that answers this. It will not guess.", color = MaterialTheme.colorScheme.onSurfaceVariant) } }
            LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(list) { e ->
                    Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface, RoundedCornerShape(12.dp)).padding(14.dp)) {
                        Text("${e.app}  ${e.window}", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp, maxLines = 1)
                        Spacer(Modifier.height(6.dp)); Text(e.quote)   // plain text only
                        Spacer(Modifier.height(6.dp)); Text(localTime(e.timestamp), color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
                    }
                }
            }
        } ?: Spacer(Modifier.weight(1f))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        var observing by remember { mutableStateOf(repo.observeScreen) }
        val context = androidx.compose.ui.platform.LocalContext.current
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Observe phone screen", fontWeight = FontWeight.SemiBold)
                Text("Off unless you turn it on here and enable “Lens screen memory” in Android accessibility settings. Never reads passwords, password managers or private tabs.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
            }
            Switch(observing, { on -> repo.observeScreen = on; observing = on
                if (on) context.startActivity(android.content.Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
        }
        OutlinedTextField(note, { note = it }, label = { Text("Quick note to remember") }, modifier = Modifier.fillMaxWidth())
        Button(enabled = note.isNotBlank(), onClick = {
            val text = note; note = ""
            scope.launch {
                val saved = withContext(Dispatchers.IO) { repo.remember(text) }
                status = when {
                    saved.error == "sensitive_content_excluded" -> "Not saved: Lens never stores passwords, codes or card details."
                    saved.error != null && saved.delivered == 0 -> "Could not save on this phone (${saved.error})."
                    saved.delivered > 0 -> "Saved on this phone and your laptop."
                    paired -> "Saved on this phone; it will be sent when your laptop is reachable (${repo.pending()} waiting)."
                    else -> "Saved on this phone."
                }
            }
        }) { Text("Remember") }
        TextButton(onClick = { confirmErase = true }) { Text("Erase this phone's memory", color = MaterialTheme.colorScheme.error) }
    }
}
