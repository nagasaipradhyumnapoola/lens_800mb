package ai.secondbrain.lens

import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun SettingsScreen(repo: LensRepository, erased: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var pairing by remember { mutableStateOf(false) }
    var paired by remember { mutableStateOf(repo.laptop != null) }
    var pending by remember { mutableIntStateOf(repo.pending()) }
    var sending by remember { mutableStateOf(false) }
    var observing by remember { mutableStateOf(repo.observeScreen) }
    var confirmUnpair by remember { mutableStateOf(false) }
    var confirmErase by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }

    if (pairing) { PairScreen(repo, onClose = { pairing = false }) { paired = true; pairing = false }; return }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Lens", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.padding(top = 8.dp))

        Section("Laptop", "Questions search your laptop's whole memory over an encrypted link on your Wi-Fi. Your laptop approves this phone once; devices of another Lens account can never pair.") {
            if (paired) {
                SettingRow(Icons.Outlined.Verified, "Paired with your laptop", tint = MaterialTheme.colorScheme.primary)
                SettingRow(Icons.Outlined.Schedule, "Waiting to send: $pending") {
                    if (pending > 0) TextButton(enabled = !sending, onClick = {
                        sending = true
                        scope.launch { withContext(Dispatchers.IO) { repo.flush() }; pending = repo.pending(); sending = false }
                    }) { Text(if (sending) "Sending…" else "Send now") }
                }
                TextButton(onClick = { confirmUnpair = true }) { Text("Unpair", color = MaterialTheme.colorScheme.error) }
            } else {
                Button(onClick = { pairing = true }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Outlined.Laptop, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text("Pair with your laptop")
                }
            }
        }

        Section("Phone screen", "Off unless you turn it on here and enable “Lens screen memory” in Android accessibility settings. Never reads passwords, password managers or private tabs; either switch stops it at once.") {
            SettingRow(Icons.Outlined.Visibility, "Observe phone screen") {
                Switch(observing, { on ->
                    repo.observeScreen = on; observing = on
                    if (on) context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                })
            }
        }

        Section("Privacy", null) {
            SettingRow(Icons.Outlined.PanTool, "Remembers only what you allow")
            SettingRow(Icons.Outlined.Lock, "Encrypted on this phone, never in cloud backups")
            SettingRow(Icons.Outlined.GraphicEq, "Voice recognised on this phone, never stored")
            TextButton(onClick = { confirmErase = true }) { Text("Erase this phone's memory", color = MaterialTheme.colorScheme.error) }
            message?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }

        Section("About", null) {
            val version = runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull() ?: ""
            SettingRow(Icons.Outlined.Info, "Lens $version · Android ${Build.VERSION.RELEASE}")
        }
    }

    if (confirmUnpair) AlertDialog(onDismissRequest = { confirmUnpair = false }, title = { Text("Unpair your laptop?") },
        text = { Text("This phone stops asking your laptop. It can pair again only with a laptop of the same Lens account.") },
        confirmButton = { TextButton(onClick = { repo.unpair(); paired = false; confirmUnpair = false }) { Text("Unpair", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClick = { confirmUnpair = false }) { Text("Cancel") } })
    if (confirmErase) AlertDialog(onDismissRequest = { confirmErase = false }, title = { Text("Erase this phone's memory?") },
        text = { Text("Deletes every note and screen memory Lens stored on this phone, and its encryption keys. Your laptop's memory is not touched. This cannot be undone.") },
        confirmButton = { TextButton(onClick = {
            confirmErase = false
            scope.launch { withContext(Dispatchers.IO) { repo.eraseLocal() }; pending = repo.pending(); message = "This phone's memory was erased."; erased() }
        }) { Text("Erase", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClick = { confirmErase = false }) { Text("Cancel") } })
}

@Composable
private fun Section(title: String, footer: String?, content: @Composable ColumnScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp, start = 4.dp))
        Surface(shape = RoundedCornerShape(18.dp), color = MaterialTheme.colorScheme.surfaceContainer, modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp), content = content)
        }
        footer?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 4.dp)) }
    }
}

@Composable
private fun SettingRow(icon: ImageVector, text: String, tint: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.onSurfaceVariant,
                trailing: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().heightIn(min = 44.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Icon(icon, null, Modifier.size(20.dp), tint = tint)
        Text(text, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
        trailing()
    }
}

/**
 * Pairing: scan (or paste) the code Lens shows on the laptop, then approve this phone on the laptop when both show the
 * same 8-digit code. Nothing is shared until the laptop's user approves.
 */
@Composable
fun PairScreen(repo: LensRepository, onClose: () -> Unit, onPaired: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var verification by remember { mutableStateOf<String?>(null) }

    fun use(text: String) {
        val parsed = PairingCode.parse(text)
        if (parsed == null) { message = "That is not a Lens pairing code."; return }
        busy = true; message = null
        scope.launch {
            val error = withContext(Dispatchers.IO) { repo.pair(parsed, Build.MODEL ?: "Phone") { shown -> verification = shown } }
            busy = false; verification = null
            if (error == null) onPaired() else message = error
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        IconButton(onClick = onClose, enabled = !busy) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") }
        Text("Pair your laptop", style = MaterialTheme.typography.headlineMedium)
        val shown = verification
        if (shown != null) {
            Surface(shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.surfaceContainer, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Text("Approve this phone on your laptop only if it shows the same code", color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                    Text(shown, fontSize = 40.sp, fontWeight = FontWeight.SemiBold, fontFamily = FontFamily.Monospace)
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp); Text("Waiting for approval…")
                    }
                }
            }
        } else {
            Text("On your laptop, open Lens › Devices and choose Pair a device. Then scan the code it shows.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(enabled = !busy, modifier = Modifier.fillMaxWidth().height(52.dp), onClick = {
                val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
                GmsBarcodeScanning.getClient(context, options).startScan()
                    .addOnSuccessListener { b -> b.rawValue?.let(::use) }
                    .addOnFailureListener { message = "The scanner is not available on this phone. Paste the code instead." }
            }) { Icon(Icons.Outlined.QrCodeScanner, null); Spacer(Modifier.width(10.dp)); Text("Scan the code") }
            OutlinedTextField(code, { code = it }, label = { Text("Or paste the pairing code") }, modifier = Modifier.fillMaxWidth(), minLines = 3,
                shape = RoundedCornerShape(14.dp))
            OutlinedButton(enabled = !busy && code.isNotBlank(), onClick = { use(code) }, modifier = Modifier.fillMaxWidth()) { Text("Pair") }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        }
        message?.let { Notice(it, Icons.Outlined.ErrorOutline) }
    }
}
