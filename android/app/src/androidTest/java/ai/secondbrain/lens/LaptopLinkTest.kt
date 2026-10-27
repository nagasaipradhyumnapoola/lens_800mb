package ai.secondbrain.lens

import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * End to end against a real laptop link (lens-agent + lens-mesh started by tests/test_android_link.py on the host).
 * The host passes the pairing code as instrumentation argument `pairingCode` (base64 JSON, hosts = ["10.0.2.2"]).
 */
@RunWith(AndroidJUnit4::class)
class LaptopLinkTest {
    @Test fun pairsRecallsAndContributesOverTheEncryptedLink() {
        val arg = InstrumentationRegistry.getArguments().getString("pairingCode")
        assumeTrue("no laptop link provided", arg != null)
        val code = PairingCode.parse(String(Base64.decode(arg, Base64.DEFAULT)))!!
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val repo = LensRepository(context)
        repo.unpair()
        assertNull(repo.pair(code, "Lens test phone"))
        assertNotNull(repo.laptop)

        val evidence = parseEvidence(repo.recall("Halvorsen contract renewal"))
        assertTrue(evidence.isNotEmpty()); assertTrue(evidence[0].quote.contains("Halvorsen"))
        assertTrue(parseEvidence(repo.recall("qwzx unrelated question about nothing stored")).isEmpty())

        assertEquals(1, repo.addNote("Synthetic phone note: the Marlow venue deposit is due Friday."))
        assertEquals(0, repo.pending())

        // a second, wrong pin must never connect
        val wrong = code.copy(fingerprint = "0".repeat(64))
        assertNotNull(repo.pair(wrong, "x"))
        repo.unpair()
    }
}
