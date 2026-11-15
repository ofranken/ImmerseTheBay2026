package com.scrapp.app.ar

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

/**
 * Pure maths for showing a whole collage in AR (no Android or ARCore types, so it is unit-tested on the JVM).
 *
 * Collage scenes come from the three.js editor (assets/web/editor.js), in editor units, Y up, right-handed:
 *  - sticker: a plane STICKER_HEIGHT tall (width = height * image aspect) centred on `position`, facing +Z before rotation
 *  - mesh: a GLB normalised so its largest side is MESH_FIT, centred in X/Z and standing on `position` (base at y = 0)
 * Both then get `quaternion` [x, y, z, w] and a uniform `scale`. ARCore/Filament use the same axes, so no conversion is needed.
 */
object CollageLayout {
    const val STICKER_HEIGHT = 0.45f
    const val MESH_FIT = 0.5f

    /** Largest side of the placed collage, in metres, before the user pinches. Fits on a table, reads well across a room. */
    const val DEFAULT_SIZE_M = 0.5f
    const val MIN_USER_SCALE = 0.2f
    const val MAX_USER_SCALE = 6f

    data class Item(
        val id: String,
        val kind: String, // "sticker" | "mesh"
        val url: String,
        val title: String,
        val position: FloatArray, // [x, y, z]
        val quaternion: FloatArray, // [x, y, z, w]
        val scale: Float,
    ) {
        val isMesh get() = kind == "mesh"
    }

    data class Box(val min: FloatArray, val max: FloatArray) {
        val size get() = FloatArray(3) { max[it] - min[it] }
        val center get() = FloatArray(3) { (min[it] + max[it]) / 2 }
        fun union(o: Box) = Box(FloatArray(3) { min(min[it], o.min[it]) }, FloatArray(3) { max(max[it], o.max[it]) })
    }

    enum class Surface { FLOOR, WALL }

    /**
     * Where the collage's own coordinates meet the anchor, and how big one editor unit is in metres.
     * Items are drawn at (position - pivot) * metresPerUnit under the anchor.
     */
    data class Fit(val pivot: FloatArray, val metresPerUnit: Float, val bounds: Box)

    /** Rotates v by unit quaternion q = [x, y, z, w]. */
    fun rotate(q: FloatArray, v: FloatArray): FloatArray {
        val (qx, qy, qz, qw) = normalized(q)
        // t = 2 * cross(q.xyz, v); v' = v + w * t + cross(q.xyz, t)
        val tx = 2 * (qy * v[2] - qz * v[1])
        val ty = 2 * (qz * v[0] - qx * v[2])
        val tz = 2 * (qx * v[1] - qy * v[0])
        return floatArrayOf(
            v[0] + qw * tx + (qy * tz - qz * ty),
            v[1] + qw * ty + (qz * tx - qx * tz),
            v[2] + qw * tz + (qx * ty - qy * tx),
        )
    }

    private fun normalized(q: FloatArray): FloatArray {
        if (q.size != 4) return floatArrayOf(0f, 0f, 0f, 1f)
        val n = kotlin.math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
        return if (n < 1e-6f || n.isNaN()) floatArrayOf(0f, 0f, 0f, 1f) else floatArrayOf(q[0] / n, q[1] / n, q[2] / n, q[3] / n)
    }

    /** Local (unrotated, unscaled) box of an item, matching how the editor builds it. */
    fun localBox(item: Item, aspect: Float?): Box = if (item.isMesh) {
        val h = MESH_FIT / 2
        Box(floatArrayOf(-h, 0f, -h), floatArrayOf(h, MESH_FIT, h)) // true model is inside this cube
    } else {
        val a = (aspect ?: 1f).takeIf { it.isFinite() && it > 0 } ?: 1f
        val hw = STICKER_HEIGHT * a / 2
        val hh = STICKER_HEIGHT / 2
        Box(floatArrayOf(-hw, -hh, 0f), floatArrayOf(hw, hh, 0f))
    }

    /** Axis-aligned box of an item in collage space (all 8 corners rotated, scaled, moved). */
    fun worldBox(item: Item, aspect: Float?): Box {
        val b = localBox(item, aspect)
        val s = item.scale.takeIf { it.isFinite() && it > 0 } ?: 1f
        var out: Box? = null
        for (i in 0 until 8) {
            val c = floatArrayOf(
                if (i and 1 == 0) b.min[0] else b.max[0],
                if (i and 2 == 0) b.min[1] else b.max[1],
                if (i and 4 == 0) b.min[2] else b.max[2],
            )
            val r = rotate(item.quaternion, floatArrayOf(c[0] * s, c[1] * s, c[2] * s))
            val p = FloatArray(3) { r[it] + item.position[it] }
            val pb = Box(p, p.copyOf())
            out = out?.union(pb) ?: pb
        }
        return out!!
    }

    fun bounds(items: List<Item>, aspects: Map<String, Float>): Box? =
        items.map { worldBox(it, aspects[it.id]) }.reduceOrNull { a, b -> a.union(b) }

    /**
     * Scale so the largest side is [targetM] metres, and pick the pivot: on a floor/table the collage stands on its lowest
     * point, centred in X/Z; on a wall its back touches the wall, centred in X/Y.
     */
    fun fit(items: List<Item>, aspects: Map<String, Float>, surface: Surface, targetM: Float = DEFAULT_SIZE_M): Fit? {
        val b = bounds(items, aspects) ?: return null
        val largest = b.size.max().coerceAtLeast(0.05f)
        val c = b.center
        val pivot = when (surface) {
            Surface.FLOOR -> floatArrayOf(c[0], b.min[1], c[2])
            Surface.WALL -> floatArrayOf(c[0], c[1], b.min[2])
        }
        return Fit(pivot, targetM / largest, b)
    }

    /** Item position under the anchor, in metres before the user's own scale. */
    fun placed(item: Item, fit: Fit): FloatArray = FloatArray(3) { (item.position[it] - fit.pivot[it]) * fit.metresPerUnit }

    /**
     * Back-to-front order for the transparent sticker cards, so overlapping stickers blend correctly. [cameraLocal] is the
     * camera position in the same space as [placed] positions.
     */
    fun drawOrder(placed: Map<String, FloatArray>, cameraLocal: FloatArray): List<String> =
        placed.entries.sortedByDescending { (_, p) -> dist2(p, cameraLocal) }.map { it.key }

    private fun dist2(a: FloatArray, b: FloatArray): Float {
        val dx = a[0] - b[0]; val dy = a[1] - b[1]; val dz = a[2] - b[2]
        return dx * dx + dy * dy + dz * dz
    }

    // ------------------------------------------------------------------------------------------------ gestures

    /** Signed change in the angle of the line between two fingers, in degrees, wrapped to (-180, 180]. */
    fun twistDegrees(ax0: Float, ay0: Float, bx0: Float, by0: Float, ax1: Float, ay1: Float, bx1: Float, by1: Float): Float {
        val a0 = atan2(by0 - ay0, bx0 - ax0)
        val a1 = atan2(by1 - ay1, bx1 - ax1)
        var d = ((a1 - a0) * 180 / PI).toFloat()
        while (d > 180f) d -= 360f
        while (d <= -180f) d += 360f
        return d
    }

    /** Ratio of finger spread now vs before (pinch). 1 when either spread is too small to trust. */
    fun spanRatio(ax0: Float, ay0: Float, bx0: Float, by0: Float, ax1: Float, ay1: Float, bx1: Float, by1: Float): Float {
        val s0 = hypot(bx0 - ax0, by0 - ay0)
        val s1 = hypot(bx1 - ax1, by1 - ay1)
        if (s0 < 8f || s1 < 8f) return 1f
        return s1 / s0
    }

    fun clampUserScale(s: Float) = s.coerceIn(MIN_USER_SCALE, MAX_USER_SCALE)

    /**
     * Screen y points down, so a positive [twistDeg] is a clockwise twist on screen. Seen from above a table (or from in
     * front of a wall) clockwise is a negative right-handed turn about the up axis (or the wall normal), so subtract.
     */
    fun applyTwist(angleDeg: Float, twistDeg: Float): Float {
        val next = angleDeg - twistDeg
        return ((next % 360f) + 360f) % 360f
    }

    /** Nice text for "how big is it", e.g. 48 cm or 1.2 m. */
    fun sizeLabel(metres: Float): String =
        if (abs(metres) < 1f) "${(metres * 100).toInt()} cm" else "${"%.1f".format(metres)} m"
}
