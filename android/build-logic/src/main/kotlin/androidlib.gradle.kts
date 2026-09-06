plugins {
    id("com.android.library")
}

android {
    enableKotlin = true
    compileSdk = 37
    compileSdkMinor = 1
    defaultConfig {
        minSdk = 26
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
    lint {
        abortOnError = true
        checkReleaseBuilds = true
        checkTestSources = true
        checkDependencies = false
        warningsAsErrors = true
    }
}

tasks.withType<Test>().configureEach {
    failOnNoDiscoveredTests.set(false)
}
