package ai.secondbrain.lens

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.Executors

/**
 * Phone screen observation (docs/LENS_V1_SPEC.md §3): reads the visible text of the app in front through Android's
 * accessibility tree, never password fields, never excluded apps or private browsing (ScreenPolicy), and queues only new
 * lines per window for the paired laptop. Runs only while the user has enabled this service in Android settings and
 * switched "Observe phone screen" on in Lens; either switch stops it.
 */
class ScreenObserverService : AccessibilityService() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private val delta = ScreenDelta()
    private val settle = Settle(2000)
    private lateinit var repo: LensRepository
    private val check = Runnable { capture() }

    override fun onServiceConnected() { repo = LensRepository(this) }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (!::repo.isInitialized || !repo.observeScreen) return
        main.removeCallbacks(check); main.postDelayed(check, 2200)  // capture after content stops changing
    }

    private fun capture() {
        if (!repo.observeScreen) return
        val root = rootInActiveWindow ?: return
        val pkg = root.packageName?.toString(); val title = windows.firstOrNull { it.isActive }?.title?.toString().orEmpty()
        if (ScreenPolicy.block(pkg, title) != null) return
        val lines = ScreenPolicy.lines(Node(root))
        if (!settle.ready(lines, System.currentTimeMillis())) { main.postDelayed(check, 2200); return }
        val fresh = delta.newLines("$pkg\n$title", lines)
        if (fresh.joinToString("").length < 4) return  // tiny changes (clock, counters) are never stored
        val text = fresh.joinToString("\n")
        io.execute { runCatching { repo.addObservation(text, pkg.orEmpty(), title) } }
    }

    override fun onInterrupt() { main.removeCallbacks(check) }
    override fun onDestroy() { main.removeCallbacks(check); io.shutdown(); super.onDestroy() }

    private class Node(private val n: AccessibilityNodeInfo) : ScreenNode {
        override val text get() = n.text?.toString()
        override val description get() = n.contentDescription?.toString()
        override val isPassword get() = n.isPassword
        override val isVisible get() = n.isVisibleToUser
        override val children: List<ScreenNode> get() = (0 until n.childCount).mapNotNull { n.getChild(it)?.let(::Node) }
    }
}
