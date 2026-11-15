package com.scrapp.app.ar

import dev.romainguy.kotlin.math.Float3
import dev.romainguy.kotlin.math.Quaternion
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class CollageLayoutTest {
    private val eps = 1e-4f
    private val identity = floatArrayOf(0f, 0f, 0f, 1f)

    private fun sticker(id: String, x: Float, y: Float, z: Float, scale: Float = 1f, q: FloatArray = identity) =
        CollageLayout.Item(id, "sticker", "http://x/$id.png", id, floatArrayOf(x, y, z), q, scale)

    private fun mesh(id: String, x: Float, y: Float, z: Float, scale: Float = 1f, q: FloatArray = identity) =
        CollageLayout.Item(id, "mesh", "http://x/$id.glb", id, floatArrayOf(x, y, z), q, scale)

    private fun yaw(deg: Float): FloatArray {
        val h = (deg * PI / 180 / 2).toFloat()
        return floatArrayOf(0f, sin(h), 0f, cos(h))
    }

    @Test fun rotateByYaw90TurnsXIntoMinusZ() {
        assertArrayEquals(floatArrayOf(0f, 0f, -1f), CollageLayout.rotate(yaw(90f), floatArrayOf(1f, 0f, 0f)), eps)
    }

    @Test fun rotateToleratesUnnormalisedAndBrokenQuaternions() {
        assertArrayEquals(floatArrayOf(0f, 0f, -1f), CollageLayout.rotate(yaw(90f).map { it * 3 }.toFloatArray(), floatArrayOf(1f, 0f, 0f)), eps)
        assertArrayEquals(floatArrayOf(1f, 2f, 3f), CollageLayout.rotate(floatArrayOf(0f, 0f, 0f, 0f), floatArrayOf(1f, 2f, 3f)), eps)
    }

    @Test fun stickerBoxUsesEditorHeightAndAspect() {
        val b = CollageLayout.worldBox(sticker("a", 0f, 1f, 0f), aspect = 2f)
        assertArrayEquals(floatArrayOf(-0.45f, 1f - 0.225f, 0f), b.min, eps)
        assertArrayEquals(floatArrayOf(0.45f, 1f + 0.225f, 0f), b.max, eps)
    }

    @Test fun turnedStickerBecomesDeepInsteadOfWide() {
        val b = CollageLayout.worldBox(sticker("a", 0f, 0f, 0f, q = yaw(90f)), aspect = 2f)
        assertEquals(0f, b.size[0], eps)
        assertEquals(0.9f, b.size[2], eps)
    }

    @Test fun meshStandsOnItsPositionAndScales() {
        val b = CollageLayout.worldBox(mesh("m", 1f, 0.2f, 0f, scale = 2f), aspect = null)
        assertEquals(0.2f, b.min[1], eps) // base on the position
        assertEquals(1.2f, b.max[1], eps) // 0.5 * 2 tall
        assertEquals(1f, b.size[0], eps)
    }

    @Test fun floorFitStandsOnLowestPointAndMakesLargestSideTarget() {
        val items = listOf(sticker("a", -0.5f, 0.6f, 0f), mesh("m", 0.5f, 0.1f, 0.2f))
        val fit = CollageLayout.fit(items, mapOf("a" to 1f), CollageLayout.Surface.FLOOR, targetM = 0.5f)!!
        val b = fit.bounds
        assertEquals(b.min[1], fit.pivot[1], eps)
        assertEquals((b.min[0] + b.max[0]) / 2, fit.pivot[0], eps)
        assertEquals(0.5f, b.size.max() * fit.metresPerUnit, eps)
        // Lowest point lands on the surface, nothing goes below it.
        for (it in items) {
            val wb = CollageLayout.worldBox(it, if (it.isMesh) null else 1f)
            assertEquals(true, (wb.min[1] - fit.pivot[1]) * fit.metresPerUnit >= -eps)
        }
    }

    @Test fun wallFitPutsTheBackOnTheWall() {
        val items = listOf(sticker("a", 0f, 0f, -0.3f), mesh("m", 0f, 0f, 0.4f))
        val fit = CollageLayout.fit(items, emptyMap(), CollageLayout.Surface.WALL)!!
        assertEquals(fit.bounds.min[2], fit.pivot[2], eps)
        assertEquals(0f, CollageLayout.placed(items[0], fit)[2], eps) // the rear sticker touches the wall
    }

    @Test fun placedIsRelativeToPivotInMetres() {
        val items = listOf(sticker("a", 0f, 0.225f, 0f), sticker("b", 0.9f, 0.225f, 0f))
        val fit = CollageLayout.fit(items, mapOf("a" to 1f, "b" to 1f), CollageLayout.Surface.FLOOR, targetM = 1.35f)!!
        // bounds x: -0.225..1.125 = 1.35 units -> 1 m per unit
        assertEquals(1f, fit.metresPerUnit, eps)
        assertArrayEquals(floatArrayOf(-0.45f, 0.225f, 0f), CollageLayout.placed(items[0], fit), eps)
    }

    @Test fun tinyCollagesDoNotExplode() {
        val fit = CollageLayout.fit(listOf(sticker("a", 0f, 0f, 0f, scale = 0.001f)), emptyMap(), CollageLayout.Surface.FLOOR)!!
        assertEquals(CollageLayout.DEFAULT_SIZE_M / 0.05f, fit.metresPerUnit, eps)
    }

    @Test fun emptyCollageHasNoFit() {
        assertNull(CollageLayout.fit(emptyList(), emptyMap(), CollageLayout.Surface.FLOOR))
        assertNotNull(CollageLayout.bounds(listOf(mesh("m", 0f, 0f, 0f)), emptyMap()))
    }

    @Test fun twistIsSignedAndWrapped() {
        // Second finger goes from right of the first to below it: clockwise on a y-down screen.
        assertEquals(90f, CollageLayout.twistDegrees(0f, 0f, 100f, 0f, 0f, 0f, 0f, 100f), eps)
        assertEquals(-90f, CollageLayout.twistDegrees(0f, 0f, 100f, 0f, 0f, 0f, 0f, -100f), eps)
        // Crossing the +-180 seam stays small.
        assertEquals(-20.5f, CollageLayout.twistDegrees(0f, 0f, -100f, -18f, 0f, 0f, -100f, 18.2f), 0.5f)
    }

    @Test fun pinchRatioAndClamp() {
        assertEquals(2f, CollageLayout.spanRatio(0f, 0f, 100f, 0f, 0f, 0f, 200f, 0f), eps)
        assertEquals(1f, CollageLayout.spanRatio(0f, 0f, 2f, 0f, 0f, 0f, 200f, 0f), eps) // too close to trust
        assertEquals(CollageLayout.MAX_USER_SCALE, CollageLayout.clampUserScale(100f), eps)
        assertEquals(CollageLayout.MIN_USER_SCALE, CollageLayout.clampUserScale(0f), eps)
    }

    @Test fun twistAppliesClockwiseAsNegativeTurnAndWraps() {
        assertEquals(350f, CollageLayout.applyTwist(0f, 10f), eps)
        assertEquals(10f, CollageLayout.applyTwist(350f, -20f), eps)
    }

    @Test fun sizeLabels() {
        assertEquals("48 cm", CollageLayout.sizeLabel(0.48f))
        assertEquals("1.2 m", CollageLayout.sizeLabel(1.2f))
    }

    /** The activity hands SceneView Euler angles made by kotlin-math; SceneView turns them back with fromEuler. */
    @Test fun quaternionSurvivesSceneViewEulerRoundTrip() {
        val qs = listOf(
            floatArrayOf(0f, 0f, 0f, 1f),
            yaw(37f),
            floatArrayOf(0.1f, 0.7f, -0.2f, 0.67f),
            floatArrayOf(-0.3f, 0.2f, 0.5f, 0.78f),
        )
        for (raw in qs) {
            val q = Quaternion(raw[0], raw[1], raw[2], raw[3]).let { dev.romainguy.kotlin.math.normalize(it) }
            val back = Quaternion.fromEuler(q.toEulerAngles())
            val v = Float3(0.3f, -0.4f, 0.8f)
            val a = q * v
            val b = back * v
            assertEquals(a.x, b.x, 1e-3f); assertEquals(a.y, b.y, 1e-3f); assertEquals(a.z, b.z, 1e-3f)
            // And our own rotate agrees with kotlin-math.
            val ours = CollageLayout.rotate(floatArrayOf(q.x, q.y, q.z, q.w), floatArrayOf(v.x, v.y, v.z))
            assertEquals(a.x, ours[0], 1e-3f); assertEquals(a.y, ours[1], 1e-3f); assertEquals(a.z, ours[2], 1e-3f)
        }
    }
}
