// A FIXTURE prime: a placeholder project, no consumer's real build.
// Plugins resolve from Maven Central only, and every file Gradle fetches is
// checked against gradle/verification-metadata.xml.
pluginManagement {
    repositories {
        mavenCentral()
    }
}

rootProject.name = "prime-fixture"

include("java", "kotlin")
