package ai.secondbrain.lens

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.cert.CertificateException

class LinkLogicTest {
    private val fp = "a".repeat(64)
    private val token = "b".repeat(32)
    private fun code(extra: String = "") = """{"v":1,"hosts":["192.168.1.20"],"port":47821,"fp":"$fp","token":"$token"$extra}"""

    @Test fun validPairingCodeParses() {
        val c = PairingCode.parse(code())!!
        assertEquals(listOf("192.168.1.20"), c.hosts); assertEquals(47821, c.port); assertEquals(fp, c.fingerprint); assertEquals(token, c.token)
    }

    @Test fun malformedPairingCodesAreRejected() {
        assertNull(PairingCode.parse("not json"))
        assertNull(PairingCode.parse(code().replace("\"v\":1", "\"v\":2")))
        assertNull(PairingCode.parse(code().replace(fp, "zz")))
        assertNull(PairingCode.parse(code().replace(token, "short")))
        assertNull(PairingCode.parse(code().replace("47821", "70000")))
        assertNull(PairingCode.parse(code().replace("[\"192.168.1.20\"]", "[]")))
    }

    @Test fun fingerprintIsSha256Hex() {
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", certificateFingerprint("abc".toByteArray()))
    }

    @Test fun pinnedTrustRejectsMissingChain() {
        assertThrows(CertificateException::class.java) { PinnedTrustManager(fp).checkServerTrusted(emptyArray(), "EC") }
        assertThrows(CertificateException::class.java) { PinnedTrustManager(fp).checkClientTrusted(emptyArray(), "EC") }
    }

    @Test fun lineChannelFramesOneResponsePerRequest() {
        val out = ByteArrayOutputStream()
        val ch = LineChannel(ByteArrayInputStream("{\"ok\":true,\"n\":1}\n{\"ok\":false}\n".toByteArray()), out)
        assertEquals(1, ch.ask(JSONObject().put("op", "ping")).getInt("n"))
        assertFalse(ch.ask(JSONObject().put("op", "x")).getBoolean("ok"))
        assertEquals("{\"op\":\"ping\"}\n{\"op\":\"x\"}\n", out.toString(Charsets.UTF_8.name()))
    }

    @Test fun evidenceParsingShowsAbstentionAsEmpty() {
        assertTrue(parseEvidence(JSONObject("{\"ok\":true,\"not_found\":true,\"results\":[]}")).isEmpty())
        val e = parseEvidence(JSONObject("""{"ok":true,"not_found":false,"results":[{"source":{"text":"full","source_application":"chrome.exe",
            "source_locator":"window:Paper - Chrome","timestamp":"2026-10-27T09:30:00Z"},"evidence":{"quote":"<b>q</b>"}}]}"""))
        assertEquals(1, e.size); assertEquals("<b>q</b>", e[0].quote); assertEquals("Chrome", e[0].app); assertEquals("Paper - Chrome", e[0].window)
    }
}
