package sdkwarm;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class ClientsTest {
    @Test
    void namesBothSdks() {
        assertEquals("AnthropicClient+McpSchema", Clients.describe());
    }
}
