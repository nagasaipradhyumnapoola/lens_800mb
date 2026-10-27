package ai.secondbrain.lens

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStream
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.security.KeyStore
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.security.Principal
import java.security.PrivateKey
import javax.net.ssl.SSLEngine
import javax.net.ssl.X509ExtendedKeyManager
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.X509TrustManager

/** Trusts exactly one server certificate: the laptop whose SHA-256 fingerprint came with the pairing code. */
class PinnedTrustManager(private val fingerprint: String) : X509TrustManager {
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val leaf = chain?.firstOrNull() ?: throw CertificateException("no certificate")
        if (certificateFingerprint(leaf.encoded) != fingerprint) throw CertificateException("laptop certificate does not match the pairing code")
    }
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = throw CertificateException("client role only")
    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

/** Newline-delimited JSON request/response framing used by the Lens link (one response per request). */
class LineChannel(input: InputStream, private val output: OutputStream) {
    private val reader = BufferedReader(InputStreamReader(input, Charsets.UTF_8))
    fun ask(request: JSONObject): JSONObject {
        output.write((request.toString() + "\n").toByteArray(Charsets.UTF_8)); output.flush()
        val line = reader.readLine() ?: throw java.io.IOException("link closed")
        if (line.length > 1 shl 20) throw java.io.IOException("response too large")
        return JSONObject(line)
    }
}

/** A TLS 1.3 connection to the paired laptop: client certificate from Android Keystore, server pinned by fingerprint. */
class MeshClient private constructor(private val socket: SSLSocket, private val channel: LineChannel) : AutoCloseable {
    fun ask(request: JSONObject): JSONObject = channel.ask(request)
    override fun close() = socket.close()

    companion object {
        fun connect(hosts: List<String>, port: Int, fingerprint: String, timeoutMs: Int = 8000): MeshClient {
            DeviceIdentity.ensure()
            val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            val keyManager = object : X509ExtendedKeyManager() {  // always presents the Keystore-held device identity
                override fun chooseClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?) = DeviceIdentity.ALIAS
                override fun chooseEngineClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, engine: SSLEngine?) = DeviceIdentity.ALIAS
                override fun getCertificateChain(alias: String?) = arrayOf(keyStore.getCertificate(DeviceIdentity.ALIAS) as X509Certificate)
                override fun getPrivateKey(alias: String?) = keyStore.getKey(DeviceIdentity.ALIAS, null) as PrivateKey
                override fun getClientAliases(keyType: String?, issuers: Array<out Principal>?) = arrayOf(DeviceIdentity.ALIAS)
                override fun getServerAliases(keyType: String?, issuers: Array<out Principal>?) = emptyArray<String>()
                override fun chooseServerAlias(keyType: String?, issuers: Array<out Principal>?, socket: Socket?) = null
            }
            val context = SSLContext.getInstance("TLSv1.3").apply { init(arrayOf(keyManager), arrayOf(PinnedTrustManager(fingerprint)), null) }
            var last: Exception? = null
            for (host in hosts) {
                try {
                    val raw = Socket().apply { connect(InetSocketAddress(host, port), timeoutMs); soTimeout = 30000 }
                    val tls = context.socketFactory.createSocket(raw, host, port, true) as SSLSocket
                    tls.enabledProtocols = arrayOf("TLSv1.3")
                    tls.startHandshake()
                    return MeshClient(tls, LineChannel(tls.inputStream, tls.outputStream))
                } catch (e: Exception) { last = e }
            }
            throw last ?: java.io.IOException("no laptop address")
        }
    }
}
