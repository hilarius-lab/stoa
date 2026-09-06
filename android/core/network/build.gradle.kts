plugins {
    id("androidlib")
    id("wiregen")
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.smartnotebook.core.network"
}

tasks.withType<Test>().configureEach {
    systemProperty(
        "contractsDir",
        rootProject.projectDir.parentFile
            .resolve("contracts")
            .absolutePath,
    )
}

dependencies {
    api(project(":core:model"))
    api(libs.retrofit)
    api(libs.retrofit.converter.kotlinx.serialization)
    api(libs.okhttp)
    api(libs.okhttp.sse)
    implementation(libs.kotlinx.serialization.json)
    testImplementation(libs.junit4)
    testImplementation(libs.truth)
    testImplementation(libs.mockwebserver3)
    testImplementation(libs.kotlinx.coroutines.test)
}
