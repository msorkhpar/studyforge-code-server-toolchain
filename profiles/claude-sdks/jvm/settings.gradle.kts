// The claude-sdks profile's JVM project: one subproject per distinct dependency set. Plugins and
// libraries resolve from the repositories a course practice's own build names (the Gradle plugin
// portal for plugins, Maven Central for libraries), and every file Gradle fetches is checked
// against gradle/verification-metadata.xml.
rootProject.name = "claude-sdks"

include("java-sdks", "kotlin-sdks", "kotlin-test")
