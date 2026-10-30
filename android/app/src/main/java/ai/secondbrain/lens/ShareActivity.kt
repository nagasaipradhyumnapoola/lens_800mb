package ai.secondbrain.lens

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import kotlin.concurrent.thread

/** "Share to Lens": text shared from any app becomes a memory on this phone (and on the paired laptop when reachable). */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = intent?.takeIf { it.action == Intent.ACTION_SEND }?.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.isNotBlank() }
        if (text == null) { finish(); return }
        val repo = LensRepository(applicationContext)
        thread {
            val saved = repo.remember(text, kind = "share")
            val message = when {
                saved.error == "sensitive_content_excluded" -> "Not saved: Lens never stores passwords, codes or card details."
                saved.error != null && saved.delivered == 0 -> "Lens could not save this (${saved.error})."
                saved.delivered > 0 -> "Saved to Lens."
                repo.laptop != null -> "Saved on this phone; will sync when your laptop is reachable."
                else -> "Saved on this phone."
            }
            runOnUiThread { Toast.makeText(this, message, Toast.LENGTH_SHORT).show(); finish() }
        }
    }
}
