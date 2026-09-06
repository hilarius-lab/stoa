pluginManagement {
    includeBuild("build-logic")
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "smart-notebook-android"

include(":app")
include(":core:model")
include(":core:network")
include(":core:database")
include(":core:security")
include(":core:designsystem")
include(":core:serverui")
include(":data")
include(":feature:setup")
include(":feature:home")
include(":feature:search")
include(":feature:meeting")
include(":feature:chat")
include(":feature:settings")
include(":service:recording")
include(":service:sync")
