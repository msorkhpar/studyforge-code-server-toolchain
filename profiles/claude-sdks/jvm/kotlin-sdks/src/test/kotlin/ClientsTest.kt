import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class ClientsTest {
    @Test
    fun namesTheSdks() {
        assertEquals("AnthropicClient+Server+Client", describe())
    }
}
