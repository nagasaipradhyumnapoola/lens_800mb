package ai.secondbrain.lens

import android.os.Debug
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.Instant

/**
 * The phone's own memory with the APK's retrieval models (e5-small INT8 + Lens answerability head v3c through ONNX
 * Runtime): paraphrased questions, abstention, background indexing, idle release. Synthetic notes only; measurements
 * go to logcat under tag LensPhoneBench (debug build, so timings are indicative).
 */
@RunWith(AndroidJUnit4::class)
class SemanticMemoryTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val dir = File(context.cacheDir, "lens-semantic-test")
    private val alias = "lens-semantic-test-wrap"
    private lateinit var models: JSONObject
    private fun open() = LocalMemory.shared(dir, alias) { models }
    private fun rssMb() = File("/proc/self/status").readLines().first { it.startsWith("VmRSS:") }.filter(Char::isDigit).toLong() / 1024
    private fun bench(vararg kv: Pair<String, Any>) = Log.i("LensPhoneBench", JSONObject(kv.toMap()).toString())
    private fun note(m: LocalMemory, id: String, text: String) =
        assertTrue(m.add(id, text, "note", Instant.parse("2026-10-29T10:00:00Z"), "Lens").optBoolean("ok"))
    private fun top(r: JSONObject) = parseEvidence(r).firstOrNull()?.quote.orEmpty()

    @Before fun setUp() {
        LocalMemory.release(); LocalMemory.erase(dir, alias)
        val t = System.nanoTime()
        models = LensModels.install(context, File(context.noBackupFilesDir, "lens-models")) ?: error("this APK ships no models")
        bench("install_ms" to (System.nanoTime() - t) / 1_000_000)
    }
    @After fun tearDown() { LocalMemory.erase(dir, alias) }

    @Test fun paraphrasedQuestionsFindTheirMemoryAndUnrelatedOnesAbstain() {
        val baseline = rssMb()
        val m = open(); assertTrue(m.semantic)
        note(m, "s-dentist", "Synthetic note: Dr. Okafor moved my dentist appointment to Thursday at 3 pm.")
        note(m, "s-car", "Synthetic note: the car needs new winter tyres before the trip to Innsbruck.")
        note(m, "s-wifi", "Synthetic note: the guest network at the cabin is called Fjordlight.")
        m.indexNow()
        for (i in 0 until 100) assertTrue(m.request(JSONObject().put("op", "add").put("consent", true).put("id", "s-filler-$i")  // raw: no background indexing
            .put("text", "Synthetic filler $i: grocery list item ${listOf("oats", "lentils", "rice", "apples", "tea")[i % 5]} number $i.")
            .put("language", "und").put("timestamp", "2026-10-29T10:00:00Z").put("kind", "note").put("device", "phone").put("provenance", "test")).optBoolean("ok"))
        var t = System.nanoTime(); val indexed = m.indexNow()
        bench("index_100_ms" to (System.nanoTime() - t) / 1_000_000, "rss_after_index_mb" to rssMb(), "rss_before_mb" to baseline)
        assertTrue(indexed.toString(), indexed.optBoolean("ok")); assertEquals(0L, indexed.optLong("pending_sources"))

        // ranking without the answer gate: the paraphrase shares no content word with the note
        val ranked = m.request(JSONObject().put("op", "recall").put("query", "When is my visit to the tooth doctor?").put("limit", 3).put("abstain", false))
        assertTrue(ranked.toString(), top(ranked).contains("Okafor"))
        // with the answer gate (the product path): whether it answers is reported, not asserted; gate quality is
        // measured on the laptop harness. A question nothing stored answers must abstain.
        t = System.nanoTime(); val gated = m.recall("When is my visit to the tooth doctor?")
        val tyres = m.recall("What does my vehicle need for the cold season?")
        bench("recall_warm_ms" to (System.nanoTime() - t) / 1_000_000, "gate_answered_dentist" to top(gated).contains("Okafor"),
            "gate_answered_tyres" to top(tyres).contains("tyres"), "rss_models_loaded_mb" to rssMb(), "pss_kb" to Debug.getPss(),
            // compared with lens-engine on Windows over the same notes (docs/VERIFICATION.md): same models, same scores
            "dentist_best_rerank" to gated.opt("best_rerank").toString(), "dentist_best_semantic" to gated.opt("best_semantic").toString(),
            "tyres_best_rerank" to tyres.opt("best_rerank").toString(), "tyres_best_semantic" to tyres.opt("best_semantic").toString())
        assertTrue(parseEvidence(m.recall("What is the capital of the moon colony on Neptune?")).isEmpty())

        m.unloadModels(); System.gc(); Thread.sleep(500)
        bench("rss_after_unload_mb" to rssMb())
        t = System.nanoTime(); val again = m.request(JSONObject().put("op", "recall").put("query", "name of the cabin wireless network").put("abstain", false))
        bench("recall_cold_ms" to (System.nanoTime() - t) / 1_000_000)
        assertTrue(again.toString(), top(again).contains("Fjordlight"))
    }

    @Test fun newItemsAreEmbeddedInTheBackground() {
        val m = open()
        note(m, "s-bg", "Synthetic note: the spare house key is under the blue flowerpot.")
        val deadline = System.currentTimeMillis() + 60_000
        var embedded = 0L
        while (embedded < 1 && System.currentTimeMillis() < deadline) {
            Thread.sleep(500); embedded = m.request(JSONObject().put("op", "stats")).optLong("embedded_sources")
        }
        assertEquals("background indexing did not embed the note", 1L, embedded)
        val r = m.request(JSONObject().put("op", "recall").put("query", "where did I hide the extra key to my home?").put("mode", "semantic").put("abstain", false))
        assertTrue(r.toString(), top(r).contains("flowerpot"))
    }

    @Test fun aStaleInstallIsReplacedAndReverified() {
        val target = File(context.cacheDir, "lens-models-reinstall")
        assertNotNull(LensModels.install(context, target))
        File(target, "e5/model.onnx").appendBytes(byteArrayOf(0))  // a damaged copy...
        File(target, "installed.json").writeText("stale")             // ...from another APK version: re-copied and re-verified
        assertNotNull(LensModels.install(context, target))
        assertEquals(118346824L, File(target, "e5/model.onnx").length())
        target.deleteRecursively()
    }
}
