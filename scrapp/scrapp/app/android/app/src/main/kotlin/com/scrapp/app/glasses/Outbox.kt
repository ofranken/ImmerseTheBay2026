package com.scrapp.app.glasses

import android.content.Context
import java.io.File
import org.json.JSONObject

/**
 * Captures land here first (JPEG + JSON metadata) so nothing is lost if the network is down or
 * the Flutter UI is not running. Dart uploads and then acks; acked entries are deleted.
 */
object Outbox {
    data class Entry(val id: String, val path: String, val meta: String)

    private fun dir(ctx: Context) = File(ctx.filesDir, "outbox").apply { mkdirs() }

    fun save(ctx: Context, jpeg: ByteArray, meta: JSONObject): Entry {
        val id = "cap-${System.currentTimeMillis()}"
        val img = File(dir(ctx), "$id.jpg").apply { writeBytes(jpeg) }
        File(dir(ctx), "$id.json").writeText(meta.toString())
        return Entry(id, img.absolutePath, meta.toString())
    }

    fun list(ctx: Context): List<Entry> =
        dir(ctx).listFiles { f -> f.extension == "jpg" }.orEmpty().sortedBy { it.name }.map { img ->
            val json = File(img.parentFile, img.nameWithoutExtension + ".json")
            Entry(img.nameWithoutExtension, img.absolutePath, if (json.exists()) json.readText() else "{}")
        }

    fun ack(ctx: Context, id: String) {
        File(dir(ctx), "$id.jpg").delete()
        File(dir(ctx), "$id.json").delete()
    }
}
