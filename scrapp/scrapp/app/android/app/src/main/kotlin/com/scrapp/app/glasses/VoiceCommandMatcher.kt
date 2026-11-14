package com.scrapp.app.glasses

/**
 * Finds "scrapbook that" in glasses transcripts. Speech recognizers mangle the coined word
 * ("scrap book that", "scrapple that", even "Scrabble cat"), so matching is fuzzy and
 * tolerant of the word split. Anything after the phrase becomes an optional object prompt:
 * "scrapbook that lamp" -> prompt "lamp" (used by a text-promptable segmenter such as SAM 3).
 */
object VoiceCommandMatcher {
    data class Match(val command: String, val prompt: String?)

    private val wakeVariants = listOf(
        "scrapbook", "scrap book", "scrapbooks", "scrap books", "scrapple", "scrabble",
        "scrap but", "scrap boo", "scrapbooking", "scrap that",
    )
    private val objectWords = setOf("that", "this", "it", "dat", "cat", "these", "those")
    private val foundPhrases = listOf("found it", "i found it", "got it")

    fun normalize(text: String): String =
        text.lowercase().replace(Regex("[^a-z ]"), " ").replace(Regex("\\s+"), " ").trim()

    fun match(raw: String): Match? {
        val t = normalize(raw)
        if (t.isEmpty()) return null
        if (foundPhrases.any { t == it || t.endsWith(" $it") }) return Match("found", null)

        val words = t.split(" ")
        for (i in words.indices) {
            // Try one- and two-word windows for the wake word ("scrapbook" / "scrap book").
            for (span in 1..2) {
                if (i + span > words.size) continue
                val candidate = words.subList(i, i + span).joinToString(" ")
                if (!isWake(candidate)) continue
                val rest = words.drop(i + span)
                if (rest.isEmpty() || rest.first() !in objectWords) {
                    // "scrap that" alone is already a full command
                    if (candidate == "scrap that") return Match("scrapbook", null)
                    continue
                }
                val prompt = rest.drop(1).joinToString(" ").ifBlank { null }
                return Match("scrapbook", prompt)
            }
        }
        return null
    }

    private fun isWake(candidate: String): Boolean =
        wakeVariants.any { it == candidate } || similarity(candidate.replace(" ", ""), "scrapbook") >= 0.75

    private fun similarity(a: String, b: String): Double {
        if (a.isEmpty() || b.isEmpty()) return 0.0
        val d = Array(a.length + 1) { IntArray(b.length + 1) }
        for (i in 0..a.length) d[i][0] = i
        for (j in 0..b.length) d[0][j] = j
        for (i in 1..a.length) for (j in 1..b.length) {
            val cost = if (a[i - 1] == b[j - 1]) 0 else 1
            d[i][j] = minOf(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
        }
        return 1.0 - d[a.length][b.length].toDouble() / maxOf(a.length, b.length)
    }
}
