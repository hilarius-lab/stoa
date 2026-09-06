plugins {
    id("org.jetbrains.kotlin.plugin.compose")
}

val libs = project.extensions.getByType(org.gradle.api.artifacts.VersionCatalogsExtension::class.java).named("libs")

dependencies {
    add("implementation", platform(libs.findLibrary("compose-bom").get()))
    add("implementation", libs.findLibrary("compose-ui").get())
    add("implementation", libs.findLibrary("compose-ui-graphics").get())
    add("implementation", libs.findLibrary("compose-ui-tooling-preview").get())
    add("implementation", libs.findLibrary("compose-material3").get())
    add("debugImplementation", libs.findLibrary("compose-ui-tooling").get())
}
