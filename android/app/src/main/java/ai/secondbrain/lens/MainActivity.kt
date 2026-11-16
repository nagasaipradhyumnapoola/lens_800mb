package ai.secondbrain.lens

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val repo = LensRepository(applicationContext)
        setContent { LensTheme { LensApp(repo) } }
    }
}

private enum class Tab(val label: String, val icon: ImageVector) {
    Ask("Ask", Icons.Outlined.Search), Remember("Remember", Icons.Outlined.AddCircleOutline),
    Memories("Memories", Icons.Outlined.History), Settings("Lens", Icons.Outlined.Settings)
}

/** This phone's memory works on its own; pairing with a laptop is optional and adds the laptop's whole memory. */
@Composable
fun LensApp(repo: LensRepository) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("lens-ui", android.content.Context.MODE_PRIVATE) }
    var onboarded by remember { mutableStateOf(prefs.getBoolean("onboarded", false)) }
    var tab by rememberSaveable { mutableStateOf(Tab.Ask) }
    var memoriesVersion by remember { mutableIntStateOf(0) }  // bumped when something is stored, deleted or erased
    val appScope = rememberCoroutineScope()
    val askState = remember { AskState(repo, appScope) }
    if (!onboarded) {
        Onboarding { prefs.edit().putBoolean("onboarded", true).apply(); onboarded = true }
        return
    }
    Scaffold(bottomBar = {
        NavigationBar {
            for (t in Tab.entries) NavigationBarItem(selected = tab == t, onClick = { tab = t }, icon = { Icon(t.icon, null) }, label = { Text(t.label) })
        }
    }) { padding ->
        Box(Modifier.padding(padding).consumeWindowInsets(padding)) {
            when (tab) {
                Tab.Ask -> AskScreen(repo, askState)
                Tab.Remember -> RememberScreen(repo) { memoriesVersion++ }
                Tab.Memories -> MemoriesScreen(repo, memoriesVersion) { memoriesVersion++ }
                Tab.Settings -> SettingsScreen(repo) { memoriesVersion++ }
            }
        }
    }
}

/** First run: what Lens on the phone does and does not do, before anything is stored. */
@Composable
private fun Onboarding(done: () -> Unit) {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(Modifier.fillMaxSize().safeDrawingPadding().padding(28.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
            Spacer(Modifier.height(16.dp))
            Icon(Icons.Outlined.Adjust, null, Modifier.size(56.dp), tint = MaterialTheme.colorScheme.primary)
            Text("Your memory, private to you", style = MaterialTheme.typography.headlineLarge)
            Point(Icons.Outlined.PanTool, "Only what you allow", "Notes, voice and things you share. Reading your screen stays off unless you turn it on.")
            Point(Icons.Outlined.Lock, "Encrypted on this phone", "Kept on this phone only, never in cloud backups. Voice is recognised here and never stored.")
            Point(Icons.Outlined.Laptop, "Your laptop's memory, here", "Pair with Lens on your laptop to ask everything it remembers, over an encrypted link on your Wi-Fi.")
            Point(Icons.Outlined.VerifiedUser, "Answers with evidence", "Every answer shows where it came from. When nothing supports an answer, Lens says so instead of guessing.")
            Spacer(Modifier.weight(1f))
            Button(onClick = done, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("Continue") }
        }
    }
}

@Composable
private fun Point(icon: ImageVector, title: String, detail: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, null, Modifier.size(28.dp), tint = MaterialTheme.colorScheme.primary)
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(detail, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
