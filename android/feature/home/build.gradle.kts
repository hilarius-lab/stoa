plugins {
    id("androidlib")
    id("android-compose")
    id("hilt-android")
}

android {
    namespace = "com.smartnotebook.feature.home"
}

dependencies {
    implementation(project(":core:model"))
    implementation(project(":core:designsystem"))
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.hilt.navigation.compose)
    testImplementation(libs.junit4)
    testImplementation(libs.truth)
}
