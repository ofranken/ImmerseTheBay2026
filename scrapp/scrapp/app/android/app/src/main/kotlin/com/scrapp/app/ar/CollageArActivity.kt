package com.scrapp.app.ar

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.os.Bundle
import android.util.Log
import android.view.MotionEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.android.filament.gltfio.FilamentInstance
import com.google.ar.core.Anchor
import com.google.ar.core.Config
import com.google.ar.core.DepthPoint
import com.google.ar.core.InstantPlacementPoint
import com.google.ar.core.Session
import com.google.ar.core.Frame
import com.google.ar.core.HitResult
import com.google.ar.core.Plane
import com.google.ar.core.Point
import com.google.ar.core.Pose
import com.google.ar.core.TrackingFailureReason
import com.google.ar.core.TrackingState
import dev.romainguy.kotlin.math.Float3
import dev.romainguy.kotlin.math.Quaternion
import io.github.sceneview.ar.ARSceneView
import io.github.sceneview.math.Direction
import io.github.sceneview.math.Position
import io.github.sceneview.math.Rotation
import io.github.sceneview.math.Scale
import io.github.sceneview.rememberEngine
import io.github.sceneview.rememberMaterialLoader
import io.github.sceneview.rememberModelLoader
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

private const val TAG = "ScrappCollageAR"
private val Ink = Color(0xFF5C3A26)
private val Cream = Color(0xFFFFF0DE)
private val Teal = Color(0xFF96C1C5)
private val Sage = Color(0xFFA3B18A)

data class CollageArRequest(val title: String, val items: List<CollageLayout.Item>) {
    companion object {
        fun parse(json: String): CollageArRequest {
            val o = JSONObject(json)
            val arr = o.optJSONArray("items") ?: JSONArray()
            val items = (0 until arr.length()).mapNotNull { i ->
                val it = arr.optJSONObject(i) ?: return@mapNotNull null
                val url = it.optString("url").takeIf { u -> u.isNotBlank() && u != "null" } ?: return@mapNotNull null
                CollageLayout.Item(
                    id = it.optString("id").ifBlank { "item$i" },
                    kind = if (it.optString("kind") == "mesh") "mesh" else "sticker",
                    url = url,
                    title = it.optString("title").takeIf { t -> t.isNotBlank() && t != "null" } ?: if (it.optString("kind") == "mesh") "3D model" else "Sticker",
                    position = floats(it.optJSONArray("position"), 3, 0f),
                    quaternion = floats(it.optJSONArray("quaternion"), 4, 0f).let { q -> if (q.all { v -> v == 0f }) floatArrayOf(0f, 0f, 0f, 1f) else q },
                    scale = it.optDouble("scale", 1.0).toFloat().takeIf { s -> s.isFinite() && s > 0 } ?: 1f,
                )
            }
            return CollageArRequest(o.optString("title").ifBlank { "Collage" }, items)
        }

        private fun floats(a: JSONArray?, n: Int, fill: Float) = FloatArray(n) { i ->
            a?.optDouble(i)?.toFloat()?.takeIf { it.isFinite() } ?: fill
        }
    }
}

/** Shows a whole saved collage (stickers + 3D models) standing on a table, the floor or a wall. */
class CollageArActivity : ComponentActivity() {
    companion object {
        const val EXTRA_REQUEST = "collage_request"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val req = CollageArRequest.parse(intent.getStringExtra(EXTRA_REQUEST) ?: "{}")
        setContent {
            CollageArScreen(req) {
                setResult(Activity.RESULT_OK, Intent().putStringArrayListExtra(ScrappArActivity.EXTRA_FOUND, ArrayList()))
                finish()
            }
        }
    }
}

private fun fetchBytes(url: String): ByteArray = (URL(url).openConnection() as HttpURLConnection).run {
    connectTimeout = 10_000
    readTimeout = 45_000
    try {
        if (responseCode !in 200..299) error("HTTP $responseCode")
        inputStream.use { input -> ByteArrayOutputStream().also { input.copyTo(it) }.toByteArray() }
    } finally {
        disconnect()
    }
}

/** Decodes a sticker PNG, halving it until its long side is at most [maxSide] px (AR cards never need more). */
private fun decodeSticker(bytes: ByteArray, maxSide: Int = 1024): Bitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxSide) sample *= 2
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
}

/** Soft round contact shadow, drawn once. */
private fun shadowBitmap(): Bitmap {
    val n = 256
    val bmp = Bitmap.createBitmap(n, n, Bitmap.Config.ARGB_8888)
    val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        shader = RadialGradient(n / 2f, n / 2f, n / 2f, intArrayOf(0x66000000, 0x33000000, 0x00000000), floatArrayOf(0f, 0.55f, 1f), Shader.TileMode.CLAMP)
    }
    Canvas(bmp).drawCircle(n / 2f, n / 2f, n / 2f, p)
    return bmp
}

/** Yaw-only pose at [t] whose +Z (the collage's front) faces [toward] horizontally. */
private fun yawPose(t: FloatArray, toward: FloatArray): Pose {
    val yaw = atan2(toward[0] - t[0], toward[2] - t[2])
    return Pose(t, floatArrayOf(0f, sin(yaw / 2), 0f, cos(yaw / 2)))
}

/** Best real-surface hit for a drag: planes first (inside their outline, then anywhere on them), then feature/depth points. */
private fun Frame.bestHit(x: Float, y: Float): HitResult? {
    val hits = hitTest(x, y)
    return hits.firstOrNull { h -> (h.trackable as? Plane)?.let { it.trackingState == TrackingState.TRACKING && it.isPoseInPolygon(h.hitPose) } == true }
        ?: hits.firstOrNull { h -> (h.trackable as? Plane)?.trackingState == TrackingState.TRACKING }
        ?: hits.firstOrNull { it.trackable is Point || it.trackable is DepthPoint }
        ?: hits.firstOrNull { it.distance < 4f }
}

private fun describe(h: HitResult) = "${h.trackable.javaClass.simpleName}" +
    ((h.trackable as? Plane)?.let { "(${it.type}, ${it.trackingState}, inPolygon=${it.isPoseInPolygon(h.hitPose)})" } ?: "") +
    " d=${"%.2f".format(h.distance)}"

private fun isWall(hit: HitResult) = (hit.trackable as? Plane)?.type == Plane.Type.VERTICAL

@Composable
fun CollageArScreen(req: CollageArRequest, onDone: () -> Unit) {
    val haptics = LocalHapticFeedback.current
    val engine = rememberEngine()
    val modelLoader = rememberModelLoader(engine)
    val materialLoader = rememberMaterialLoader(engine)

    val stickers = remember { mutableStateMapOf<String, Bitmap>() }
    val models = remember { mutableStateMapOf<String, FilamentInstance>() }
    val failed = remember { mutableStateMapOf<String, String>() }
    var loadRound by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(true) }
    val shadow = remember { shadowBitmap() }

    var anchor by remember { mutableStateOf<Anchor?>(null) }
    var surface by remember { mutableStateOf(CollageLayout.Surface.FLOOR) }
    var offset by remember { mutableStateOf(Float3()) }
    var userScale by remember { mutableFloatStateOf(1f) }
    var angle by remember { mutableFloatStateOf(0f) }
    var planesSeen by remember { mutableStateOf(false) }
    var trackingProblem by remember { mutableStateOf<String?>(null) }
    val frameRef = remember { arrayOfNulls<Frame>(1) } // latest frame for hit tests; not Compose state (changes every frame)
    val sessionRef = remember { arrayOfNulls<Session>(1) }
    var tapNote by remember { mutableStateOf<String?>(null) } // short feedback so every tap visibly registers

    // -------- load every sticker and model (in parallel), keep going past failures
    LaunchedEffect(loadRound) {
        loading = true
        val todo = req.items.filter { it.id !in stickers && it.id !in models }
        val results = coroutineScope {
            todo.map { item ->
                async(Dispatchers.IO) {
                    item to runCatching { fetchBytes(item.url) }
                }
            }.awaitAll()
        }
        for ((item, r) in results) {
            val bytes = r.getOrElse { e ->
                Log.w(TAG, "download failed: ${item.title}", e)
                failed[item.id] = item.title
                null
            } ?: continue
            if (item.isMesh) {
                // Filament objects must be created on the main thread.
                runCatching {
                    val buf = ByteBuffer.allocateDirect(bytes.size).order(ByteOrder.nativeOrder()).put(bytes).also { it.rewind() }
                    modelLoader.createModelInstance(buf)
                }.onSuccess { models[item.id] = it; failed.remove(item.id) }
                    .onFailure { e -> Log.w(TAG, "bad model: ${item.title}", e); failed[item.id] = item.title }
            } else {
                val bmp = withContext(Dispatchers.Default) { runCatching { decodeSticker(bytes) }.getOrNull() }
                if (bmp != null) { stickers[item.id] = bmp; failed.remove(item.id) } else failed[item.id] = item.title
            }
        }
        loading = false
    }

    val shown = req.items.filter { it.id in stickers || it.id in models }
    val aspects = stickers.mapValues { (_, b) -> b.width.toFloat() / b.height.coerceAtLeast(1) }
    // The fit is fixed once loading settles, so the collage does not jump while items arrive.
    val fit = remember(loading, surface, shown.size) {
        if (loading) null else CollageLayout.fit(shown, aspects, surface)
    }
    // ARSceneView keeps the touch/session lambdas from its FIRST composition, so anything they read that is not itself a
    // State object must go through rememberUpdatedState (a plain `fit` captured there stayed null forever: taps did nothing).
    val currentFit by rememberUpdatedState(fit)

    // -------- gestures: tap = place, 1 finger = drag, 2 fingers = pinch + twist
    val gesture = remember { GestureState() }
    fun setAnchor(a: Anchor, wall: Boolean, note: String) {
        anchor?.detach()
        surface = if (wall) CollageLayout.Surface.WALL else CollageLayout.Surface.FLOOR
        offset = Float3()
        angle = 0f
        anchor = a
        tapNote = note
        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
        Log.i(TAG, "placed: $note at ${a.pose}")
    }

    /**
     * Forgiving placement: any plane, then a feature or depth point, then ARCore Instant Placement, and if the camera sees
     * nothing usable, 0.7 m in front of the phone. A tap always places something.
     */
    fun placeAt(x: Float, y: Float) {
        val frame = frameRef[0]
        val session = sessionRef[0]
        if (currentFit == null) { tapNote = if (loading) "Still loading, one moment…" else "Nothing to place"; Log.i(TAG, "tap ignored: fit=null loading=$loading"); return }
        if (frame == null || session == null) { tapNote = "The camera is starting…"; Log.i(TAG, "tap ignored: no frame yet"); return }
        val camera = frame.camera.pose
        val hits = runCatching { frame.hitTest(x, y) }.getOrDefault(emptyList())
        Log.i(TAG, "tap ($x, $y) tracking=${frame.camera.trackingState} hits=${hits.map { describe(it) }}")
        val hit = hits.firstOrNull { h -> (h.trackable as? Plane)?.let { it.trackingState == TrackingState.TRACKING && it.isPoseInPolygon(h.hitPose) } == true }
            ?: hits.firstOrNull { h -> (h.trackable as? Plane)?.trackingState == TrackingState.TRACKING }
            ?: hits.firstOrNull { it.trackable is Point || it.trackable is DepthPoint }
            ?: hits.firstOrNull()
        if (hit != null) {
            val t = hit.hitPose.translation
            val wall = isWall(hit)
            val pose = if (wall) {
                val n = hit.hitPose.yAxis // plane normal, horizontal on a wall
                yawPose(t, floatArrayOf(t[0] + n[0], t[1], t[2] + n[2]))
            } else yawPose(t, camera.translation)
            val a = runCatching { hit.trackable.createAnchor(pose) }.onFailure { Log.w(TAG, "anchor on trackable failed", it) }.getOrNull()
                ?: runCatching { session.createAnchor(pose) }.getOrNull()
            if (a != null) return setAnchor(a, wall, if (wall) "Placed on the wall" else "Placed")
        }
        if (frame.camera.trackingState == TrackingState.TRACKING) {
            val instant = runCatching { frame.hitTestInstantPlacement(x, y, 0.7f).firstOrNull() }.getOrNull()
            if (instant != null) {
                val t = instant.hitPose.translation
                val a = runCatching { (instant.trackable as InstantPlacementPoint).createAnchor(yawPose(t, camera.translation)) }.getOrNull()
                if (a != null) return setAnchor(a, false, "Placed (it will settle onto the surface)")
            }
            // Nothing under the finger: stand it 0.7 m ahead, a little below eye level, facing you.
            val ahead = camera.compose(Pose.makeTranslation(0f, -0.25f, -0.7f)).translation
            val a = runCatching { session.createAnchor(yawPose(ahead, camera.translation)) }.getOrNull()
            if (a != null) return setAnchor(a, false, "No surface there, so it's floating in front of you. Drag it onto a table.")
        }
        tapNote = "Can't see the room yet. Move the phone slowly and try again."
    }

    fun dragTo(x: Float, y: Float) {
        val a = anchor ?: return
        val hit = frameRef[0]?.bestHit(x, y) ?: return
        if (surface == CollageLayout.Surface.FLOOR && isWall(hit)) return // keep a table collage off the walls while dragging
        val local = a.pose.inverse().transformPoint(hit.hitPose.translation)
        offset = when (surface) {
            CollageLayout.Surface.FLOOR -> Float3(local[0], local[1].coerceIn(-0.6f, 0.6f), local[2])
            CollageLayout.Surface.WALL -> Float3(local[0], local[1], 0f) // slide along the wall
        }
    }

    val message = when {
        req.items.isEmpty() -> "This collage has nothing to show yet."
        loading -> "Loading ${stickers.size + models.size} of ${req.items.size}…"
        shown.isEmpty() -> "Couldn't load this collage. Check your connection and try again."
        trackingProblem != null && anchor == null -> trackingProblem!!
        anchor == null && !planesSeen -> "Move your phone slowly over a table, the floor or a wall…"
        anchor == null -> "Tap a surface to place your collage"
        else -> "Drag to move · pinch to resize · twist to turn"
    }

    Box(Modifier.fillMaxSize()) {
        ARSceneView(
            modifier = Modifier.fillMaxSize(),
            engine = engine,
            modelLoader = modelLoader,
            materialLoader = materialLoader,
            planeFindingMode = Config.PlaneFindingMode.HORIZONTAL_AND_VERTICAL,
            depthMode = Config.DepthMode.AUTOMATIC,
            instantPlacementMode = Config.InstantPlacementMode.LOCAL_Y_UP,
            planeRenderer = anchor == null,
            onTrackingFailureChanged = { reason ->
                trackingProblem = when (reason) {
                    null, TrackingFailureReason.NONE -> null
                    TrackingFailureReason.INSUFFICIENT_LIGHT -> "It's too dark here. Find more light."
                    TrackingFailureReason.EXCESSIVE_MOTION -> "Slow down a little."
                    TrackingFailureReason.INSUFFICIENT_FEATURES -> "Point at something with more texture."
                    TrackingFailureReason.CAMERA_UNAVAILABLE -> "The camera is busy. Close other camera apps."
                    else -> "Move your phone slowly…"
                }
            },
            onSessionUpdated = { session, frame ->
                sessionRef[0] = session
                frameRef[0] = frame
                if (!planesSeen && frame.getUpdatedTrackables(Plane::class.java).any { it.trackingState == TrackingState.TRACKING }) planesSeen = true
            },
            onTouchEvent = { e: MotionEvent, _ ->
                handleTouch(
                    e, gesture,
                    placed = anchor != null,
                    onTap = { x, y -> if (anchor == null) placeAt(x, y) else Log.i(TAG, "tap while placed (use Re-place)") },
                    onDrag = { x, y -> dragTo(x, y) },
                    onPinchTwist = { ratio, twist ->
                        userScale = CollageLayout.clampUserScale(userScale * ratio)
                        angle = CollageLayout.applyTwist(angle, twist)
                    },
                )
            },
        ) {
            val a = anchor
            val f = fit
            if (a != null && f != null) {
                key(a) { AnchorNode(anchor = a) {
                    Node(
                        position = offset,
                        rotation = if (surface == CollageLayout.Surface.FLOOR) Rotation(y = angle) else Rotation(z = angle),
                        scale = Scale(userScale),
                    ) {
                        if (surface == CollageLayout.Surface.FLOOR) {
                            val s = f.bounds.size
                            val c = f.bounds.center
                            val d = maxOf(s[0], s[2]) * f.metresPerUnit * 1.25f
                            ImageNode(
                                bitmap = shadow,
                                size = Float3(d, d, 0f),
                                normal = Direction(y = 1f),
                                position = Position((c[0] - f.pivot[0]) * f.metresPerUnit, 0.002f, (c[2] - f.pivot[2]) * f.metresPerUnit),
                            )
                        }
                        for (item in shown) key(item.id) {
                            val p = CollageLayout.placed(item, f)
                            val q = item.quaternion
                            Node(
                                position = Position(p[0], p[1], p[2]),
                                rotation = Quaternion(q[0], q[1], q[2], q[3]).toEulerAngles(),
                                scale = Scale(item.scale * f.metresPerUnit),
                            ) {
                                val bmp = stickers[item.id]
                                val model = models[item.id]
                                if (bmp != null) {
                                    val h = CollageLayout.STICKER_HEIGHT
                                    val w = h * bmp.width / bmp.height.coerceAtLeast(1)
                                    // The card material is one-sided, so draw a back face too (like the editor's DoubleSide).
                                    ImageNode(bitmap = bmp, size = Float3(w, h, 0f), normal = Direction(z = 1f))
                                    ImageNode(bitmap = bmp, size = Float3(w, h, 0f), normal = Direction(z = -1f))
                                } else if (model != null) {
                                    ModelNode(
                                        modelInstance = model,
                                        autoAnimate = true,
                                        scaleToUnits = CollageLayout.MESH_FIT,
                                        centerOrigin = Position(0f, -1f, 0f), // base on the floor, like the editor
                                    )
                                }
                            }
                        }
                    }
                } }
            }
        }

        // -------- paper overlay
        Column(Modifier.fillMaxSize().systemBarsPadding().padding(14.dp), verticalArrangement = Arrangement.SpaceBetween) {
            Column(Modifier.fillMaxWidth().background(Cream, RoundedCornerShape(20.dp)).padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text(req.title.uppercase(), color = Ink, fontWeight = FontWeight.Black, fontSize = 20.sp)
                Text(message, color = Ink, fontSize = 15.sp)
                tapNote?.let { Text(it, color = Ink, fontWeight = FontWeight.Bold, fontSize = 14.sp) }
                if (anchor != null && fit != null) {
                    val largest = fit.bounds.size.max() * fit.metresPerUnit * userScale
                    Text("About ${CollageLayout.sizeLabel(largest)} across", color = Ink.copy(alpha = 0.7f), fontSize = 13.sp)
                }
                if (failed.isNotEmpty() && !loading) {
                    Text(
                        "Couldn't load: ${failed.values.joinToString(", ")}",
                        color = Ink.copy(alpha = 0.75f), fontSize = 13.sp,
                    )
                }
            }
            Column {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (failed.isNotEmpty() && !loading) {
                        Button(
                            onClick = { loadRound++ },
                            modifier = Modifier.weight(1f).height(48.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Cream, contentColor = Ink),
                            shape = RoundedCornerShape(30.dp),
                        ) { Text("Retry", fontWeight = FontWeight.Bold) }
                    }
                    if (anchor != null) {
                        Button(
                            onClick = {
                                anchor?.detach()
                                anchor = null
                                tapNote = null
                                userScale = 1f
                                angle = 0f
                                offset = Float3()
                            },
                            modifier = Modifier.weight(1f).height(48.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Sage, contentColor = Ink),
                            shape = RoundedCornerShape(30.dp),
                        ) { Text("Re-place", fontWeight = FontWeight.Bold) }
                    }
                }
                Spacer(Modifier.height(10.dp))
                Button(
                    onClick = onDone,
                    modifier = Modifier.fillMaxWidth().height(54.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Teal, contentColor = Ink),
                    shape = RoundedCornerShape(30.dp),
                ) { Text("Done", fontWeight = FontWeight.Black, fontSize = 17.sp) }
            }
        }
    }
}

/** Raw multi-touch state; kept out of Compose state because it changes on every touch event. */
private class GestureState {
    var downX = 0f
    var downY = 0f
    var downAt = 0L
    var moved = false
    var multi = false
    var lastAx = 0f; var lastAy = 0f; var lastBx = 0f; var lastBy = 0f
}

private fun handleTouch(
    e: MotionEvent,
    g: GestureState,
    placed: Boolean,
    onTap: (Float, Float) -> Unit,
    onDrag: (Float, Float) -> Unit,
    onPinchTwist: (ratio: Float, twistDeg: Float) -> Unit,
): Boolean {
    when (e.actionMasked) {
        MotionEvent.ACTION_DOWN -> {
            g.downX = e.x; g.downY = e.y; g.downAt = e.eventTime; g.moved = false; g.multi = false
        }
        MotionEvent.ACTION_POINTER_DOWN -> if (e.pointerCount >= 2) {
            g.multi = true
            g.lastAx = e.getX(0); g.lastAy = e.getY(0); g.lastBx = e.getX(1); g.lastBy = e.getY(1)
        }
        MotionEvent.ACTION_MOVE -> {
            if (hypot(e.x - g.downX, e.y - g.downY) > 48f) g.moved = true
            if (!placed) return true
            if (e.pointerCount >= 2) {
                val ax = e.getX(0); val ay = e.getY(0); val bx = e.getX(1); val by = e.getY(1)
                val ratio = CollageLayout.spanRatio(g.lastAx, g.lastAy, g.lastBx, g.lastBy, ax, ay, bx, by)
                val twist = CollageLayout.twistDegrees(g.lastAx, g.lastAy, g.lastBx, g.lastBy, ax, ay, bx, by)
                onPinchTwist(ratio, twist)
                g.lastAx = ax; g.lastAy = ay; g.lastBx = bx; g.lastBy = by
            } else if (!g.multi && g.moved) {
                onDrag(e.x, e.y)
            }
        }
        MotionEvent.ACTION_POINTER_UP -> {
            // Keep the remaining two fingers' baseline in sync so the next move does not jump.
            if (e.pointerCount > 2) {
                val keep = (0 until e.pointerCount).filter { it != e.actionIndex }
                g.lastAx = e.getX(keep[0]); g.lastAy = e.getY(keep[0]); g.lastBx = e.getX(keep[1]); g.lastBy = e.getY(keep[1])
            }
        }
        MotionEvent.ACTION_UP -> {
            Log.d(TAG, "up moved=${g.moved} multi=${g.multi} dt=${e.eventTime - g.downAt}")
            if (!g.moved && !g.multi && e.eventTime - g.downAt < 700) onTap(e.x, e.y)
        }
    }
    return true
}
