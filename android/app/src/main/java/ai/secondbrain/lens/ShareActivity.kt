package ai.secondbrain.lens

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import kotlin.concurrent.thread

/** "Share to Lens": text shared from any app becomes a memory (queued until the laptop is reachable). */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = intent?.takeIf { it.action == Intent.ACTION_SEND }?.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.isNotBlank() }
        val repo = LensRepository(applicationContext)
        when {
            text == null -> { finish(); return }
            repo.laptop == null -> { Toast.makeText(this, "Pair Lens with your laptop first.", Toast.LENGTH_LONG).show(); finish(); return }
        }
        thread {
            val delivered = repo.addNote(text!!, kind = "share")
            runOnUiThread {
                Toast.makeText(this, if (delivered > 0) "Saved to Lens." else "Saved; will sync when your laptop is reachable.", Toast.LENGTH_SHORT).show()
                finish()
            }
        }
    }
}
