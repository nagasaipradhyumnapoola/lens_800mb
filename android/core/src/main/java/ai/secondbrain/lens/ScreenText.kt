package ai.secondbrain.lens

/**
 * Screen text from an accessibility tree, with the observer's privacy rules (docs/LENS_V1_SPEC.md §3–5), independent
 * of Android types so it is unit-tested on the JVM:
 * - only nodes visible to the user, never password fields or their subtrees;
 * - never Lens itself, password managers, the lock screen or system authentication prompts;
 * - never a private-browsing window (title markers);
 * - per app and window title, only lines not stored before (a delta), and nothing until the content has settled.
 */
interface ScreenNode {
    val text: String?
    val description: String?
    val isPassword: Boolean
    val isVisible: Boolean
    val children: List<ScreenNode>
}

object ScreenPolicy {
    val excludedPackages = setOf(
        "ai.secondbrain.lens", "com.x8bit.bitwarden", "com.agilebits.onepassword", "com.onepassword.android",
        "keepass2android.keepass2android", "com.kunzisoft.keepass.free", "com.lastpass.lpandroid", "com.dashlane",
        "com.android.systemui", "com.android.settings", "com.google.android.gms", "com.android.keychain",
        "com.android.permissioncontroller", "com.google.android.permissioncontroller")
    val privateMarkers = listOf("incognito", "inprivate", "private browsing", "private tab", "navigation privée", "navegación privada")

    /** Null when the window may be read, otherwise the reason it must not be. */
    fun block(packageName: String?, title: String?): String? = when {
        packageName.isNullOrBlank() -> "process_unknown"
        packageName in excludedPackages -> "excluded_process"
        privateMarkers.any { title.orEmpty().lowercase().contains(it) } -> "private_browsing"
        else -> null
    }

    /** Visible lines in reading order, consecutive duplicates removed, capped at [maxChars]. */
    fun lines(root: ScreenNode, maxChars: Int = 8000, maxNodes: Int = 4000): List<String> {
        val out = ArrayList<String>(); var chars = 0; var nodes = 0
        fun add(s: String?) {
            for (line in s.orEmpty().split('\n')) {
                val t = line.trim(); if (t.isEmpty() || out.lastOrNull() == t || chars + t.length > maxChars) continue
                out += t; chars += t.length + 1
            }
        }
        fun visit(n: ScreenNode) {
            if (++nodes > maxNodes || chars >= maxChars) return
            if (n.isPassword || !n.isVisible) return
            add(n.text ?: n.description)
            for (c in n.children) visit(c)
        }
        visit(root); return out
    }
}

/** Per-window line fingerprints: a capture keeps only lines not seen in that window before. */
class ScreenDelta(private val maxWindows: Int = 32) {
    private val seen = LinkedHashMap<String, MutableSet<String>>(16, 0.75f, true)
    fun newLines(window: String, lines: List<String>): List<String> {
        val known = seen.getOrPut(window) { HashSet() }
        if (seen.size > maxWindows) seen.remove(seen.keys.first())
        val fresh = lines.filter { it !in known }
        known += lines; return fresh
    }
}

/** Content must stay unchanged for [settleMs] before it is captured (streaming text, animations, typing). */
class Settle(private val settleMs: Long = 2000) {
    private var hash = 0; private var since = 0L
    fun ready(content: List<String>, now: Long): Boolean {
        val h = content.hashCode()
        if (h != hash) { hash = h; since = now; return false }
        return now - since >= settleMs
    }
}
