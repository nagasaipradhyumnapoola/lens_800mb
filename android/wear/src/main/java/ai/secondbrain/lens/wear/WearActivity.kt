package ai.secondbrain.lens.wear

import ai.secondbrain.lens.LensRepository
import ai.secondbrain.lens.PairingCode
import ai.secondbrain.lens.parseEvidence
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.material.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Lens on the wrist: ask laptop memory and leave quick notes. Everything else stays on the phone and laptop. */
class WearActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repo = LensRepository(applicationContext)
        setContent { MaterialTheme { WearLens(repo) } }
    }
}

@Composable
fun Field(value: String, onChange: (String) -> Unit, hint: String) {
    Box(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        BasicTextField(value, onChange, textStyle = TextStyle(color = Color.White, fontSize = 13.sp), modifier = Modifier.fillMaxWidth())
        if (value.isEmpty()) Text(hint, fontSize = 13.sp, color = Color.Gray)
    }
}

@Composable
fun WearLens(repo: LensRepository) {
    var paired by remember { mutableStateOf(repo.laptop != null) }
    var input by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    ScalingLazyColumn(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
        item { Text("Lens", style = MaterialTheme.typography.title3) }
        if (!paired) {
            item { Field(input, { input = it }, "Pairing code") }
            item {
                Chip(label = { Text("Pair") }, onClick = {
                    val code = PairingCode.parse(input) ?: run { answer = "Not a Lens pairing code."; return@Chip }
                    scope.launch {
                        val err = withContext(Dispatchers.IO) { repo.pair(code, "Watch") }
                        if (err == null) { paired = true; input = ""; answer = null } else answer = err
                    }
                })
            }
        } else {
            item { Field(input, { input = it }, "Ask or note…") }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    CompactChip(label = { Text("Ask") }, onClick = {
                        val q = input; answer = "…"
                        scope.launch {
                            answer = withContext(Dispatchers.IO) {
                                runCatching { parseEvidence(repo.recall(q)).firstOrNull()?.let { "${it.app}: ${it.quote}" } ?: "No reliable evidence found." }
                                    .getOrElse { "Laptop not reachable." }
                            }
                        }
                    })
                    CompactChip(label = { Text("Note") }, onClick = {
                        val t = input; input = ""
                        scope.launch { answer = if (withContext(Dispatchers.IO) { repo.addNote(t) } > 0) "Saved." else "Saved; will sync." }
                    })
                }
            }
        }
        answer?.let { item { Text(it, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(horizontal = 8.dp)) } }
    }
}
