plugins {
    `kotlin-dsl`
}

group = "com.smartnotebook.buildlogic"

dependencyLocking {
    lockAllConfigurations()
    ignoredDependencies.add("junit:junit")
    ignoredDependencies.add("org.hamcrest:hamcrest-core")
}

dependencies {
    implementation(libs.agp)
    implementation(libs.kotlin.gradle.plugin)
    implementation(libs.kotlin.compose.compiler.gradle.plugin)
    implementation(libs.ksp.gradle.plugin)
    implementation(libs.hilt.gradle.plugin)
    implementation(libs.roborazzi.gradle.plugin)
    implementation(libs.kotlinx.serialization.json)
    testImplementation(libs.junit4)
}

tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
    compilerOptions {
        allWarningsAsErrors.set(true)
    }
}
