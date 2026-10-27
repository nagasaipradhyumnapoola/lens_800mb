package ai.secondbrain.lens

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.spec.ECGenParameterSpec
import java.util.Date
import javax.security.auth.x500.X500Principal

/** This device's link identity: a P-256 key generated inside Android Keystore (never exportable). */
object DeviceIdentity {
    const val ALIAS = "lens-device-identity"

    fun ensure() {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (ks.containsAlias(ALIAS)) return
        val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_NONE)
            .setCertificateSubject(X500Principal("CN=Lens companion"))
            .setCertificateSerialNumber(BigInteger.ONE)
            .setCertificateNotBefore(Date(System.currentTimeMillis() - 3_600_000))
            .setCertificateNotAfter(Date(System.currentTimeMillis() + 20L * 365 * 24 * 3_600_000))
            .build()
        KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply { initialize(spec) }.generateKeyPair()
    }

    /** Fingerprint of this device's certificate, as the laptop lists it. */
    fun fingerprint(): String {
        ensure()
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return certificateFingerprint(ks.getCertificate(ALIAS).encoded)
    }

    fun forget() {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (ks.containsAlias(ALIAS)) ks.deleteEntry(ALIAS)
    }
}
