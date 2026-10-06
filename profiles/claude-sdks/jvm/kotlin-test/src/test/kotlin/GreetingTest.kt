import kotlin.test.Test
import kotlin.test.assertEquals

class GreetingTest {
    @Test
    fun greets() {
        assertEquals("hello, claude", greeting("claude"))
    }
}
