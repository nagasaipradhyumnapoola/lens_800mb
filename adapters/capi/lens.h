/* Lens C API for app shells that are not on the JVM (the iPhone app; tests on Windows): the memory core inside the app's
 * process, and the device side of the Lens link to a paired laptop (TLS 1.3, own P-256 certificate, laptop pinned by the
 * SHA-256 fingerprint from the pairing code). Requests and responses are the engine's JSON protocol as UTF-8 text, the
 * same contract as lens-engine's stdin protocol and the Android library (adapters/android/lens_jni.cpp).
 * Every char* returned is owned by the caller and released with lens_free. Error codes are reason codes, never content. */
#ifndef LENS_CAPI_H
#define LENS_CAPI_H
#ifdef __cplusplus
extern "C" {
#endif
#if defined(_WIN32) && defined(LENS_CAPI_SHARED)
#define LENS_API __declspec(dllexport)
#else
#define LENS_API
#endif

typedef struct lens_store lens_store;
typedef struct lens_link lens_link;

/* Opens (creating on first use) the encrypted database at db_path. models_json is "{}" for keyword-only recall, or the
 * retrieval models as lens-engine's arguments name them (runtime, embedding_model, embedding_tokenizer, embedding_id,
 * reranker_model, reranker_tokenizer, verifier_model, verifier_tokenizer). On failure returns NULL and sets *error. */
LENS_API lens_store* lens_store_open(const char* db_path, const char* models_json, char** error);
/* One request, one response ({"ok":false,"error":code} on failure). Requests on one store are serialised. */
LENS_API char* lens_store_request(lens_store* store, const char* request_json);
LENS_API void lens_store_close(lens_store* store);

/* A new device identity: P-256 private key and self-signed certificate (PEM), and the certificate's fingerprint as the
 * laptop lists it. Returns 0 on success. The caller keeps the key in the platform key store. */
LENS_API int lens_link_identity(char** key_pem, char** cert_pem, char** fingerprint);
/* Fingerprint (SHA-256 of the DER certificate, lower-case hex) of a PEM certificate, or NULL. */
LENS_API char* lens_link_fingerprint(const char* cert_pem);
/* Connects to the first reachable address in hosts_json (a JSON array of strings), TLS 1.3 only, presenting the device
 * identity and accepting only the laptop whose certificate matches fingerprint. NULL and *error on failure
 * (laptop_unreachable, tls_failed, laptop_mismatch, identity_unreadable, invalid_request). */
LENS_API lens_link* lens_link_connect(const char* hosts_json, int port, const char* fingerprint, const char* key_pem,
                                      const char* cert_pem, int timeout_ms, char** error);
/* One request over the link, one response; {"ok":false,"error":"link_closed"} once the connection is gone. */
LENS_API char* lens_link_ask(lens_link* link, const char* request_json);
LENS_API void lens_link_close(lens_link* link);

LENS_API void lens_free(char* text);

#ifdef __cplusplus
}
#endif
#endif
