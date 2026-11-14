package com.scrapp.app.glasses

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class VoiceCommandMatcherTest {
    private fun cmd(text: String) = VoiceCommandMatcher.match(text)

    @Test fun plainPhrase() = assertEquals("scrapbook", cmd("Scrapbook that.")?.command)
    @Test fun splitWord() = assertEquals("scrapbook", cmd("scrap book that")?.command)
    @Test fun misheard() = assertEquals("scrapbook", cmd("Scrabble cat")?.command)
    @Test fun fuzzy() = assertEquals("scrapbook", cmd("crab book that")?.command)
    @Test fun objectPrompt() = assertEquals("lamp", cmd("hey scrapbook this lamp")?.prompt)
    @Test fun huntFound() = assertEquals("found", cmd("I found it")?.command)
    @Test fun ignoresChatter() = assertNull(cmd("what a nice scrapbook"))
    @Test fun ignoresBookTalk() = assertNull(cmd("the book that I read"))
}
