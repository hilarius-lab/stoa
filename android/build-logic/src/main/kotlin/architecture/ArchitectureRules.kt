package com.smartnotebook.buildlogic.architecture

object ArchitectureRules {

    private val featureModules = listOf(
        ":feature:setup",
        ":feature:home",
        ":feature:search",
        ":feature:meeting",
        ":feature:chat",
        ":feature:settings",
    )

    private val serviceModules = listOf(
        ":service:recording",
        ":service:sync",
    )

    val expectedModules: List<String> = listOf(
        ":app",
        ":core:model",
        ":core:network",
        ":core:database",
        ":core:security",
        ":core:designsystem",
        ":core:serverui",
        ":data",
        ":feature:setup",
        ":feature:home",
        ":feature:search",
        ":feature:meeting",
        ":feature:chat",
        ":feature:settings",
        ":service:recording",
        ":service:sync",
    )

    val allowedDependencies: Map<String, Set<String>> = buildMap {
        put(
            ":app",
            setOf(
                ":data",
                ":core:model",
                ":core:designsystem",
                ":core:serverui",
                *featureModules.toTypedArray(),
                *serviceModules.toTypedArray(),
            ),
        )
        put(":core:model", emptySet())
        put(":core:network", setOf(":core:model"))
        put(":core:database", setOf(":core:model"))
        put(":core:security", setOf(":core:model"))
        put(":core:designsystem", emptySet())
        put(":core:serverui", setOf(":core:model", ":core:designsystem"))
        put(
            ":data",
            setOf(":core:model", ":core:network", ":core:database", ":core:security"),
        )
        featureModules.forEach { feature ->
            put(feature, setOf(":core:model", ":core:designsystem", ":core:serverui", ":data"))
        }
        put(":service:recording", setOf(":core:model", ":core:security", ":data"))
        put(":service:sync", setOf(":core:model", ":core:security", ":data"))
    }

    private val uiImportPrefixes = listOf(
        "androidx.compose",
        "androidx.navigation",
        "androidx.activity",
        "androidx.hilt",
        "com.smartnotebook.core.designsystem",
        "com.smartnotebook.core.serverui",
    )

    private val dataLayerImportPrefixes = listOf(
        "retrofit2",
        "okhttp3",
        "androidx.room",
        "androidx.datastore",
        "net.zetetic",
        "androidx.work",
        "com.smartnotebook.core.network",
        "com.smartnotebook.core.database",
        "com.smartnotebook.core.security",
    )

    private val fileAccessImportPrefixes = listOf(
        "java.io.File",
        "java.io.FileInputStream",
        "java.io.FileOutputStream",
        "java.nio.file",
    )

    private val upperLayerImportPrefixes = listOf(
        "com.smartnotebook.feature",
        "com.smartnotebook.service",
        "com.smartnotebook.app",
    )

    fun forbiddenImportPrefixes(module: String): List<String> = when {
        module == ":core:model" -> listOf(
            "android.",
            "androidx.",
            "com.google.dagger",
            "com.squareup",
            "net.zetetic",
            "retrofit2",
            "okhttp3",
            "androidx.room",
            "androidx.datastore",
            "androidx.work",
            "java.io.File",
            "java.io.FileInputStream",
            "java.io.FileOutputStream",
            "java.nio.file",
        )

        module == ":core:network" -> listOf(
            "androidx.room",
            "androidx.datastore",
            "net.zetetic",
            "androidx.work",
            "com.smartnotebook.core.database",
            "com.smartnotebook.core.security",
            "com.smartnotebook.data",
            "com.smartnotebook.feature",
            "com.smartnotebook.service",
            "com.smartnotebook.app",
            "androidx.compose",
            "androidx.navigation",
            "androidx.activity",
            "androidx.hilt",
        )

        module == ":core:database" -> listOf(
            "com.squareup.retrofit2",
            "com.squareup.okhttp3",
            "androidx.datastore",
            "net.zetetic",
            "androidx.work",
            "com.smartnotebook.core.network",
            "com.smartnotebook.core.security",
            "com.smartnotebook.data",
            "com.smartnotebook.feature",
            "com.smartnotebook.service",
            "com.smartnotebook.app",
            "androidx.compose",
            "androidx.navigation",
            "androidx.activity",
            "androidx.hilt",
        )

        module == ":core:security" -> listOf(
            "com.squareup.retrofit2",
            "com.squareup.okhttp3",
            "androidx.room",
            "androidx.datastore",
            "androidx.work",
            "com.smartnotebook.core.network",
            "com.smartnotebook.core.database",
            "com.smartnotebook.data",
            "com.smartnotebook.feature",
            "com.smartnotebook.service",
            "com.smartnotebook.app",
            "androidx.compose",
            "androidx.navigation",
            "androidx.activity",
            "androidx.hilt",
        )

        module == ":core:designsystem" || module == ":core:serverui" -> listOf(
            "com.squareup.retrofit2",
            "com.squareup.okhttp3",
            "androidx.room",
            "androidx.datastore",
            "net.zetetic",
            "androidx.work",
            "com.smartnotebook.core.network",
            "com.smartnotebook.core.database",
            "com.smartnotebook.core.security",
            "com.smartnotebook.data",
            "com.smartnotebook.feature",
            "com.smartnotebook.service",
            "com.smartnotebook.app",
        )

        module == ":data" -> uiImportPrefixes + upperLayerImportPrefixes

        module.startsWith(":feature:") -> dataLayerImportPrefixes + fileAccessImportPrefixes

        module.startsWith(":service:") -> uiImportPrefixes +
            listOf(
                "com.squareup.retrofit2",
                "com.squareup.okhttp3",
                "androidx.room",
                "androidx.datastore",
                "net.zetetic",
                "com.smartnotebook.core.network",
                "com.smartnotebook.core.database",
            )

        module == ":app" -> listOf(
            "com.squareup.retrofit2",
            "com.squareup.okhttp3",
            "androidx.room",
            "androidx.datastore",
            "net.zetetic",
            "androidx.work",
            "com.smartnotebook.core.network",
            "com.smartnotebook.core.database",
            "com.smartnotebook.core.security",
        )

        else -> emptyList()
    }

    fun externalDependencyViolation(module: String, group: String, artifact: String): String? {
        val isUi = group == "androidx.compose" ||
            artifact in setOf("navigation-compose", "activity-compose", "hilt-navigation-compose")

        return when {
            module == ":core:model" -> {
                if (group == "org.jetbrains.kotlinx" || group == "org.jetbrains.kotlin") {
                    null
                } else {
                    "core:model bleibt reines Kotlin/JVM ohne Android-, DI-, Netzwerk- oder Persistenzabhaengigkeit"
                }
            }

            module == ":core:network" -> {
                if (isUi || group in setOf("androidx.room", "androidx.datastore", "net.zetetic", "androidx.work")) {
                    "core:network kennt nur core:model und den festgelegten Netzwerkstack"
                } else {
                    null
                }
            }

            module == ":core:database" -> {
                if (isUi || group in setOf("com.squareup.retrofit2", "com.squareup.okhttp3", "androidx.datastore", "net.zetetic", "androidx.work")) {
                    "core:database kennt nur core:model und den Room-Stack"
                } else {
                    null
                }
            }

            module == ":core:security" -> {
                if (isUi || group in setOf("com.squareup.retrofit2", "com.squareup.okhttp3", "androidx.room", "androidx.datastore", "androidx.work")) {
                    "core:security kennt nur Krypto-, Keystore- und Dateischutzabhaengigkeiten"
                } else {
                    null
                }
            }

            module == ":core:designsystem" || module == ":core:serverui" -> {
                if (group in setOf(
                        "com.squareup.retrofit2",
                        "com.squareup.okhttp3",
                        "androidx.room",
                        "androidx.datastore",
                        "net.zetetic",
                        "androidx.work",
                        "com.google.dagger",
                    )
                ) {
                    "core:designsystem und core:serverui bleiben ohne Daten-, Netzwerk- oder Workmanagerabhaengigkeit"
                } else {
                    null
                }
            }

            module == ":data" -> {
                if (isUi) {
                    "data bleibt ohne UI-Abhaengigkeiten"
                } else {
                    null
                }
            }

            module.startsWith(":feature:") -> {
                if (group in setOf(
                        "com.squareup.retrofit2",
                        "com.squareup.okhttp3",
                        "androidx.room",
                        "androidx.datastore",
                        "net.zetetic",
                        "androidx.work",
                    )
                ) {
                    "Features greifen nie direkt auf Netzwerk-, Persistenz- oder Workmanagerstack zu"
                } else {
                    null
                }
            }

            module == ":service:recording" -> {
                if (isUi || group == "androidx.work") {
                    "service:recording ist UI-frei und startet keine Workmanager-Jobs"
                } else {
                    null
                }
            }

            module == ":service:sync" -> {
                if (isUi) {
                    "service:sync ist UI-frei"
                } else {
                    null
                }
            }

            module == ":app" -> {
                if (group in setOf(
                        "com.squareup.retrofit2",
                        "com.squareup.okhttp3",
                        "androidx.room",
                        "androidx.datastore",
                        "net.zetetic",
                        "androidx.work",
                    )
                ) {
                    "app greift nie direkt auf Netzwerk-, Persistenz- oder Workmanagerstack zu"
                } else {
                    null
                }
            }

            else -> "unbekanntes Modul $module"
        }
    }
}
