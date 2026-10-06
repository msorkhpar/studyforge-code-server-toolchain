package fixture

import com.google.gson.Gson
import org.apache.commons.lang3.StringUtils

/** One real source per library, so every classpath is resolved when the project is warmed. */
fun toJson(value: Map<String, Int>): String = Gson().toJson(value)

fun shout(text: String): String = StringUtils.capitalize(text) + "!"
