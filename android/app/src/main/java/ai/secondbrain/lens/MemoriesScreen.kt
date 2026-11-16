package ai.secondbrain.lens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

/** What this phone remembers, newest first, grouped by day; each item opens in full and can be deleted. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemoriesScreen(repo: LensRepository, version: Int, changed: () -> Unit) {
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<Evidence>?>(null) }
    var filter by remember { mutableStateOf("") }
    var open by remember { mutableStateOf<Evidence?>(null) }
    var confirm by remember { mutableStateOf<Evidence?>(null) }
    LaunchedEffect(version) { items = withContext(Dispatchers.IO) { repo.timeline() } }

    val zone = ZoneId.systemDefault()
    val shown = items.orEmpty().filter { filter.isBlank() || it.text.contains(filter, ignoreCase = true) }
    val days = shown.groupBy { it.instant()?.atZone(zone)?.toLocalDate() }
    val today = LocalDate.now(zone)
    fun dayTitle(d: LocalDate?) = when (d) {
        null -> "Undated"; today -> "Today"; today.minusDays(1) -> "Yesterday"
        else -> d.format(DateTimeFormatter.ofPattern("EEEE, d MMMM"))
    }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("Memories", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.padding(top = 8.dp)) }
        if (items == null) item {
            Row(Modifier.padding(vertical = 24.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                Text("Opening your memory…", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else if (items!!.isEmpty()) item {
            EmptyState(Icons.Outlined.Inbox, "Nothing remembered yet", "Notes, voice and things you share to Lens appear here.")
        } else {
            item {
                OutlinedTextField(filter, { filter = it }, modifier = Modifier.fillMaxWidth(), singleLine = true, shape = RoundedCornerShape(14.dp),
                    placeholder = { Text("Filter") }, leadingIcon = { Icon(Icons.Outlined.FilterList, null) })
            }
            for ((day, group) in days) {
                item(key = "day-$day") {
                    Text(dayTitle(day), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 10.dp))
                }
                items(group, key = { it.id }) { e ->
                    Surface(onClick = { open = e }, shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.surfaceContainer) {
                        Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
                            Icon(kindIcon(e.kind), null, tint = MaterialTheme.colorScheme.primary)
                            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(e.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text("${e.app} · ${e.instant()?.atZone(zone)?.toLocalTime()?.format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT)).orEmpty()}",
                                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
        }
    }

    open?.let { e ->
        ModalBottomSheet(onDismissRequest = { open = null }) {
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp).padding(bottom = 32.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)) {
                SelectionContainer { Text(e.text, style = MaterialTheme.typography.bodyLarge) }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(kindIcon(e.kind), null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("${e.app} · ${relativeTime(e)}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Lock, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("Stored encrypted on this phone", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                TextButton(onClick = { confirm = e }, colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
                    Icon(Icons.Outlined.Delete, null); Spacer(Modifier.width(8.dp)); Text("Delete")
                }
            }
        }
    }
    confirm?.let { e ->
        AlertDialog(onDismissRequest = { confirm = null }, title = { Text("Delete this memory?") },
            text = { Text("It is removed from this phone with everything Lens derived from it. A copy already sent to your laptop stays there.") },
            confirmButton = { TextButton(onClick = {
                confirm = null; open = null
                scope.launch { if (withContext(Dispatchers.IO) { repo.delete(e.id) }) changed() }
            }) { Text("Delete", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } })
    }
}
