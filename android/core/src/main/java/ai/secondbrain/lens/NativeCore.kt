package ai.secondbrain.lens

/**
 * The memory core (adapters/android/lens_jni.cpp, liblens-core.so) running inside this app. Requests and responses are the
 * engine's JSON protocol as UTF-8 bytes. Use [LocalMemory]; it owns the master key and serialises access.
 */
internal object NativeCore {
    init { System.loadLibrary("lens-core") }
    @JvmStatic external fun setMasterKey(key: ByteArray)
    @JvmStatic external fun clearMasterKey()
    /** Opens (creating on first use) the encrypted database; [models] is {} or [LensModels.install]'s configuration (UTF-8 JSON). Throws IllegalStateException(reason code). */
    @JvmStatic external fun open(path: ByteArray, models: ByteArray): Long
    @JvmStatic external fun request(handle: Long, request: ByteArray): ByteArray
    @JvmStatic external fun close(handle: Long)
}
