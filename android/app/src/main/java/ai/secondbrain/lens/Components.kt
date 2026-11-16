package ai.secondbrain.lens

import android.os.Build
import android.text.format.DateUtils
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import java.time.Instant

private val Indigo = Color(0xFF5856D6)
private val DarkScheme = darkColorScheme(
    primary = Color(0xFFB4B3FF), onPrimary = Color(0xFF1A1966), primaryContainer = Color(0xFF34338F), onPrimaryContainer = Color(0xFFE2E0FF),
    background = Color(0xFF111214), surface = Color(0xFF111214), surfaceContainer = Color(0xFF1C1D21), surfaceContainerHigh = Color(0xFF222328),
    surfaceContainerLow = Color(0xFF17181B), onBackground = Color(0xFFE9E9EC), onSurface = Color(0xFFE9E9EC), onSurfaceVariant = Color(0xFF9B9CA4),
    outline = Color(0xFF383A41), outlineVariant = Color(0xFF2A2C31), error = Color(0xFFEF8A8A))
private val LightScheme = lightColorScheme(
    primary = Indigo, onPrimary = Color.White, primaryContainer = Color(0xFFE2E0FF), onPrimaryContainer = Color(0xFF1A1966),
    background = Color(0xFFF6F6F8), surface = Color(0xFFF6F6F8), surfaceContainer = Color.White, surfaceContainerHigh = Color(0xFFEDEDF1),
    surfaceContainerLow = Color(0xFFFBFBFC), onSurfaceVariant = Color(0xFF5E5F66), outline = Color(0xFFC6C6CC), outlineVariant = Color(0xFFE2E2E6))

/** Lens's palette (graphite and indigo, as on the laptop), light or dark with the system. */
@Composable
fun LensTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) DarkScheme else LightScheme, content = content)
}

fun kindIcon(kind: String): ImageVector = when (kind) {
    "voice_note" -> Icons.Outlined.GraphicEq
    "screen_observation" -> Icons.Outlined.Web
    "share" -> Icons.Outlined.Download
    "reminder" -> Icons.Outlined.Notifications
    else -> Icons.Outlined.Notes
}

fun Evidence.instant(): Instant? = runCatching { Instant.parse(timestamp) }.getOrNull()

@Composable
fun relativeTime(e: Evidence): String {
    val at = e.instant() ?: return ""
    return DateUtils.getRelativeTimeSpanString(at.toEpochMilli(), System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString()
}

private val STOPWORDS = setOf("the", "and", "for", "with", "what", "when", "where", "which", "who", "how", "did", "does", "was", "were",
    "are", "about", "this", "that", "from", "have", "has", "had", "will", "can", "you", "your", "our", "his", "her", "its", "they", "them")

/** The quote with the question's words emphasised, so it is clear why this evidence was chosen. */
@Composable
fun highlighted(text: String, query: String): AnnotatedString {
    val mark = SpanStyle(fontWeight = FontWeight.SemiBold, background = MaterialTheme.colorScheme.primary.copy(alpha = 0.16f))
    val words = query.split(Regex("[^\\p{L}\\p{N}]+")).filter { it.length >= 3 && it.lowercase() !in STOPWORDS }
    return buildAnnotatedString {
        append(text)
        for (w in words) {
            var from = 0
            while (true) {
                val at = text.indexOf(w, from, ignoreCase = true)
                if (at < 0) break
                addStyle(mark, at, at + w.length); from = at + w.length
            }
        }
    }
}

/** One piece of evidence: what was remembered, from where and when. */
@Composable
fun EvidenceCard(e: Evidence, query: String = "", compact: Boolean = false, onClick: (() -> Unit)? = null) {
    val body: @Composable ColumnScope.() -> Unit = {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(kindIcon(e.kind), null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(e.app, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (e.window.isNotEmpty()) Text("· ${e.window}", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                Spacer(Modifier.weight(1f))
                Text(relativeTime(e), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            SelectionContainer {
                Text(highlighted(e.quote, query), style = if (compact) MaterialTheme.typography.bodyMedium else MaterialTheme.typography.bodyLarge,
                    maxLines = if (compact) 3 else Int.MAX_VALUE, overflow = TextOverflow.Ellipsis)
            }
            if (e.device.isNotEmpty() && e.device != "phone") Text(e.device, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        }
    }
    val shape = RoundedCornerShape(18.dp)
    val colors = CardDefaults.cardColors(containerColor = if (compact) MaterialTheme.colorScheme.surfaceContainerLow else MaterialTheme.colorScheme.surfaceContainer)
    if (onClick != null) Card(onClick = onClick, shape = shape, colors = colors, modifier = Modifier.fillMaxWidth(), content = body)
    else Card(shape = shape, colors = colors, modifier = Modifier.fillMaxWidth(), content = body)
}

/** A short notice (laptop unreachable, permission missing). */
@Composable
fun Notice(text: String, icon: ImageVector = Icons.Outlined.Info) {
    Surface(color = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.5f), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, Modifier.size(18.dp))
            Text(text, style = MaterialTheme.typography.bodySmall)
        }
    }
}

/** Empty or abstaining state: a symbol, a title and one line of explanation. */
@Composable
fun EmptyState(icon: ImageVector, title: String, detail: String, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth().padding(vertical = 40.dp, horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Icon(icon, null, Modifier.size(44.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(detail, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}

/** Whether this phone can recognise speech on the device itself (Android 12+ with an on-device model). */
@Composable
fun onDeviceSpeech(): Boolean {
    val context = LocalContext.current
    return Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && android.speech.SpeechRecognizer.isOnDeviceRecognitionAvailable(context)
}
