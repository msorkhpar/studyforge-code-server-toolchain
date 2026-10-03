package sdkwarm;

import com.anthropic.client.AnthropicClient;
import io.modelcontextprotocol.spec.McpSchema;

/** Names one type of each SDK, so the compile resolves both jars' classpaths. */
public final class Clients {
    private Clients() {
    }

    public static String describe() {
        return AnthropicClient.class.getSimpleName() + "+" + McpSchema.class.getSimpleName();
    }
}
