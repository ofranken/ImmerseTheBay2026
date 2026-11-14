package com.scrapp.app.glasses

import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.scrapp.app.MainActivity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** Method + event channels between Flutter (lib/services/glasses_bridge.dart) and [GlassesManager]. */
class GlassesChannel(private val activity: MainActivity, messenger: BinaryMessenger) : MethodChannel.MethodCallHandler {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var eventJob: Job? = null

    init {
        MethodChannel(messenger, "scrapp/glasses").setMethodCallHandler(this)
        EventChannel(messenger, "scrapp/glasses/events").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, sink: EventChannel.EventSink) {
                eventJob = scope.launch {
                    sink.success(GlassesManager.status.value.toMap())
                    GlassesManager.events.collect { sink.success(it) }
                }
            }

            override fun onCancel(arguments: Any?) {
                eventJob?.cancel()
            }
        })
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        scope.launch {
            try {
                when (call.method) {
                    "initialize" -> {
                        if (!GlassesManager.initialized && !activity.requestAndroidPermissions()) {
                            result.error("permission", "Bluetooth permission is required to talk to the glasses", null)
                            return@launch
                        }
                        GlassesManager.initialize(activity)
                        result.success(GlassesManager.status.value.toMap())
                    }
                    "status" -> result.success(GlassesManager.status.value.toMap())
                    "register" -> { GlassesManager.register(activity); result.success(null) }
                    "unregister" -> { GlassesManager.unregister(activity); result.success(null) }
                    "requestPermission" -> {
                        val p = if (call.argument<String>("permission") == "microphone") Permission.MICROPHONE else Permission.CAMERA
                        val status = activity.requestDatPermission(p)
                        result.success(if (status == PermissionStatus.Granted) "granted" else "denied")
                    }
                    "arm" -> {
                        GlassesManager.arm(
                            GlassesManager.ArmConfig(
                                warmCamera = call.argument<Boolean>("warmCamera") ?: true,
                                voice = call.argument<Boolean>("voice") ?: true,
                                button = call.argument<Boolean>("button") ?: true,
                            ),
                        )
                        result.success(null)
                    }
                    "disarm" -> { GlassesManager.disarm(); result.success(null) }
                    "captureNow" -> { GlassesManager.trigger(call.argument<String>("trigger") ?: "app"); result.success(null) }
                    "setHunt" -> { GlassesManager.setActiveHunt(call.argument<String>("huntId")); result.success(null) }
                    "speak" -> { GlassesManager.speak(call.argument<String>("text") ?: ""); result.success(null) }
                    "pendingCaptures" -> result.success(
                        Outbox.list(activity).map { mapOf("id" to it.id, "path" to it.path, "meta" to it.meta) },
                    )
                    "ackCapture" -> { Outbox.ack(activity, call.argument<String>("id")!!); result.success(null) }
                    "enableMock" -> { GlassesManager.setMock(activity, call.argument<Boolean>("enabled") ?: false); result.success(null) }
                    "simulateTranscript" -> { GlassesManager.simulateTranscript(call.argument<String>("text") ?: ""); result.success(null) }
                    "consumeLaunchIntent" -> {
                        val v = GlassesManager.pendingVoiceLaunch
                        GlassesManager.pendingVoiceLaunch = false
                        result.success(v)
                    }
                    else -> result.notImplemented()
                }
            } catch (e: Exception) {
                result.error("glasses", e.message, null)
            }
        }
    }
}
