package com.scrapp.app.glasses

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class VoiceCommandMatcherTest {
    private fun cmd(text: String) = VoiceCommandMatcher.match(text)

    @Test fun plainPhrase() = assertEquals("scrapbook", cmd("Scrap that.")?.command)
    @Test fun oldPhraseStillWorks() = assertEquals("scrapbook", cmd("scrapbook that")?.command)
    @Test fun scrapThatWithObject() = assertEquals("lamp", cmd("scrap that lamp")?.prompt)
    @Test fun scrapThatPlain() = assertEquals("scrapbook", cmd("hey scrap that")?.command)
    @Test fun scrapWithoutThatIsChatter() = assertNull(cmd("scrap the plan"))
    @Test fun splitWord() = assertEquals("scrapbook", cmd("scrap book that")?.command)
    @Test fun misheard() = assertEquals("scrapbook", cmd("Scrabble cat")?.command)
    @Test fun fuzzy() = assertEquals("scrapbook", cmd("crab book that")?.command)
    @Test fun objectPrompt() = assertEquals("lamp", cmd("hey scrapbook this lamp")?.prompt)
    @Test fun huntFound() = assertEquals("found", cmd("I found it")?.command)
    @Test fun huntFoundInSentence() = assertEquals("found", cmd("oh wow I think I found it")?.command)
    @Test fun huntFoundOne() = assertEquals("found", cmd("found one")?.command)
    @Test fun foundCarriesNoPrompt() = assertNull(cmd("found it")?.prompt)
    @Test fun gotItIsJustChatter() = assertNull(cmd("got it thanks"))
    @Test fun foundMidSentenceIsChatter() = assertNull(cmd("I found it hard to read"))
    @Test fun ignoresChatter() = assertNull(cmd("what a nice scrapbook"))
    @Test fun ignoresBookTalk() = assertNull(cmd("the book that I read"))
}
