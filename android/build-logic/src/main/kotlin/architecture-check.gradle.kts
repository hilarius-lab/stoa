import com.smartnotebook.buildlogic.architecture.ArchitectureTestTask
import com.smartnotebook.buildlogic.uitext.UiTextCheckTask
import org.gradle.api.artifacts.ProjectDependency

val architectureTest = tasks.register<ArchitectureTestTask>("architectureTest") {
    group = "verification"
    description = "Prueft Modulstruktur, Abhaengigkeitsrichtung, Zyklen und verbotene Modulzugriffe."
}

val uiTextCheck = tasks.register<UiTextCheckTask>("uiTextCheck") {
    group = "verification"
    description = "Prueft hartcodierte sichtbare UI-Texte sowie englische und deutsche String-Ressourcen."
}

gradle.projectsEvaluated {
    val task = architectureTest.get()
    val mainConfigurations = setOf("api", "implementation", "compileOnly", "runtimeOnly")
    val edges = linkedSetOf<String>()
    val externalDependencies = linkedSetOf<String>()
    val moduleProjects = subprojects.filter { it.buildFile.exists() }.sortedBy { it.path }

    uiTextCheck.get().apply {
        moduleSourceRoots.addAll(
            moduleProjects.map { moduleProject ->
                val mainSourceDir = moduleProject.projectDir.resolve("src/main")
                "${moduleProject.path}\u001F${mainSourceDir.absolutePath}"
            },
        )
        moduleResourceRoots.addAll(
            moduleProjects.map { moduleProject ->
                val resDir = moduleProject.projectDir.resolve("src/main/res")
                "${moduleProject.path}\u001F${resDir.absolutePath}"
            },
        )
        sourceRoots.from(moduleProjects.map { it.projectDir.resolve("src/main") })
        resourceRoots.from(moduleProjects.map { it.projectDir.resolve("src/main/res") })
    }

    moduleProjects.forEach { moduleProject ->
        moduleProject.configurations
            .matching { configuration -> (mainConfigurations.contains(configuration.name) ?: false) }
            .forEach { configuration ->
                for (dependency in configuration.dependencies) {
                    if (dependency is ProjectDependency) {
                        edges.add("${moduleProject.path}\u001F${dependency.path}")
                    } else {
                        dependency.group?.let { group ->
                            externalDependencies.add(
                                "${moduleProject.path}\u001F$group\u001F${dependency.name}\u001F${configuration.name}",
                            )
                        }
                    }
                }
            }
    }

    task.actualModules.addAll(moduleProjects.map { it.path })
    task.moduleEdges.addAll(edges.sorted())
    task.externalDependencies.addAll(externalDependencies.sorted())
    task.moduleSourceRoots.addAll(
        moduleProjects.map { moduleProject ->
            val mainSourceDir = moduleProject.projectDir.resolve("src/main")
            "${moduleProject.path}\u001F${mainSourceDir.absolutePath}"
        },
    )
    task.sourceRoots.from(
        moduleProjects.map { moduleProject -> moduleProject.projectDir.resolve("src/main") },
    )
}
