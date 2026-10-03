plugins {
    kotlin("jvm") version "2.4.20"
}

kotlin {
    jvmToolchain(25)
}

dependencies {
    implementation("com.anthropic:anthropic-java:2.68.0")
    implementation("io.modelcontextprotocol:kotlin-sdk:0.15.0")
    implementation("io.modelcontextprotocol:kotlin-sdk-server:0.15.0")
    implementation("io.modelcontextprotocol:kotlin-sdk-client:0.15.0")
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.test {
    useJUnitPlatform()
}
