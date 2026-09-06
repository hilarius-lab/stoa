package com.smartnotebook.buildlogic.architecture

import java.io.File
import org.gradle.api.DefaultTask
import org.gradle.api.GradleException
import org.gradle.api.file.ConfigurableFileCollection
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.InputFiles
import org.gradle.api.tasks.PathSensitive
import org.gradle.api.tasks.PathSensitivity
import org.gradle.api.tasks.TaskAction

abstract class ArchitectureTestTask : DefaultTask() {

    @get:Input
    abstract val actualModules: org.gradle.api.provider.ListProperty<String>

    @get:Input
    abstract val moduleEdges: org.gradle.api.provider.ListProperty<String>

    @get:Input
    abstract val externalDependencies: org.gradle.api.provider.ListProperty<String>

    @get:Input
    abstract val moduleSourceRoots: org.gradle.api.provider.ListProperty<String>

    @get:InputFiles
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val sourceRoots: ConfigurableFileCollection

    @TaskAction
    fun execute() {
        val violations = LinkedHashSet<String>()
        val actual = actualModules.get().toSet()
        val expected = ArchitectureRules.expectedModules.toSet()

        (expected - actual).forEach { violations.add("fehlendes Modul: $it") }
        (actual - expected).forEach { violations.add("unerwartetes Modul: $it") }

        val graph = actualModules.get().associateWith { mutableSetOf<String>() }.toMutableMap()
        moduleEdges.get().forEach { edge ->
            val parts = edge.split('\u001F', limit = 2)
            if (parts.size != 2) {
                violations.add("ungueltige Modul-Kante: $edge")
                return@forEach
            }
            val from = parts[0]
            val to = parts[1]
            if (from !in actual || to !in actual) {
                violations.add("Modul-Kante referenziert unbekanntes Modul: $from -> $to")
                return@forEach
            }
            graph[from]?.add(to)
            val allowed = ArchitectureRules.allowedDependencies[from].orEmpty()
            if (to !in allowed) {
                violations.add("verbotene Modulabhaengigkeit: $from -> $to")
            }
        }

        violations.addAll(findCycles(graph))

        externalDependencies.get().forEach { entry ->
            val parts = entry.split('\u001F', limit = 4)
            if (parts.size != 4) {
                violations.add("ungueltige Abhaengigkeitsangabe: $entry")
                return@forEach
            }
            val module = parts[0]
            val group = parts[1]
            val artifact = parts[2]
            val configuration = parts[3]
            val reason = ArchitectureRules.externalDependencyViolation(module, group, artifact)
            if (reason != null) {
                violations.add("verbotene externe Abhaengigkeit $group:$artifact in $configuration ($module): $reason")
            }
        }

        var scannedSources = 0
        moduleSourceRoots.get().forEach { entry ->
            val parts = entry.split('\u001F', limit = 2)
            if (parts.size != 2) {
                violations.add("ungueltige Quellverzeichnis-Angabe: $entry")
                return@forEach
            }
            val module = parts[0]
            val sourceRoot = File(parts[1])
            if (!sourceRoot.isDirectory) {
                return@forEach
            }
            val forbidden = ArchitectureRules.forbiddenImportPrefixes(module)
            sourceRoot.walkTopDown().forEach { file ->
                val isSource = file.isFile && (file.extension == "kt" || file.extension == "java")
                val isGeneratedWire = file.invariantSeparatorsPath.contains("wire" + File.separator + "generated")
                if (!isSource || isGeneratedWire) {
                    return@forEach
                }
                scannedSources++
                val relativePath = file.relativeTo(sourceRoot).invariantSeparatorsPath
                val content = file.readText(Charsets.UTF_8)
                if (forbidden.isEmpty()) {
                    return@forEach
                }
                val importHits = LinkedHashSet<String>()
                content.lineSequence().forEach { rawLine ->
                    val line = rawLine.trim()
                    if (!line.startsWith("import ")) {
                        return@forEach
                    }
                    val imported = line.removePrefix("import ").substringBefore(" as ").trim()
                    forbidden.forEach { prefix ->
                        if (matchesPrefix(imported, prefix)) {
                            importHits.add(prefix)
                            violations.add(
                                "verbotener Import $imported in $module/$relativePath: " +
                                    "Modulgrenze aus NATIVE_ANDROID_ARCHITECTURE.md verletzt",
                            )
                        }
                    }
                }
                forbidden.forEach { prefix ->
                    if (prefix in importHits) {
                        return@forEach
                    }
                    val needle = if (prefix.endsWith(".")) prefix else "$prefix."
                    val callNeedle = if (prefix.endsWith(".")) null else "$prefix("
                    if (content.contains(needle) || (callNeedle != null && content.contains(callNeedle))) {
                        violations.add(
                            "verbotener direkter Zugriff auf $prefix in $module/$relativePath: " +
                                "Modulgrenze aus NATIVE_ANDROID_ARCHITECTURE.md verletzt",
                        )
                    }
                }
            }
        }

        if (violations.isNotEmpty()) {
            throw GradleException(
                "Architektur-Test fehlgeschlagen:\n" +
                    violations.sorted().joinToString("\n") { "  - $it" },
            )
        }

        logger.lifecycle(
            "Architektur-Test: ${actual.size} Module, ${moduleEdges.get().size} Kanten, " +
                "$scannedSources Quelldateien, 0 Verstoesse.",
        )
    }

    private fun matchesPrefix(value: String, prefix: String): Boolean {
        return if (prefix.endsWith(".")) {
            value == prefix.trimEnd('.') || value.startsWith(prefix)
        } else {
            value == prefix || value.startsWith("$prefix.")
        }
    }

    private fun findCycles(graph: Map<String, MutableSet<String>>): List<String> {
        val state = mutableMapOf<String, Int>()
        val cycles = LinkedHashSet<String>()

        fun dfs(node: String, path: MutableList<String>) {
            state[node] = 1
            path.add(node)
            graph[node].orEmpty().sorted().forEach { next ->
                val marker = state[next] ?: 0
                when (marker) {
                    0 -> dfs(next, path)
                    1 -> {
                        val start = path.indexOf(next)
                        if (start >= 0) {
                            cycles.add(path.subList(start, path.size).joinToString(" -> ") + " -> $next")
                        }
                    }
                }
            }
            path.removeAt(path.size - 1)
            state[node] = 2
        }

        graph.keys.sorted().forEach { node ->
            if (state[node] == null) {
                dfs(node, mutableListOf())
            }
        }
        return cycles.toList()
    }
}
