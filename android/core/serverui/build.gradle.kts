plugins {
    id("androidlib")
    id("android-compose")
    alias(libs.plugins.roborazzi)
}

android {
    namespace = "com.smartnotebook.core.serverui"
}

roborazzi {
    outputDir.set(file("src/screenshots"))
}

dependencies {
    api(project(":core:model"))
    implementation(project(":core:designsystem"))
    testImplementation(libs.junit4)
    testImplementation(libs.truth)
    testImplementation(libs.robolectric)
    testImplementation(libs.roborazzi)
    testImplementation(libs.roborazzi.compose)
    testImplementation(libs.androidx.test.ext.junit)
    testImplementation(libs.androidx.activity.compose)
}
