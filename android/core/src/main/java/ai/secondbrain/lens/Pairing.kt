package ai.secondbrain.lens

import org.json.JSONObject
import java.security.MessageDigest

/** The pairing code shown by the laptop (QR or text): where to connect, which certificate to trust, one-time token. */
data class PairingCode(val hosts: List<String>, val port: Int, val fingerprint: String, val token: String) {
    companion object {
        private val HEX64 = Regex("^[0-9a-f]{64}$")
        private val HEX32 = Regex("^[0-9a-f]{32}$")

        /** Parses and validates a pairing code; returns null for anything malformed. */
        fun parse(text: String): PairingCode? = runCatching {
            val o = JSONObject(text.trim())
            if (o.optInt("v") != 1) return null
            val hostsJson = o.getJSONArray("hosts")
            val hosts = (0 until hostsJson.length()).map { hostsJson.getString(it) }.filter { it.isNotBlank() && it.length <= 253 }
            val port = o.getInt("port")
            val fp = o.getString("fp").lowercase()
            val token = o.getString("token").lowercase()
            if (hosts.isEmpty() || port !in 1..65535 || !HEX64.matches(fp) || !HEX32.matches(token)) null
            else PairingCode(hosts, port, fp, token)
        }.getOrNull()
    }
}

/** SHA-256 of a DER certificate, lower-case hex: the pin compared against the pairing code. */
fun certificateFingerprint(der: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }
