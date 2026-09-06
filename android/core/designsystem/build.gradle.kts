plugins {
    id("androidlib")
    id("android-compose")
    alias(libs.plugins.roborazzi)
}

android {
    namespace = "com.smartnotebook.core.designsystem"
}

roborazzi {
    outputDir.set(file("src/screenshots"))
}

dependencies {
    api(libs.androidx.core.ktx)
    testImplementation(libs.junit4)
    testImplementation(libs.truth)
    testImplementation(libs.robolectric)
    testImplementation(libs.roborazzi)
    testImplementation(libs.roborazzi.compose)
    testImplementation(libs.androidx.test.ext.junit)
    testImplementation(libs.androidx.activity.compose)
}
