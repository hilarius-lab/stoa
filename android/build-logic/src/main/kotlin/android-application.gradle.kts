plugins {
    id("com.android.application")
}

android {
    enableKotlin = true
    compileSdk = 37
    compileSdkMinor = 1
    defaultConfig {
        minSdk = 26
        targetSdk = 36
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildTypes {
        release {
            isMinifyEnabled = true
        }
    }
    lint {
        abortOnError = true
        checkReleaseBuilds = true
        checkTestSources = true
        checkDependencies = false
        warningsAsErrors = true
    }
}
