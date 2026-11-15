package com.scrapp.app.glasses

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.location.Location
import android.location.LocationManager
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.exifinterface.media.ExifInterface
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.removeCamera
import com.meta.wearable.dat.camera.types.PhotoData
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.StreamState
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import com.meta.wearable.dat.core.session.DeviceSessionState
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.meta.wearable.dat.core.types.RegistrationState
import com.meta.wearable.dat.core.voiceinvocations.startVoiceInvocationsStream
import com.meta.wearable.dat.core.voiceinvocations.types.actions.LaunchApp
import com.meta.wearable.dat.inputs.Inputs
import com.meta.wearable.dat.inputs.addInputs
import com.meta.wearable.dat.inputs.types.CapturePressType
import com.meta.wearable.dat.inputs.types.InputEvent
import com.meta.wearable.dat.inputs.types.InputSource
import com.meta.wearable.dat.inputs.types.InputsConfiguration
import com.meta.wearable.dat.mockdevice.MockDeviceKit
import com.meta.wearable.dat.mockdevice.api.GlassesModel
import com.meta.wearable.dat.mockdevice.api.MockGlasses
import com.meta.wearable.dat.mockdevice.api.camera.CameraFacing
import com.meta.wearable.dat.speech.Speech
import com.meta.wearable.dat.speech.addSpeech
import com.meta.wearable.dat.speech.types.SpeechState
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.time.Instant
import java.util.concurrent.Executors
import kotlin.coroutines.resume
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * Owns the Meta Wearables session for the whole app process.
 *
 * Triggers: on-glasses speech ("scrapbook that"), the physical capture button (Inputs), or the
 * app. Each trigger grabs a still from the glasses camera stream, tags it with GPS and writes it
 * to the [Outbox]; Flutter uploads it. Everything here keeps running inside [GlassesService]
 * while the phone is locked in a pocket.
 */
@SuppressLint("StaticFieldLeak")
object GlassesManager {
    private const val TAG = "ScrappGlasses"
    private const val DEBOUNCE_MS = 2500L

    data class Status(
        val registration: String = "UNKNOWN",
        val deviceName: String = "",
        val connected: Boolean = false,
        val session: String = "NONE",
        val speech: String = "OFF",
        val inputs: String = "OFF",
        val camera: String = "OFF",
        val armed: Boolean = false,
        val mock: Boolean = false,
        val huntId: String? = null,
    ) {
        fun toMap(): Map<String, Any?> = mapOf(
            "type" to "status", "registration" to registration, "deviceName" to deviceName,
            "connected" to connected, "session" to session, "speech" to speech, "inputs" to inputs,
            "camera" to camera, "armed" to armed, "mock" to mock, "huntId" to huntId,
        )
    }

    data class ArmConfig(val warmCamera: Boolean = true, val voice: Boolean = true, val button: Boolean = true)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var appContext: Context

    private val _status = MutableStateFlow(Status())
    val status: StateFlow<Status> = _status.asStateFlow()
    val events = MutableSharedFlow<Map<String, Any?>>(extraBufferCapacity = 64)

    var initialized = false
        private set
    var pendingVoiceLaunch = false

    private var config = ArmConfig()
    private var session: DeviceSession? = null
    private var camera: Camera? = null
    private var speech: Speech? = null
    private var inputs: Inputs? = null
    private val streamState = MutableStateFlow<StreamState?>(null)
    private val sessionJobs = mutableListOf<Job>()
    private var reconnectJob: Job? = null
    private var deviceJob: Job? = null
    private var closeVoiceInvocations: (() -> Unit)? = null
    private var speechStarted = false

    private val captureMutex = Mutex()
    private var lastTriggerAt = 0L
    private var activeHuntId: String? = null
    private var tts: TextToSpeech? = null
    private var mockGlasses: MockGlasses? = null
    private val locationExecutor = Executors.newSingleThreadExecutor()

    private fun update(f: (Status) -> Status) = _status.update(f)
    private fun emit(map: Map<String, Any?>) { events.tryEmit(map) }
    private fun emitError(msg: String) { Log.w(TAG, msg); emit(mapOf("type" to "captureFailed", "reason" to msg)) }

    // ------------------------------------------------------------------------------- lifecycle
    /** Call after BLUETOOTH_CONNECT is granted (the SDK cannot discover devices without it). */
    fun initialize(ctx: Context): Boolean {
        if (initialized) return true
        appContext = ctx.applicationContext
        // MockDeviceKit.enable() may already have initialized the SDK, so a failure here is logged,
        // not fatal; real problems surface on registration/session calls.
        Wearables.initialize(appContext).onFailure { error, _ ->
            Log.w(TAG, "Wearables.initialize: ${error.description}")
        }
        initialized = true
        tts = TextToSpeech(appContext) { }

        scope.launch {
            Wearables.registrationState.collect { st ->
                update { it.copy(registration = st.toString()) }
                if (st == RegistrationState.REGISTERED) startVoiceInvocations()
            }
        }
        scope.launch {
            Wearables.devices.collect { ids ->
                update { it.copy(connected = ids.isNotEmpty()) }
                deviceJob?.cancel()
                val id = ids.firstOrNull() ?: return@collect
                deviceJob = scope.launch {
                    Wearables.devicesMetadata[id]?.collect { device -> update { it.copy(deviceName = device.name) } }
                }
            }
        }
        scope.launch { status.collect { emit(it.toMap()) } }
        return true
    }

    fun register(activity: android.app.Activity) = Wearables.startRegistration(activity)
    fun unregister(activity: android.app.Activity) = Wearables.startUnregistration(activity)

    // ---------------------------------------------------------------------------------- arming
    fun arm(cfg: ArmConfig) {
        check(initialized) { "Glasses not initialized yet" }
        config = cfg
        GlassesService.start(appContext)
        update { it.copy(armed = true) }
        openSession()
    }

    fun disarm() {
        update { it.copy(armed = false) }
        reconnectJob?.cancel()
        closeSession()
        GlassesService.stop(appContext)
    }

    private fun openSession() {
        if (session != null) return
        Wearables.createSession(AutoDeviceSelector()).fold(
            onSuccess = { s ->
                session = s
                // Collect before start() so no transition is missed.
                sessionJobs += scope.launch { s.errors.collect { e -> Log.w(TAG, "session: ${e.description}") } }
                sessionJobs += scope.launch {
                    s.state.collect { st ->
                        update { it.copy(session = st.toString()) }
                        when (st) {
                            DeviceSessionState.STARTED -> onSessionStarted(s)
                            DeviceSessionState.STOPPED -> onSessionStopped()
                            else -> Unit
                        }
                    }
                }
                s.start()
            },
            onFailure = { e, _ ->
                emitError("Could not open glasses session: ${e.description}")
                scheduleReconnect()
            },
        )
    }

    private fun onSessionStarted(s: DeviceSession) {
        if (config.voice && speech == null) attachSpeech(s)
        if (config.button && inputs == null) attachInputs(s)
        if (config.warmCamera && camera == null) scope.launch { ensureStreaming(s) }
    }

    private fun onSessionStopped() {
        // STOPPED is terminal for this session object: drop it and make a new one if still armed
        // (glasses folded, taken off, out of range...).
        clearCapabilities()
        session = null
        if (_status.value.armed) scheduleReconnect()
    }

    private fun scheduleReconnect() {
        if (reconnectJob?.isActive == true) return
        reconnectJob = scope.launch {
            delay(4000)
            if (_status.value.armed && session == null) openSession()
        }
    }

    private fun closeSession() {
        val s = session
        clearCapabilities()
        session = null
        s?.stop()
        update { it.copy(session = "NONE") }
    }

    private fun clearCapabilities() {
        sessionJobs.forEach { it.cancel() }
        sessionJobs.clear()
        camera = null
        speech = null
        inputs = null
        speechStarted = false
        streamState.value = null
        update { it.copy(speech = "OFF", inputs = "OFF", camera = "OFF") }
    }

    // ------------------------------------------------------------------------- voice (speech)
    private fun attachSpeech(s: DeviceSession) {
        s.addSpeech().fold(
            onSuccess = { sp ->
                speech = sp
                sessionJobs += scope.launch {
                    sp.transcriptions.collect { r -> if (r != null) onTranscript(r.text, r.isFinal) }
                }
                sessionJobs += scope.launch {
                    sp.state.collect { st ->
                        update { it.copy(speech = st.toString()) }
                        if (st == SpeechState.STARTED) speechStarted = true
                        // The recognizer can end on its own; restart it while armed.
                        if (st == SpeechState.STOPPED && speechStarted && _status.value.armed) {
                            delay(800)
                            sp.start()
                        }
                    }
                }
                sp.start().onFailure { e, _ -> emitError("Voice unavailable: ${e.description}") }
            },
            onFailure = { e, _ ->
                update { it.copy(speech = "UNAVAILABLE") }
                emitError("Voice unavailable (grant microphone access in Settings): ${e.description}")
            },
        )
    }

    private fun onTranscript(text: String, isFinal: Boolean) {
        emit(mapOf("type" to "transcript", "text" to text, "isFinal" to isFinal))
        val m = VoiceCommandMatcher.match(text) ?: return
        if (m.command == "found") {
            // Only meaningful during a hunt; otherwise it is just someone talking, so don't take a photo.
            if (activeHuntId == null) return
            trigger(source = "voice", transcript = text, announce = "Checking")
            return
        }
        // Partials make the shutter feel instant; the debounce stops the final from firing twice.
        trigger(source = "voice", transcript = text, prompt = m.prompt)
    }

    // ------------------------------------------------------------------- capture button (Inputs)
    private fun attachInputs(s: DeviceSession) {
        s.addInputs(InputsConfiguration(sources = setOf(InputSource.CAPTURE_BUTTON), consumeBack = false)).fold(
            onSuccess = { inp ->
                inputs = inp
                sessionJobs += scope.launch { inp.state.collect { st -> update { it.copy(inputs = st.toString()) } } }
                sessionJobs += scope.launch {
                    inp.events.collect { ev ->
                        if (ev is InputEvent.Capture && ev.pressType == CapturePressType.SHORT_PRESS) trigger(source = "button")
                    }
                }
            },
            onFailure = { e, _ ->
                update { it.copy(inputs = "UNAVAILABLE") }
                Log.w(TAG, "Inputs unavailable: ${e.description}")
            },
        )
    }

    // ---------------------------------------------------------------------------------- camera
    private suspend fun ensureStreaming(s: DeviceSession): com.meta.wearable.dat.camera.Stream? {
        if (camera == null) {
            val perm = Wearables.checkPermissionStatus(Permission.CAMERA).getOrDefault(PermissionStatus.Denied)
            if (perm != PermissionStatus.Granted) {
                emitError("Camera access not granted. Open Settings → Camera access.")
                return null
            }
            // HIGH = 720x1280. 2 fps when kept warm (battery), 15 fps for on-demand bursts.
            val cfg = StreamConfiguration(videoQuality = VideoQuality.HIGH, frameRate = if (config.warmCamera) 2 else 15)
            s.addCamera(cfg).fold(
                onSuccess = { c ->
                    camera = c
                    sessionJobs += scope.launch {
                        c.stream.state.collect { st ->
                            streamState.value = st
                            update { it.copy(camera = st.toString()) }
                        }
                    }
                    c.stream.start().onFailure { e, _ -> emitError("Camera stream failed: ${e.description}") }
                },
                onFailure = { e, _ -> emitError("Camera unavailable: ${e.description}") },
            )
        }
        val c = camera ?: return null
        val ok = withTimeoutOrNull(8000) { streamState.first { it == StreamState.STREAMING } }
        return if (ok != null) c.stream else null
    }

    private fun releaseCamera() {
        val c = camera ?: return
        camera = null
        streamState.value = null
        c.stop()
        session?.removeCamera()
        update { it.copy(camera = "OFF") }
    }

    // ---------------------------------------------------------------------------------- capture
    fun trigger(source: String, transcript: String? = null, prompt: String? = null, announce: String = "Scrapbooking") {
        val now = SystemClock.elapsedRealtime()
        if (now - lastTriggerAt < DEBOUNCE_MS) return
        lastTriggerAt = now
        emit(mapOf("type" to "trigger", "source" to source))
        scope.launch { capture(source, transcript, prompt, announce) }
    }

    private suspend fun capture(source: String, transcript: String?, prompt: String?, announce: String) = captureMutex.withLock {
        val s = session
        if (s == null) {
            emitError("Glasses not connected")
            return@withLock
        }
        speak(announce)
        val stream = ensureStreaming(s)
        if (stream == null) {
            speak("Camera not ready")
            return@withLock
        }
        val result = withTimeoutOrNull(12_000) { stream.capturePhoto() }
        var jpeg: ByteArray? = null
        var failure: String? = null
        if (result == null) failure = "Photo timed out"
        else result.fold(
            onSuccess = { data -> jpeg = toJpeg(data) },
            onFailure = { e, _ -> failure = e.description },
        )
        if (!config.warmCamera) releaseCamera()
        val bytes = jpeg
        if (bytes == null) {
            emitError(failure ?: "Photo could not be decoded")
            speak("Capture failed")
            return@withLock
        }
        val loc = withContext(Dispatchers.IO) { currentLocation() }
        val meta = JSONObject().apply {
            put("captured_at", Instant.now().toString())
            put("trigger", if (source == "button") "button" else if (source == "app") "app" else "voice")
            transcript?.let { put("transcript", it) }
            prompt?.let { put("prompt", it) }
            put("device", _status.value.deviceName)
            activeHuntId?.let { put("hunt_id", it) }
            loc?.let {
                put("lat", it.latitude); put("lng", it.longitude); put("accuracy_m", it.accuracy.toDouble())
                if (it.hasAltitude()) put("altitude_m", it.altitude)
            }
        }
        val entry = withContext(Dispatchers.IO) { Outbox.save(appContext, bytes, meta) }
        emit(mapOf("type" to "captured", "id" to entry.id, "path" to entry.path, "meta" to entry.meta))
    }

    private fun toJpeg(data: PhotoData): ByteArray? {
        val bmp: Bitmap = when (data) {
            is PhotoData.Bitmap -> data.bitmap
            is PhotoData.HEIC -> {
                val buf = data.data.duplicate()
                val bytes = ByteArray(buf.remaining()).also { buf.get(it) }
                val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
                val orientation = ExifInterface(ByteArrayInputStream(bytes))
                    .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
                rotate(decoded, orientation)
            }
            else -> return null
        }
        return ByteArrayOutputStream().use { out ->
            bmp.compress(Bitmap.CompressFormat.JPEG, 92, out)
            out.toByteArray()
        }
    }

    private fun rotate(b: Bitmap, exif: Int): Bitmap {
        val deg = when (exif) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> return b
        }
        return Bitmap.createBitmap(b, 0, 0, b.width, b.height, Matrix().apply { postRotate(deg) }, true)
    }

    @SuppressLint("MissingPermission")
    private suspend fun currentLocation(): Location? {
        val granted = ContextCompat.checkSelfPermission(appContext, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!granted) return null
        val lm = appContext.getSystemService(LocationManager::class.java) ?: return null
        val fresh = withTimeoutOrNull(4000) {
            suspendCancellableCoroutine<Location?> { cont ->
                try {
                    lm.getCurrentLocation(LocationManager.FUSED_PROVIDER, null, locationExecutor) { if (cont.isActive) cont.resume(it) }
                } catch (e: Exception) {
                    if (cont.isActive) cont.resume(null)
                }
            }
        }
        return fresh ?: listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER, LocationManager.FUSED_PROVIDER)
            .mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }
            .maxByOrNull { it.time }
    }

    // --------------------------------------------------------------------------------- feedback
    /** TTS plays on the phone's media route, which is the glasses when they are connected. */
    fun speak(text: String) {
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "scrapp-${SystemClock.elapsedRealtime()}")
    }

    fun setActiveHunt(id: String?) {
        activeHuntId = id
        update { it.copy(huntId = id) }
    }

    // ----------------------------------------------------------------------- voice invocations
    /** "Hey Meta, start Scrapp" (experimental; needs approval in the Wearables Developer Center). */
    private fun startVoiceInvocations() {
        if (closeVoiceInvocations != null) return
        try {
            val stream = Wearables.startVoiceInvocationsStream(AutoDeviceSelector())
            val job = scope.launch {
                stream.invocations.collect { inv ->
                    if (inv is LaunchApp) {
                        inv.responseHandle.sendSuccess(null)
                        onVoiceLaunch()
                    }
                }
            }
            closeVoiceInvocations = { job.cancel(); stream.close() }
        } catch (e: Exception) {
            Log.w(TAG, "Voice invocations unavailable: $e")
        }
    }

    fun onVoiceLaunch() {
        pendingVoiceLaunch = true
        emit(mapOf("type" to "voiceInvocation"))
    }

    // ------------------------------------------------------------------------- mock (testing)
    fun setMock(ctx: Context, enabled: Boolean) {
        appContext = ctx.applicationContext
        val kit = MockDeviceKit.getInstance(appContext)
        if (enabled) {
            kit.enable()
            if (mockGlasses == null) {
                mockGlasses = kit.pairGlasses(GlassesModel.RAYBAN_META).getOrNull()?.also { g ->
                    g.powerOn()
                    g.unfold()
                    g.don()
                    g.services.camera.setCameraFeed(CameraFacing.BACK) // phone camera stands in for the glasses
                }
            }
        } else {
            kit.disable()
            mockGlasses = null
        }
        initialize(appContext)
        update { it.copy(mock = enabled) }
    }

    fun simulateTranscript(text: String) {
        mockGlasses?.services?.speech?.simulateTranscription(text, true, 1f) ?: onTranscript(text, true)
    }
}
