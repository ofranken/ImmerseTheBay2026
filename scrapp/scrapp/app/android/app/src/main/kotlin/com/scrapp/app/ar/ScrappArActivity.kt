package com.scrapp.app.ar

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.PointF
import android.os.Bundle
import android.view.MotionEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.ar.core.Anchor
import com.google.ar.core.AugmentedImage
import com.google.ar.core.Config
import com.google.ar.core.Pose
import com.google.ar.core.TrackingState
import io.github.sceneview.ar.ARSceneView
import io.github.sceneview.ar.arcore.AddImageResult
import io.github.sceneview.ar.arcore.rememberRuntimeAugmentedImageDatabase
import io.github.sceneview.math.Direction
import io.github.sceneview.math.Position
import io.github.sceneview.math.Rotation
import io.github.sceneview.math.Scale
import io.github.sceneview.rememberEngine
import io.github.sceneview.rememberMaterialLoader
import io.github.sceneview.rememberModelLoader
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

private val Ink = Color(0xFF5C3A26)
private val Cream = Color(0xFFFFF0DE)
private val Teal = Color(0xFF96C1C5)
private val Sage = Color(0xFFA3B18A)

data class ArAnchorSpec(val mode: String, val objectClass: String?, val animation: String, val sizeM: Float, val lat: Double?, val lng: Double?)
data class ArItemSpec(val id: String, val imageUrl: String, val title: String, val targetUrl: String?, val anchor: ArAnchorSpec)
data class ArRequest(val title: String, val instructions: String?, val items: List<ArItemSpec>) {
    companion object {
        fun parse(json: String): ArRequest {
            val o = JSONObject(json)
            val arr = o.optJSONArray("items")
            val items = (0 until (arr?.length() ?: 0)).map { i ->
                val it = arr!!.getJSONObject(i)
                val a = it.optJSONObject("anchor") ?: JSONObject()
                ArItemSpec(
                    id = it.getString("id"),
                    imageUrl = it.getString("imageUrl"),
                    title = it.optString("title", "Sticker").ifBlank { "Sticker" },
                    targetUrl = it.optString("targetUrl").takeIf { s -> s.isNotBlank() && s != "null" },
                    anchor = ArAnchorSpec(
                        mode = a.optString("mode", "surface"),
                        objectClass = a.optString("object_class").takeIf { s -> s.isNotBlank() && s != "null" },
                        animation = a.optString("animation", "wiggle"),
                        sizeM = a.optDouble("size_m", 0.12).toFloat(),
                        lat = a.optDouble("lat").takeIf { d -> !d.isNaN() },
                        lng = a.optDouble("lng").takeIf { d -> !d.isNaN() },
                    ),
                )
            }
            return ArRequest(o.optString("title", "Scrapp"), o.optString("instructions").takeIf { it.isNotBlank() && it != "null" }, items)
        }
    }
}

/**
 * Native AR (ARCore via SceneView). Three ways a sticker attaches to the world:
 *  - image: the exact artwork/object, tracked from a crop of the creator's ORIGINAL photo
 *  - object: any instance of a class ("apple") found by MediaPipe, then hit-tested onto it
 *  - geo / surface: ARCore Earth anchor outdoors, or tap-to-place on any surface
 */
class ScrappArActivity : ComponentActivity() {
    companion object {
        const val EXTRA_REQUEST = "request"
        const val EXTRA_FOUND = "found"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val req = ArRequest.parse(intent.getStringExtra(EXTRA_REQUEST) ?: "{}")
        setContent {
            ScrappArScreen(req) { found ->
                setResult(Activity.RESULT_OK, Intent().putStringArrayListExtra(EXTRA_FOUND, ArrayList(found)))
                finish()
            }
        }
    }
}

private fun download(url: String): Bitmap? = runCatching {
    (URL(url).openConnection() as HttpURLConnection).run {
        connectTimeout = 10_000
        readTimeout = 20_000
        inputStream.use { BitmapFactory.decodeStream(it) }
    }
}.getOrNull()

/** Yaw-only pose at [hit] whose +Z faces the camera, so stickers stand upright and face you. */
private fun facingPose(hit: Pose, camera: Pose): Pose {
    val t = hit.translation
    val c = camera.translation
    val yaw = atan2(c[0] - t[0], c[2] - t[2])
    return Pose(t, floatArrayOf(0f, sin(yaw / 2), 0f, cos(yaw / 2)))
}

private fun dist(a: Pose, b: Pose): Float {
    val dx = a.tx() - b.tx(); val dy = a.ty() - b.ty(); val dz = a.tz() - b.tz()
    return sqrt(dx * dx + dy * dy + dz * dz)
}

private fun metersBetween(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
    val out = FloatArray(1)
    android.location.Location.distanceBetween(lat1, lng1, lat2, lng2, out)
    return out[0].toDouble()
}

/** Elastic "pop" for the first half-second after a sticker appears. */
private fun pop(elapsedMs: Long): Float {
    val t = (elapsedMs / 550.0).coerceIn(0.0, 1.0)
    if (t >= 1.0) return 1f
    return (1 + 2.0.pow(-10 * t) * sin((t * 10 - 0.75) * (2 * PI / 3))).toFloat()
}

@Composable
fun ScrappArScreen(req: ArRequest, onDone: (List<String>) -> Unit) {
    val context = LocalContext.current
    val haptics = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()
    val engine = rememberEngine()
    val modelLoader = rememberModelLoader(engine)
    val materialLoader = rememberMaterialLoader(engine)
    val imageDb = rememberRuntimeAugmentedImageDatabase()

    val stickers = remember { mutableStateMapOf<String, Bitmap>() }
    val anchors = remember { mutableStateMapOf<String, Anchor>() }
    val tracked = remember { mutableStateMapOf<String, AugmentedImage>() }
    val appearedAt = remember { mutableStateMapOf<String, Long>() }
    val found = remember { mutableStateListOf<String>() }
    val pendingHits = remember { mutableStateMapOf<String, PointF>() }
    var message by remember { mutableStateOf(req.instructions ?: "Look around") }
    var viewSize by remember { mutableStateOf(IntSize.Zero) }
    var frameMs by remember { mutableLongStateOf(0L) }
    var lastDetectAt by remember { mutableLongStateOf(0L) }
    val detecting = remember { AtomicBoolean(false) }

    val objectItems = remember(req) { req.items.filter { it.anchor.mode == "object" && it.anchor.objectClass != null } }
    val geoItems = remember(req) { req.items.filter { it.anchor.mode == "geo" && it.anchor.lat != null && it.anchor.lng != null } }
    val finder = remember { if (objectItems.isNotEmpty()) runCatching { ObjectFinder(context) }.getOrNull() else null }
    DisposableEffect(Unit) { onDispose { finder?.close() } }

    val infinite = rememberInfiniteTransition(label = "sticker")
    val phase by infinite.animateFloat(0f, (2 * PI).toFloat(), infiniteRepeatable(tween(1600, easing = LinearEasing)), label = "phase")
    val spin by infinite.animateFloat(0f, 360f, infiniteRepeatable(tween(4000, easing = LinearEasing)), label = "spin")

    LaunchedEffect(Unit) { while (true) withFrameMillis { frameMs = it } }

    fun markFound(id: String, text: String) {
        appearedAt[id] = frameMs
        if (id !in found) {
            found += id
            message = text
            haptics.performHapticFeedback(HapticFeedbackType.LongPress)
        }
    }

    LaunchedEffect(req) {
        for (item in req.items) {
            val bmp = withContext(Dispatchers.IO) { download(item.imageUrl) } ?: continue
            stickers[item.id] = bmp
            val targetUrl = item.targetUrl
            if (item.anchor.mode == "image" && targetUrl != null) {
                val target = withContext(Dispatchers.IO) { download(targetUrl) } ?: continue
                when (imageDb.addImage(item.id, target.copy(Bitmap.Config.ARGB_8888, false))) {
                    is AddImageResult.LowQuality -> message = "\"${item.title}\" has little detail to track. Try getting closer."
                    is AddImageResult.Error -> message = "Could not prepare \"${item.title}\" for tracking."
                    else -> Unit
                }
            }
        }
        if (objectItems.isNotEmpty() && finder == null) message = "Object finder unavailable. Tap a surface to place it."
    }

    var lastFrame by remember { mutableStateOf<com.google.ar.core.Frame?>(null) }
    Box(Modifier.fillMaxSize().onSizeChanged { viewSize = it }) {
        ARSceneView(
            modifier = Modifier.fillMaxSize(),
            engine = engine,
            modelLoader = modelLoader,
            materialLoader = materialLoader,
            depthMode = Config.DepthMode.AUTOMATIC, // depth hits let stickers land on round things like apples
            instantPlacementMode = Config.InstantPlacementMode.LOCAL_Y_UP,
            geospatialMode = if (geoItems.isNotEmpty()) Config.GeospatialMode.ENABLED else Config.GeospatialMode.DISABLED,
            sessionConfiguration = { session, config -> imageDb.applyTo(config, session) },
            onSessionCreated = { session -> imageDb.bind(session) },
            onSessionUpdated = { session, frame ->
                lastFrame = frame
                // 1) Exact objects / artworks (hunt finds, "on the exact thing" shares)
                for (img in frame.getUpdatedTrackables(AugmentedImage::class.java)) {
                    if (img.trackingState == TrackingState.TRACKING &&
                        img.trackingMethod == AugmentedImage.TrackingMethod.FULL_TRACKING &&
                        tracked[img.name] == null
                    ) {
                        tracked[img.name] = img
                        val title = req.items.firstOrNull { it.id == img.name }?.title ?: "it"
                        markFound(img.name, "Found $title!")
                    }
                }

                // 2) Object classes: detect off the main thread every ~0.6 s; keeps following a moved object
                val now = System.currentTimeMillis()
                if (finder != null && objectItems.isNotEmpty() && viewSize.width > 0 && !detecting.get() && now - lastDetectAt > 600) {
                    lastDetectAt = now
                    val image = runCatching { frame.acquireCameraImage() }.getOrNull()
                    if (image != null) {
                        val aligned = try {
                            ObjectFinder.viewAlignedBitmap(frame, image, 480, viewSize.width.toFloat() / viewSize.height)
                        } finally {
                            image.close()
                        }
                        if (aligned != null) {
                            detecting.set(true)
                            scope.launch {
                                val hits = withContext(Dispatchers.Default) {
                                    objectItems.mapNotNull { item -> finder.find(aligned, item.anchor.objectClass!!)?.let { item.id to it } }
                                }
                                hits.forEach { (id, p) -> pendingHits[id] = p }
                                if (hits.isEmpty() && found.isEmpty()) message = "Hold up ${objectItems.first().anchor.objectClass} in view…"
                                detecting.set(false)
                            }
                        }
                    }
                }
                for ((id, p) in pendingHits.toMap()) {
                    pendingHits.remove(id)
                    val x = p.x * viewSize.width
                    val y = p.y * viewSize.height
                    val hit = frame.hitTest(x, y).firstOrNull { it.distance < 3f }
                        ?: frame.hitTestInstantPlacement(x, y, 0.4f).firstOrNull()
                        ?: continue
                    val pose = facingPose(hit.hitPose, frame.camera.pose)
                    val old = anchors[id]
                    if (old == null || dist(old.pose, pose) > 0.06f) {
                        old?.detach()
                        anchors[id] = session.createAnchor(pose)
                        if (old == null) markFound(id, "There it is!")
                    }
                }

                // 3) Geo anchors (outdoors, ARCore Earth / VPS)
                if (geoItems.any { it.id !in anchors }) {
                    val earth = session.earth
                    if (earth != null && earth.trackingState == TrackingState.TRACKING) {
                        val here = earth.cameraGeospatialPose
                        for (item in geoItems) {
                            if (item.id in anchors) continue
                            val d = metersBetween(here.latitude, here.longitude, item.anchor.lat!!, item.anchor.lng!!)
                            if (d < 150) {
                                anchors[item.id] = earth.createAnchor(item.anchor.lat!!, item.anchor.lng!!, here.altitude - 0.3, 0f, 0f, 0f, 1f)
                                markFound(item.id, "${item.title} is here!")
                            } else {
                                message = "${item.title} is ${d.toInt()} m away"
                            }
                        }
                    }
                }
            },
            onTouchEvent = { e: MotionEvent, hit ->
                val arHit = if (e.action == MotionEvent.ACTION_UP) lastFrame?.hitTest(e.x, e.y)?.firstOrNull() else null
                if (arHit != null) {
                    val next = req.items.firstOrNull { it.id !in anchors && it.id !in tracked && it.anchor.mode != "image" }
                    if (next != null) {
                        anchors[next.id] = arHit.createAnchor()
                        markFound(next.id, "Placed ${next.title}")
                        true
                    } else false
                } else false
            },
        ) {
            for (item in req.items) {
                // No `continue` here: keep control flow simple inside composable content.
                val bmp = stickers[item.id]
                val elapsed = frameMs - (appearedAt[item.id] ?: frameMs)
                val p = pop(elapsed)
                val wiggle = if (item.anchor.animation == "wiggle") sin(phase) * 12f else 0f
                val bob = if (item.anchor.animation == "bob") sin(phase) * 0.02f else 0f
                val turn = if (item.anchor.animation == "spin") spin else 0f
                val pulse = if (item.anchor.animation == "pop") 1f + 0.06f * sin(phase) else 1f
                if (bmp != null) key(item.id) {
                    anchors[item.id]?.let { a ->
                        AnchorNode(anchor = a) {
                            // Standing sticker facing the viewer (anchor +Z faces the camera).
                            val lift = if (item.anchor.mode == "object") 0f else item.anchor.sizeM * 0.5f
                            ImageNode(
                                bitmap = bmp,
                                normal = Direction(z = 1f),
                                position = Position(y = lift + bob, z = if (item.anchor.mode == "object") 0.015f else 0f),
                                rotation = Rotation(y = turn, z = wiggle),
                                scale = Scale(item.anchor.sizeM * p * pulse),
                            )
                        }
                    }
                    tracked[item.id]?.let { img ->
                        AugmentedImageNode(augmentedImage = img) {
                            // Lies flat on the artwork (default plane normal is the image normal, +Y).
                            val size = min(img.extentX, img.extentZ).coerceAtLeast(0.08f) * 0.6f
                            ImageNode(
                                bitmap = bmp,
                                position = Position(y = 0.004f + bob * 0.3f),
                                rotation = Rotation(y = wiggle + turn),
                                scale = Scale(size * p * pulse),
                            )
                        }
                    }
                }
            }
        }

        // Paper overlay
        Column(Modifier.fillMaxSize().systemBarsPadding().padding(14.dp), verticalArrangement = Arrangement.SpaceBetween) {
            Column(
                Modifier.fillMaxWidth().background(Cream, RoundedCornerShape(20.dp)).padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                Text(req.title.uppercase(), color = Ink, fontWeight = FontWeight.Black, fontSize = 20.sp)
                Text(message, color = Ink, fontSize = 15.sp)
            }
            Column {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (item in req.items) {
                        val done = item.id in found
                        Text(
                            (if (done) "✓ " else "○ ") + item.title,
                            color = Ink,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.background(if (done) Sage else Cream, RoundedCornerShape(30.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))
                Button(
                    onClick = { onDone(found.toList()) },
                    modifier = Modifier.fillMaxWidth().height(54.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Teal, contentColor = Ink),
                    shape = RoundedCornerShape(30.dp),
                ) { Text("Done", fontWeight = FontWeight.Black, fontSize = 17.sp) }
            }
        }
        if (stickers.isEmpty()) Box(Modifier.align(Alignment.Center)) { Text("Loading stickers…", color = Ink) }
    }
}
