plugins {
    id("androidlib")
    id("ksp-conv")
}

android {
    namespace = "com.smartnotebook.core.database"
}

dependencies {
    api(project(":core:model"))
    api(libs.room.runtime)
    api(libs.room.ktx)
    ksp(libs.room.compiler)
    implementation(libs.kotlinx.coroutines.android)
    testImplementation(libs.junit4)
    testImplementation(libs.truth)
}
