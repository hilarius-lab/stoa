package com.smartnotebook.buildlogic.uitext

import java.io.File

object UiTextScanner {

    private const val ALLOW_MARKER = "ui-text:allow"

    private val textComposablePattern =
        Regex("""\bText\s*\(\s*(?:text\s*=\s*)?\"""")

    private val visibleNamedArgumentPattern =
        Regex(
            """\b(?:text|contentDescription|label|placeholder|hint|title|subtitle|actionLabel|buttonText|dialogTitle|dialogMessage|confirmButtonText|dismissButtonText|snackbarMessage)\s*=\s*\"""",
        )

    private val xmlAttributePattern =
        Regex(
            """android:(?:label|hint|text|contentDescription|title|placeholderText|dialogMessage|dialogTitle|actionBarTitle|summary|confirmButtonText|dismissButtonText)\s*=\s*"([^"]*)"""",
        )

    private val xmlCommentPattern =
        Regex("<!--.*?-->", RegexOption.DOT_MATCHES_ALL)

    private val stringNamePattern =
        Regex("""<string\s+name\s*=\s*"([^"]+)"""")

    fun findSourceViolations(file: File, module: String, sourceRoot: File): List<String> {
        val raw = file.readText(Charsets.UTF_8)
        val code = redactCommentsAndStringContents(raw)
        val rawLines = raw.lines()
        val label = "$module/${file.relativeTo(sourceRoot).invariantSeparatorsPath}"
        val violations = LinkedHashSet<String>()

        listOf(textComposablePattern, visibleNamedArgumentPattern).forEach { pattern ->
            pattern.findAll(code).forEach { match ->
                val line = lineNumberOf(code, match.range.first)
                if (isAllowed(rawLines, line)) {
                    return@forEach
                }
                violations.add(
                    "$label:Zeile $line: hartcodierter sichtbarer UI-Text; " +
                        "nutze stringResource/R.string mit values/ und values-de/",
                )
            }
        }

        return violations.sorted()
    }

    fun findXmlViolations(file: File, module: String, sourceRoot: File): List<String> {
        val code = xmlCommentPattern.replace(file.readText(Charsets.UTF_8), " ")
        val label = "$module/${file.relativeTo(sourceRoot).invariantSeparatorsPath}"
        val violations = LinkedHashSet<String>()

        xmlAttributePattern.findAll(code).forEach { match ->
            val value = match.groupValues[1]
            if (!value.startsWith("@") && !value.startsWith("?")) {
                val line = lineNumberOf(code, match.range.first)
                violations.add(
                    "$label:Zeile $line: hartcodierter sichtbarer UI-Text in android:-Attribut; " +
                        "nutze @string/-Ressource",
                )
            }
        }

        return violations.sorted()
    }

    fun resourceViolations(module: String, resRoot: File): List<String> {
        if (!resRoot.isDirectory) {
            return emptyList()
        }
        val valuesDir = resRoot.resolve("values")
        val valuesDeDir = resRoot.resolve("values-de")
        val englishNames = xmlFiles(valuesDir).flatMap { stringNames(it) }
        val germanNames = xmlFiles(valuesDeDir).flatMap { stringNames(it) }
        if (englishNames.isEmpty() && germanNames.isEmpty()) {
            return emptyList()
        }

        val violations = LinkedHashSet<String>()
        if (!valuesDir.isDirectory) {
            violations.add("$module: values/ fehlt für englische Fallback-Ressourcen")
        }
        if (!valuesDeDir.isDirectory) {
            violations.add("$module: values-de/ fehlt für deutsche Ressourcen")
        }

        englishNames.groupingBy { it }.eachCount()
            .filter { it.value > 1 }
            .keys
            .sorted()
            .forEach { violations.add("$module: doppelte englische Ressourcenangabe: $it") }

        germanNames.groupingBy { it }.eachCount()
            .filter { it.value > 1 }
            .keys
            .sorted()
            .forEach { violations.add("$module: doppelte deutsche Ressourcenangabe: $it") }

        val englishSet = englishNames.toSet()
        val germanSet = germanNames.toSet()

        (englishSet - germanSet).sorted().forEach {
            violations.add("$module: fehlende deutsche Ressource values-de: $it")
        }
        (germanSet - englishSet).sorted().forEach {
            violations.add("$module: fehlende englische Fallback-Ressource values: $it")
        }

        return violations.sorted()
    }

    fun stringNames(file: File): List<String> {
        return stringNamePattern.findAll(file.readText(Charsets.UTF_8))
            .map { it.groupValues[1] }
            .toList()
    }

    fun redactCommentsAndStringContents(code: String): String {
        val result = StringBuilder(code.length)
        var index = 0

        while (index < code.length) {
            when {
                code.startsWith("//", index) -> {
                    while (index < code.length && code[index] != '\n') {
                        result.append(' ')
                        index++
                    }
                }

                code.startsWith("/*", index) -> {
                    result.append("  ")
                    index += 2
                    while (index < code.length && !code.startsWith("*/", index)) {
                        result.append(if (code[index] == '\n') '\n' else ' ')
                        index++
                    }
                    if (index < code.length) {
                        result.append("  ")
                        index += 2
                    }
                }

                code[index] == '"' -> {
                    if (code.startsWith("\"\"\"", index)) {
                        index = skipRawString(code, index, result)
                    } else {
                        index = skipQuotedString(code, index, result, '"')
                    }
                }

                code[index] == '\'' -> {
                    index = skipQuotedString(code, index, result, '\'')
                }

                else -> {
                    result.append(code[index])
                    index++
                }
            }
        }

        return result.toString()
    }

    private fun skipRawString(code: String, start: Int, result: StringBuilder): Int {
        result.append("\"\"")
        var index = start + 3
        while (index < code.length) {
            if (code.startsWith("\"\"\"", index)) {
                return index + 3
            }
            if (code[index] == '\n') {
                result.append('\n')
            }
            index++
        }
        return index
    }

    private fun skipQuotedString(code: String, start: Int, result: StringBuilder, quote: Char): Int {
        result.append(quote.toString() + quote.toString())
        var index = start + 1
        while (index < code.length) {
            val char = code[index]
            when {
                char == '\\' && index + 1 < code.length -> {
                    index += 2
                }

                char == quote -> {
                    return index + 1
                }

                char == '\n' && quote == '"' -> {
                    result.append('\n')
                    index++
                }

                else -> {
                    index++
                }
            }
        }
        return index
    }

    private fun xmlFiles(directory: File): List<File> {
        if (!directory.isDirectory) {
            return emptyList()
        }
        return directory.listFiles { file -> file.isFile && file.extension == "xml" }
            ?.sortedBy { it.name }
            .orEmpty()
    }

    private fun isAllowed(rawLines: List<String>, line: Int): Boolean {
        if (line !in 1..rawLines.size) {
            return false
        }
        return rawLines[line - 1].contains(ALLOW_MARKER) ||
            (line > 1 && rawLines[line - 2].contains(ALLOW_MARKER))
    }

    private fun lineNumberOf(code: String, index: Int): Int {
        var line = 1
        for (i in 0 until minOf(index, code.length)) {
            if (code[i] == '\n') {
                line++
            }
        }
        return line
    }
}
