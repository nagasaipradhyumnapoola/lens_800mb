package ai.secondbrain.lens

import org.junit.Assert.*
import org.junit.Test

class ScreenTextTest {
    private data class N(override val text: String? = null, override val description: String? = null, override val isPassword: Boolean = false,
                         override val isVisible: Boolean = true, override val children: List<ScreenNode> = emptyList()) : ScreenNode

    @Test fun passwordAndHiddenNodesAreNeverRead() {
        val root = N(children = listOf(N("Synthetic note: the Larkspur review is on Friday."), N("hunter2 secret", isPassword = true,
            children = listOf(N("child of password"))), N("scrolled away", isVisible = false), N(description = "Send button"), N("Send button")))
        assertEquals(listOf("Synthetic note: the Larkspur review is on Friday.", "Send button"), ScreenPolicy.lines(root))
    }

    @Test fun excludedAppsAndPrivateWindowsAreBlocked() {
        assertEquals("excluded_process", ScreenPolicy.block("com.x8bit.bitwarden", "Vault"))
        assertEquals("excluded_process", ScreenPolicy.block("ai.secondbrain.lens", "Lens"))
        assertEquals("private_browsing", ScreenPolicy.block("com.android.chrome", "New Incognito tab"))
        assertEquals("process_unknown", ScreenPolicy.block(null, "x"))
        assertNull(ScreenPolicy.block("com.android.chrome", "Synthetic article"))
    }

    @Test fun onlyNewLinesPerWindow() {
        val d = ScreenDelta()
        assertEquals(listOf("a", "b"), d.newLines("chat", listOf("a", "b")))
        assertEquals(listOf("c"), d.newLines("chat", listOf("a", "b", "c")))
        assertEquals(listOf("a"), d.newLines("mail", listOf("a")))  // another window keeps its own history
    }

    @Test fun contentMustSettle() {
        val s = Settle(2000)
        assertFalse(s.ready(listOf("typing"), 0)); assertFalse(s.ready(listOf("typing."), 500))
        assertFalse(s.ready(listOf("typing."), 2000)); assertTrue(s.ready(listOf("typing."), 2600))
    }

    @Test fun capAndDuplicates() {
        val root = N(children = List(5) { N("same") } + N("x".repeat(50)))
        assertEquals(listOf("same"), ScreenPolicy.lines(root, maxChars = 40))
    }
}
