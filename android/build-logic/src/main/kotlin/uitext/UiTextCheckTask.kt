package com.smartnotebook.buildlogic.uitext

import java.io.File
import org.gradle.api.DefaultTask
import org.gradle.api.GradleException
import org.gradle.api.file.ConfigurableFileCollection
import org.gradle.api.provider.ListProperty
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.InputFiles
import org.gradle.api.tasks.PathSensitive
import org.gradle.api.tasks.PathSensitivity
import org.gradle.api.tasks.TaskAction

abstract class UiTextCheckTask : DefaultTask() {

    @get:Input
    abstract val moduleSourceRoots: ListProperty<String>

    @get:Input
    abstract val moduleResourceRoots: ListProperty<String>

    @get:InputFiles
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val sourceRoots: ConfigurableFileCollection

    @get:InputFiles
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val resourceRoots: ConfigurableFileCollection

    @TaskAction
    fun execute() {
        val violations = LinkedHashSet<String>()
        var scannedSourceFiles = 0
        var scannedXmlFiles = 0

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

            sourceRoot.walkTopDown().forEach { file ->
                if (!file.isFile) {
                    return@forEach
                }
                val relative = file.relativeTo(sourceRoot).invariantSeparatorsPath
                if (
                    relative.contains("wire" + File.separator + "generated") ||
                    relative.startsWith("build" + File.separator)
                ) {
                    return@forEach
                }
                when (file.extension) {
                    "kt", "java" -> {
                        scannedSourceFiles++
                        violations.addAll(UiTextScanner.findSourceViolations(file, module, sourceRoot))
                    }

                    "xml" -> {
                        scannedXmlFiles++
                        violations.addAll(UiTextScanner.findXmlViolations(file, module, sourceRoot))
                    }

                    else -> Unit
                }
            }
        }

        moduleResourceRoots.get().forEach { entry ->
            val parts = entry.split('\u001F', limit = 2)
            if (parts.size != 2) {
                violations.add("ungueltige Ressourcenverzeichnis-Angabe: $entry")
                return@forEach
            }
            val module = parts[0]
            violations.addAll(UiTextScanner.resourceViolations(module, File(parts[1])))
        }

        if (violations.isNotEmpty()) {
            throw GradleException(
                "UI-Text-Check fehlgeschlagen:\n" +
                    violations.sorted().joinToString("\n") { "  - $it" },
            )
        }

        logger.lifecycle(
            "UI-Text-Check: $scannedSourceFiles Kotlin/Java-Dateien, $scannedXmlFiles XML-Dateien, " +
                "${moduleResourceRoots.get().size} Ressourcenmodule, 0 Verstoesse.",
        )
    }
}
