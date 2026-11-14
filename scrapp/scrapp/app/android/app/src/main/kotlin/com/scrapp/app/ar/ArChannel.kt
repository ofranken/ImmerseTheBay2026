package com.scrapp.app.ar

import android.app.Activity
import android.content.Intent
import com.google.ar.core.ArCoreApk
import com.scrapp.app.MainActivity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject

/** Flutter -> native AR. Opens [ScrappArActivity] and returns the ids found/anchored. */
class ArChannel(private val activity: MainActivity, messenger: BinaryMessenger) {
    private var pending: MethodChannel.Result? = null

    init {
        MethodChannel(messenger, "scrapp/ar").setMethodCallHandler { call, result ->
            when (call.method) {
                "available" -> result.success(ArCoreApk.getInstance().checkAvailability(activity).isSupported)
                "open" -> {
                    pending?.success(emptyList<String>())
                    pending = result
                    val req = JSONObject(call.arguments as Map<*, *>).toString()
                    activity.arLauncher.launch(Intent(activity, ScrappArActivity::class.java).putExtra(ScrappArActivity.EXTRA_REQUEST, req))
                }
                else -> result.notImplemented()
            }
        }
    }

    fun onActivityResult(code: Int, data: Intent?) {
        val found = if (code == Activity.RESULT_OK) data?.getStringArrayListExtra(ScrappArActivity.EXTRA_FOUND).orEmpty() else emptyList()
        pending?.success(found)
        pending = null
    }
}
