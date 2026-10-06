import com.anthropic.client.AnthropicClient
import io.modelcontextprotocol.kotlin.sdk.server.Server
import io.modelcontextprotocol.kotlin.sdk.client.Client

/** Names one type of each SDK, so the compile resolves their classpaths. */
fun describe(): String = listOf(AnthropicClient::class, Server::class, Client::class).joinToString("+") { it.simpleName ?: "" }
