// The fixture profile project: a small stand-in for a framework profile's closure. One subproject
// per distinct dependency set. Plugins and libraries resolve from Maven Central only, and every
// file Gradle fetches is checked against gradle/verification-metadata.xml.
pluginManagement {
    repositories {
        mavenCentral()
    }
}

rootProject.name = "fixture-libs"

include("core")
