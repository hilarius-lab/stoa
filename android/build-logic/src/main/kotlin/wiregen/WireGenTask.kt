package com.smartnotebook.buildlogic.wiregen

import java.io.File
import org.gradle.api.DefaultTask
import org.gradle.api.GradleException
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.tasks.InputFile
import org.gradle.api.tasks.Internal
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.PathSensitive
import org.gradle.api.tasks.PathSensitivity
import org.gradle.api.tasks.TaskAction

abstract class WireGenGenerateTask : DefaultTask() {

    @get:InputFile
    @get:PathSensitive(PathSensitivity.NONE)
    abstract val snapshot: RegularFileProperty

    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty

    @TaskAction
    fun generate() {
        val files = WireDtoGenerator.generate(snapshot.get().asFile)
        val out = outputDir.get().asFile
        out.mkdirs()
        out.listFiles { _, name -> name.endsWith(".kt") }?.forEach { it.delete() }
        for ((name, content) in files) {
            File(out, name).writeText(content, Charsets.UTF_8)
        }
    }
}

abstract class WireGenVerifyTask : DefaultTask() {

    @get:InputFile
    @get:PathSensitive(PathSensitivity.NONE)
    abstract val snapshot: RegularFileProperty

    @get:Internal
    abstract val sourceDir: DirectoryProperty

    @TaskAction
    fun verify() {
        val expected = WireDtoGenerator.generate(snapshot.get().asFile)
        val src = sourceDir.get().asFile
        val problems = mutableListOf<String>()
        if (!src.isDirectory) {
            problems += "generated source dir missing: ${src.absolutePath}"
        } else {
            val actual = src.listFiles { _, name -> name.endsWith(".kt") }
                ?.map { it.name }?.toSet() ?: emptySet()
            (expected.keys - actual).sorted().forEach { problems += "missing in source: $it" }
            (actual - expected.keys).sorted().forEach { problems += "unexpected in source: $it" }
            for (name in expected.keys.intersect(actual)) {
                val expectedBytes = expected.getValue(name).toByteArray(Charsets.UTF_8)
                if (!expectedBytes.contentEquals(File(src, name).readBytes())) {
                    problems += "content drift: $name"
                }
            }
        }
        if (problems.isNotEmpty()) {
            throw GradleException(
                "Wire-DTO drift detected against $SOURCE_LABEL:\n" +
                    problems.joinToString("\n") { "  - $it" } +
                    "\nRun :core:network:generateWireDtos and copy build/wiregen/generated into " +
                    "src/main/kotlin/$WIRE_PACKAGE_PATH.",
            )
        }
    }
}

private const val SOURCE_LABEL = "contracts/client-openapi-v1.json"
private const val WIRE_PACKAGE_PATH = "com/smartnotebook/core/network/wire/generated"
