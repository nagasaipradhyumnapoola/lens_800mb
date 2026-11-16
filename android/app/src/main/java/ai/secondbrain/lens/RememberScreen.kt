package ai.secondbrain.lens

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Notes typed or spoken; each is stored only when the user taps Remember. Anything can also be shared to Lens. */
@Composable
fun RememberScreen(repo: LensRepository, stored: () -> Unit) {
    val context = LocalContext.current
    val focus = LocalFocusManager.current
    val scope = rememberCoroutineScope()
    val dictation = remember { Dictation(context) }
    var note by rememberSaveable { mutableStateOf("") }
    var spokenStart by remember { mutableStateOf<Int?>(null) }
    var voice by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<Pair<Boolean, String>?>(null) }
    val mic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { if (it) dictation.start() }

    LaunchedEffect(dictation.transcript) {
        val t = dictation.transcript
        if (t.isEmpty()) return@LaunchedEffect
        val start = spokenStart ?: run { if (note.isNotEmpty() && !note.endsWith(" ")) note += " "; note.length }
        spokenStart = start; note = note.take(start) + t; voice = true
    }
    LaunchedEffect(dictation.running) { if (!dictation.running) spokenStart = null }
    DisposableEffect(Unit) { onDispose { dictation.stop() } }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Remember", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.padding(top = 8.dp))
        OutlinedTextField(note, { note = it; status = null }, modifier = Modifier.fillMaxWidth().heightIn(min = 160.dp), shape = RoundedCornerShape(18.dp),
            placeholder = { Text("Type or speak something to remember") })
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { if (dictation.running) dictation.stop() else mic.launch(Manifest.permission.RECORD_AUDIO) }) {
                Icon(if (dictation.running) Icons.Outlined.StopCircle else Icons.Outlined.Mic, null, Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp)); Text(if (dictation.running) "Stop" else "Speak")
            }
            Spacer(Modifier.weight(1f))
            Button(enabled = note.isNotBlank() && !saving, onClick = {
                val text = note; dictation.stop(); focus.clearFocus(); saving = true
                scope.launch {
                    val saved = withContext(Dispatchers.IO) { repo.remember(text, if (voice) "voice_note" else "note") }
                    saving = false
                    status = when {
                        saved.error == "sensitive_content_excluded" -> false to "Not saved: Lens never stores passwords, codes or card details."
                        saved.error != null && saved.delivered == 0 -> false to "Could not save on this phone (${saved.error})."
                        saved.delivered > 0 -> true to "Saved on this phone and your laptop."
                        repo.laptop != null -> true to "Saved on this phone. It goes to your laptop when it is reachable (${repo.pending()} waiting)."
                        else -> true to "Saved on this phone."
                    }
                    if (status?.first == true) { note = ""; voice = false; stored() }
                }
            }) { Text("Remember") }
        }
        dictation.problem?.let { Notice(it, Icons.Outlined.MicOff) }
        status?.let { (ok, text) ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(if (ok) Icons.Outlined.CheckCircle else Icons.Outlined.ErrorOutline, null,
                    tint = if (ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
                Text(text, style = MaterialTheme.typography.bodyMedium)
            }
        }
        Text("Voice is recognised on this phone and never stored; only the text is kept.", style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        HorizontalDivider(Modifier.padding(vertical = 8.dp), color = MaterialTheme.colorScheme.outlineVariant)
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.Top) {
            Icon(Icons.Outlined.Share, null, tint = MaterialTheme.colorScheme.primary)
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("Share to Lens from any app", style = MaterialTheme.typography.titleSmall)
                Text("Choose Lens in the Share menu to keep a link, a message or any text.", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
