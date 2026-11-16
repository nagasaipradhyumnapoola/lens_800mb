package ai.secondbrain.lens

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** The question and its answer, kept by the app (not the tab) so switching tabs never loses an answer or a search in flight. */
class AskState(private val repo: LensRepository, private val scope: CoroutineScope) {
    var query by mutableStateOf("")
    var asked by mutableStateOf(""); private set
    var asking by mutableStateOf(false); private set
    var answer by mutableStateOf<LensRepository.Answer?>(null); private set

    fun ask() {
        val q = query.trim()
        if (q.isEmpty() || asking) return
        asking = true; asked = q
        scope.launch { answer = withContext(Dispatchers.IO) { repo.ask(q) }; asking = false }
    }
}

@Composable
fun AskScreen(repo: LensRepository, state: AskState) {
    val context = LocalContext.current
    val focus = LocalFocusManager.current
    val dictation = remember { Dictation(context) }
    var query by state::query
    val asked = state.asked
    val asking = state.asking
    val answer = state.answer
    val paired = repo.laptop != null
    val mic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { if (it) dictation.start() }

    fun ask() { dictation.stop(); focus.clearFocus(); state.ask() }
    LaunchedEffect(dictation.transcript) { if (dictation.transcript.isNotEmpty()) query = dictation.transcript }
    LaunchedEffect(dictation.running) { if (!dictation.running && dictation.transcript.isNotEmpty()) ask() }
    DisposableEffect(Unit) { onDispose { dictation.stop() } }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("Ask", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)) }
        item {
            OutlinedTextField(query, { query = it }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp),
                placeholder = { Text("Ask your memory") }, maxLines = 4,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { ask() }),
                trailingIcon = {
                    Row {
                        IconButton(onClick = { if (dictation.running) dictation.stop() else mic.launch(Manifest.permission.RECORD_AUDIO) }) {
                            Icon(if (dictation.running) Icons.Outlined.GraphicEq else Icons.Outlined.Mic,
                                if (dictation.running) "Stop listening" else "Ask by voice",
                                tint = if (dictation.running) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        FilledIconButton(onClick = { ask() }, enabled = query.isNotBlank() && !asking, modifier = Modifier.padding(end = 6.dp)) {
                            Icon(Icons.AutoMirrored.Outlined.ArrowForward, "Ask")
                        }
                    }
                })
        }
        dictation.problem?.let { p -> item { Notice(p, Icons.Outlined.MicOff) } }
        when {
            asking -> item {
                var slow by remember { mutableStateOf(false) }
                LaunchedEffect(Unit) { kotlinx.coroutines.delay(3000); slow = true }
                Column(Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        Text(if (paired) "Searching your laptop…" else "Searching this phone…", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (slow && !paired) Text("The first question after Lens starts loads its search models on this phone; later questions are quick.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            answer != null -> {
                val a = answer
                val results = parseEvidence(a.response)
                if (a.laptopUnreachable) item { Notice("Your laptop is not reachable, so this searched only this phone.", Icons.Outlined.WifiOff) }
                if (results.isEmpty()) item {
                    EmptyState(Icons.Outlined.HelpOutline, "No reliable memory",
                        if (!a.response.optBoolean("ok")) "Lens could not search (${a.response.optString("error")})."
                        else "Lens found nothing that answers this${if (a.searchedLaptop) " on your laptop or this phone" else ""}. It won't guess.")
                } else {
                    item {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Icon(if (a.fromPhone) Icons.Outlined.PhoneAndroid else Icons.Outlined.Laptop, null, Modifier.size(16.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(if (a.fromPhone) "From this phone" else "From your laptop's memory", style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    item { EvidenceCard(results[0], asked) }
                    if (results.size > 1) {
                        item { Text("Other matches", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 10.dp)) }
                        items(results.drop(1).take(2)) { EvidenceCard(it, asked, compact = true) }
                    }
                }
                if (!paired) item { Text("Pair with Lens on your laptop to ask everything it remembers.", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            else -> {
                item { Text("Try", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(listOf("What did I note about the venue?", "When is the dentist appointment?", "Which flight did I book?")) { example ->
                    OutlinedCard(onClick = { query = example; ask() }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp)) {
                        Row(Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.ManageSearch, null, tint = MaterialTheme.colorScheme.primary)
                            Text(example)
                        }
                    }
                }
            }
        }
    }
}
