package fixture

import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class FixtureTest {
    @Test
    fun writesJson() = assertEquals("""{"a":1}""", toJson(mapOf("a" to 1)))

    @Test
    fun shouts() = runBlocking { assertEquals("Hi!", shout("hi")) }
}
