plugins {
    id("androidlib")
}

android {
    namespace = "com.smartnotebook.core.security"
}

dependencies {
    api(libs.sqlcipher.android)
    implementation(libs.kotlinx.coroutines.android)
    testImplementation(libs.junit4)
    testImplementation(libs.truth)
}
