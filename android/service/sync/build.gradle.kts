plugins {
    id("androidlib")
}

android {
    namespace = "com.smartnotebook.service.sync"
}

dependencies {
    implementation(project(":core:model"))
    implementation(libs.work.runtime.ktx)
    implementation(libs.kotlinx.coroutines.android)
    testImplementation(libs.junit4)
    testImplementation(libs.truth)
}
