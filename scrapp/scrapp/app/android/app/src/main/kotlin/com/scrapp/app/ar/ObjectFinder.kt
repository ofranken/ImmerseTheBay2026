package com.scrapp.app.ar

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.PointF
import android.graphics.Rect
import android.graphics.YuvImage
import android.media.Image
import com.google.ar.core.Coordinates2d
import com.google.ar.core.Frame
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.objectdetector.ObjectDetector
import java.io.ByteArrayOutputStream

/**
 * "Hold up an apple": finds a COCO object class in the AR camera image with MediaPipe
 * (EfficientDet-Lite0, bundled at android/app/src/main/assets/efficientdet_lite0.tflite).
 */
class ObjectFinder(ctx: Context) {
    private val detector: ObjectDetector = ObjectDetector.createFromOptions(
        ctx,
        ObjectDetector.ObjectDetectorOptions.builder()
            .setBaseOptions(BaseOptions.builder().setModelAssetPath("efficientdet_lite0.tflite").build())
            .setRunningMode(RunningMode.IMAGE)
            .setMaxResults(10)
            .setScoreThreshold(0.35f)
            .build(),
    )

    /** Returns the detection centre in VIEW-normalised coordinates (0..1), or null. */
    fun find(viewAligned: Bitmap, label: String): PointF? {
        val result = detector.detect(BitmapImageBuilder(viewAligned).build())
        val best = result.detections()
            .filter { d -> d.categories().any { it.categoryName().equals(label, ignoreCase = true) } }
            .maxByOrNull { d -> d.categories().maxOf { it.score() } } ?: return null
        val box = best.boundingBox()
        return PointF(box.centerX() / viewAligned.width, box.centerY() / viewAligned.height)
    }

    fun close() = detector.close()

    companion object {
        /**
         * CPU camera image -> bitmap aligned with what the user sees on screen (rotated and
         * cropped exactly like the AR view), so detector coordinates == view coordinates.
         * Must be called inside the frame update; the caller closes [image].
         */
        fun viewAlignedBitmap(frame: Frame, image: Image, outWidth: Int, viewAspect: Float): Bitmap? {
            val src = yuvToBitmap(image) ?: return null
            // Where the view's top-left, top-right and bottom-left corners land in the camera image.
            val viewPts = floatArrayOf(0f, 0f, 1f, 0f, 0f, 1f)
            val imgPts = FloatArray(6)
            frame.transformCoordinates2d(Coordinates2d.VIEW_NORMALIZED, viewPts, Coordinates2d.IMAGE_NORMALIZED, imgPts)
            for (i in 0 until 3) {
                imgPts[i * 2] *= src.width
                imgPts[i * 2 + 1] *= src.height
            }
            val outH = (outWidth / viewAspect).toInt().coerceAtLeast(1)
            val dst = floatArrayOf(0f, 0f, outWidth.toFloat(), 0f, 0f, outH.toFloat())
            val m = Matrix().apply { setPolyToPoly(imgPts, 0, dst, 0, 3) }
            val out = Bitmap.createBitmap(outWidth, outH, Bitmap.Config.ARGB_8888)
            Canvas(out).drawBitmap(src, m, Paint(Paint.FILTER_BITMAP_FLAG))
            src.recycle()
            return out
        }

        private fun yuvToBitmap(image: Image): Bitmap? {
            if (image.format != ImageFormat.YUV_420_888) return null
            val w = image.width
            val h = image.height
            val nv21 = ByteArray(w * h * 3 / 2)
            val (yP, uP, vP) = image.planes
            // Y
            var pos = 0
            val yBuf = yP.buffer
            for (row in 0 until h) {
                yBuf.position(row * yP.rowStride)
                yBuf.get(nv21, pos, w)
                pos += w
            }
            // Interleaved VU
            val uBuf = uP.buffer
            val vBuf = vP.buffer
            for (row in 0 until h / 2) {
                for (col in 0 until w / 2) {
                    val uvIndex = row * uP.rowStride + col * uP.pixelStride
                    val vIndex = row * vP.rowStride + col * vP.pixelStride
                    nv21[pos++] = vBuf.get(vIndex)
                    nv21[pos++] = uBuf.get(uvIndex)
                }
            }
            val out = ByteArrayOutputStream()
            YuvImage(nv21, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 80, out)
            val bytes = out.toByteArray()
            return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }
    }
}
