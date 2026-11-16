package ai.secondbrain.lens

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Spoken notes and questions, recognised on this phone only (SpeechRecognizer.createOnDeviceSpeechRecognizer, Android 12+):
 * the audio is never stored and never leaves the device. Without an on-device recogniser Lens says so instead of using a
 * server. Main thread only.
 */
class Dictation(private val context: Context) {
    var running by mutableStateOf(false); private set
    var transcript by mutableStateOf(""); private set
    var problem by mutableStateOf<String?>(null); private set
    private var recognizer: SpeechRecognizer? = null

    fun start() {
        problem = null
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || !SpeechRecognizer.isOnDeviceRecognitionAvailable(context)) {
            problem = "On-device speech recognition is not available on this phone. Lens never sends your voice off the phone."
            return
        }
        transcript = ""
        val r = SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        r.setRecognitionListener(object : RecognitionListener {
            override fun onPartialResults(b: Bundle?) { first(b)?.let { transcript = it } }
            override fun onResults(b: Bundle?) { first(b)?.let { transcript = it }; stop() }
            override fun onError(error: Int) {
                if (error != SpeechRecognizer.ERROR_NO_MATCH && error != SpeechRecognizer.ERROR_SPEECH_TIMEOUT)
                    problem = if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) "Allow the microphone for Lens to speak notes."
                              else "Speech was not recognised. Try again."
                stop()
            }
            override fun onReadyForSpeech(p: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(v: Float) {}
            override fun onBufferReceived(b: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(t: Int, p: Bundle?) {}
        })
        r.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true))
        recognizer = r
        running = true
    }

    fun stop() {
        recognizer?.run { stopListening(); destroy() }
        recognizer = null
        running = false
    }

    private fun first(b: Bundle?) = b?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf { it.isNotBlank() }
}
