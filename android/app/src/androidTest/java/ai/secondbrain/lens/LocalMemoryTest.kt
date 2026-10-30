package ai.secondbrain.lens

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.KeyStore
import java.time.Instant

/**
 * This phone's own memory (liblens-core.so in the app process): synthetic notes only, in a test directory under a test
 * Keystore alias, so the app's real memory is never touched. Run on the emulator (x86_64) or a device (arm64-v8a).
 */
@RunWith(AndroidJUnit4::class)
class LocalMemoryTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val dir = File(context.cacheDir, "lens-memory-test")
    private val alias = "lens-memory-test-wrap"
    private fun open() = LocalMemory.shared(dir, alias)
    private fun note(m: LocalMemory, id: String, text: String) =
        m.add(id, text, "note", Instant.parse("2026-10-30T09:00:00Z"), "Lens").also { assertTrue(it.toString(), it.optBoolean("ok")) }

    @Before fun clean() { LocalMemory.release(); LocalMemory.erase(dir, alias) }  // another test may hold the app's own store
    @After fun cleanUp() { LocalMemory.erase(dir, alias) }

    @Test fun storesAndRecallsWithoutALaptop() {
        val m = open()
        note(m, "t-1", "Synthetic note: the Marlow venue deposit is due on Friday.")
        note(m, "t-2", "Synthetic note: Quentin prefers the blue slide template.")
        note(m, "t-3", "सिंथेटिक नोट: बजट बैठक गुरुवार को है।")
        val hit = parseEvidence(m.recall("Marlow deposit"))
        assertEquals(1, hit.size); assertTrue(hit[0].quote.contains("Marlow"))
        assertTrue(parseEvidence(m.recall("बजट बैठक")).any { it.quote.contains("बजट") })
        assertTrue(parseEvidence(m.recall("qwzx unrelated question about nothing stored")).isEmpty())
        assertTrue(note(m, "t-1", "Synthetic note: the Marlow venue deposit is due on Friday.").optBoolean("deduplicated"))
    }

    @Test fun textOutsideTheBasicPlaneSurvivesTheBridge() {
        val m = open()
        val text = "Synthetic: Zephyrine sent 🎉 and the rare character 𠀀 (U+20000)."
        note(m, "t-emoji", text)
        val quote = parseEvidence(m.recall("Zephyrine"))[0].quote
        assertTrue(quote, quote.contains("🎉") && quote.contains("𠀀"))
    }

    @Test fun sensitiveContentIsRefused() {
        val r = open().add("t-pw", "Synthetic: my password is hunter2", "note", Instant.now(), "Lens")
        assertFalse(r.optBoolean("ok")); assertEquals("sensitive_content_excluded", r.optString("error"))
    }

    @Test fun filesHoldNoPlaintextAndReopenAfterRestart() {
        val sentinel = "Vexillum-sentinel-7c1e"
        note(open(), "t-s", "Synthetic note with $sentinel inside.")
        LocalMemory.release()  // as after a process restart: native master key forgotten
        val files = dir.walk().filter { it.isFile }.toList()
        assertTrue(files.any { it.name == "memory.db" }); assertTrue(files.any { it.name == "master.key" })
        for (f in files) assertFalse("plaintext in ${f.name}", String(f.readBytes(), Charsets.ISO_8859_1).contains(sentinel))
        assertTrue(parseEvidence(open().recall(sentinel)).isNotEmpty())
    }

    @Test fun lostKeystoreKeyNeverOpensOrStartsOver() {
        note(open(), "t-k", "Synthetic note about the Corvina invoice.")
        LocalMemory.release()
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.deleteEntry(alias)
        val e = assertThrows(IllegalStateException::class.java) { open() }
        assertEquals("key_unavailable", e.message)
        File(dir, "master.key").delete()  // even without the wrapped key file, an existing database is never re-keyed
        assertEquals("key_unavailable", assertThrows(IllegalStateException::class.java) { open() }.message)
    }

    @Test fun eraseDeletesFilesAndKey() {
        note(open(), "t-e", "Synthetic note about the Halloran lease.")
        LocalMemory.erase(dir, alias)
        assertFalse(dir.exists())
        assertFalse(KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.containsAlias(alias))
        assertTrue(parseEvidence(open().recall("Halloran lease")).isEmpty())
    }

    @Test fun malformedRequestsComeBackAsErrors() {
        val m = open()
        assertEquals("unsupported_operation", m.request(JSONObject().put("op", "nope")).optString("error"))
        assertFalse(m.request(JSONObject().put("op", "add").put("consent", true)).optBoolean("ok"))  // fields missing
        assertTrue(m.request(JSONObject().put("op", "stats")).optBoolean("ok"))  // the store still answers
    }
}
