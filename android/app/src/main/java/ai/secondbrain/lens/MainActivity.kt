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

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repo = LensRepository(applicationContext)
        setContent { MaterialTheme(colorScheme = Graphite) { Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { LensApp(repo) } } }
    }
}

@Composable
fun LensApp(repo: LensRepository) {
    var paired by remember { mutableStateOf(repo.laptop != null) }
    if (!paired) PairScreen(repo) { paired = true } else HomeScreen(repo) { repo.unpair(); paired = false }
}

@Composable
fun PairScreen(repo: LensRepository, onPaired: () -> Unit) {
    var code by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Lens", fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
        Text("Pair this phone with Lens on your laptop: open Lens › Privacy › Phone link, then paste the pairing code shown there.",
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(code, { code = it }, label = { Text("Pairing code") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
        Button(enabled = !busy && code.isNotBlank(), onClick = {
            val parsed = PairingCode.parse(code)
            if (parsed == null) { message = "That is not a Lens pairing code."; return@Button }
            busy = true
            scope.launch {
                val error = withContext(Dispatchers.IO) { repo.pair(parsed, Build.MODEL ?: "Phone") }
                busy = false; if (error == null) onPaired() else message = error
            }
        }) { Text(if (busy) "Pairing…" else "Pair") }
        message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable
fun HomeScreen(repo: LensRepository, onUnpair: () -> Unit) {
    var query by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<Evidence>?>(null) }
    var status by remember { mutableStateOf<String?>(null) }
    var note by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Text("Ask your memory", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            TextButton(onClick = onUnpair) { Text("Unpair") }
        }
        OutlinedTextField(query, { query = it }, placeholder = { Text("What did Priya say about the budget?") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Button(enabled = query.isNotBlank(), onClick = {
            status = "Asking your laptop…"; results = null
            scope.launch {
                val r = withContext(Dispatchers.IO) { runCatching { repo.recall(query) } }
                r.onSuccess { results = parseEvidence(it); status = if (it.optBoolean("ok")) null else "Lens could not search (${it.optString("error")})." }
                 .onFailure { status = "Your laptop is not reachable right now." }
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
                        Spacer(Modifier.height(6.dp)); Text(e.timestamp.take(16).replace('T', ' '), color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
                    }
                }
            }
        } ?: Spacer(Modifier.weight(1f))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        OutlinedTextField(note, { note = it }, label = { Text("Quick note to remember") }, modifier = Modifier.fillMaxWidth())
        Button(enabled = note.isNotBlank(), onClick = {
            val text = note; note = ""
            scope.launch {
                val delivered = withContext(Dispatchers.IO) { repo.addNote(text) }
                status = if (delivered > 0) "Saved to your laptop." else "Saved on this phone; it will be sent when your laptop is reachable (${repo.pending()} waiting)."
            }
        }) { Text("Remember") }
    }
}
