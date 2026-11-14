package com.scrapp.app

import android.Manifest
import android.content.Intent
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.meta.wearable.dat.core.voiceinvocations.isVoiceInvocationsIntent
import com.scrapp.app.ar.ArChannel
import com.scrapp.app.glasses.GlassesChannel
import com.scrapp.app.glasses.GlassesManager
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import kotlin.coroutines.Continuation
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * FlutterFragmentActivity (a ComponentActivity) because Meta's permission contract and the
 * AR activity-result launcher both use the Activity Result API.
 */
class MainActivity : FlutterFragmentActivity() {

    private var arChannel: ArChannel? = null

    // Android runtime permissions needed before Wearables.initialize()
    private var androidPermsCont: Continuation<Boolean>? = null
    private val androidPermsLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
            androidPermsCont?.resume(result[Manifest.permission.BLUETOOTH_CONNECT] == true)
            androidPermsCont = null
        }

    // Glasses permissions are granted in the Meta AI app
    private val datMutex = Mutex()
    private var datCont: Continuation<PermissionStatus>? = null
    private val datPermissionLauncher =
        registerForActivityResult(Wearables.RequestPermissionContract()) { result ->
            datCont?.resume(result.getOrDefault(PermissionStatus.Denied))
            datCont = null
        }

    val arLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        arChannel?.onActivityResult(r.resultCode, r.data)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        GlassesChannel(this, messenger)
        arChannel = ArChannel(this, messenger)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // "Hey Meta, start Scrapp" cold launch
        if (savedInstanceState == null && isVoiceInvocationsIntent(intent)) GlassesManager.pendingVoiceLaunch = true
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (isVoiceInvocationsIntent(intent)) GlassesManager.onVoiceLaunch()
    }

    suspend fun requestAndroidPermissions(): Boolean = suspendCancellableCoroutine { cont ->
        androidPermsCont = cont
        androidPermsLauncher.launch(
            arrayOf(
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.POST_NOTIFICATIONS,
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.CAMERA,
            ),
        )
    }

    suspend fun requestDatPermission(permission: Permission): PermissionStatus = datMutex.withLock {
        suspendCancellableCoroutine { cont ->
            datCont = cont
            datPermissionLauncher.launch(permission)
        }
    }
}
