package com.smartnotebook.buildlogic.uitext

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class UiTextScannerTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    @Test
    fun detectsHardcodedTextComposable() {
        val file = tempFolder.newFile("Ui.kt")
        file.writeText(
            """
            @Composable
            fun Ui() {
                Text("Hallo")
                Text(text = "Welt")
            }
            """.trimIndent(),
        )

        val violations = UiTextScanner.findSourceViolations(file, ":test", file.parentFile)

        assertEquals(2, violations.size)
    }

    @Test
    fun detectsHardcodedContentDescription() {
        val file = tempFolder.newFile("Ui.kt")
        file.writeText(
            """
            @Composable
            fun Ui() {
                Image(painter, contentDescription = "Logo")
            }
            """.trimIndent(),
        )

        val violations = UiTextScanner.findSourceViolations(file, ":test", file.parentFile)

        assertEquals(1, violations.size)
    }

    @Test
    fun acceptsStringResource() {
        val file = tempFolder.newFile("Ui.kt")
        file.writeText(
            """
            @Composable
            fun Ui() {
                Text(stringResource(R.string.greeting))
                Text(text = stringResource(R.string.greeting))
            }
            """.trimIndent(),
        )

        val violations = UiTextScanner.findSourceViolations(file, ":test", file.parentFile)

        assertTrue(violations.isEmpty())
    }

    @Test
    fun ignoresComments() {
        val file = tempFolder.newFile("Ui.kt")
        file.writeText(
            """
            // Text("Hallo")
            /*
            Text("Welt")
            */
            @Composable
            fun Ui() {
                val value = "Kein sichtbarer UI-Text"
            }
            """.trimIndent(),
        )

        val violations = UiTextScanner.findSourceViolations(file, ":test", file.parentFile)

        assertTrue(violations.isEmpty())
    }

    @Test
    fun ignoresStringContentsThatMentionUiPatterns() {
        val file = tempFolder.newFile("Ui.kt")
        file.writeText(
            "const val Sample = \"\"\"\n" +
                "Text(\"Probe\")\n" +
                "label = \"Probe\"\n" +
                "\"\"\"\n",
        )

        val violations = UiTextScanner.findSourceViolations(file, ":test", file.parentFile)

        assertTrue(violations.isEmpty())
    }

    @Test
    fun honoursAllowMarker() {
        val file = tempFolder.newFile("Ui.kt")
        file.writeText(
            """
            @Composable
            fun Ui() {
                // ui-text:allow
                Text("https")
            }
            """.trimIndent(),
        )

        val violations = UiTextScanner.findSourceViolations(file, ":test", file.parentFile)

        assertTrue(violations.isEmpty())
    }

    @Test
    fun detectsHardcodedXmlAttribute() {
        val file = tempFolder.newFile("AndroidManifest.xml")
        file.writeText(
            """
            <manifest>
                <application android:label="Smart Notebook" />
            </manifest>
            """.trimIndent(),
        )

        val violations = UiTextScanner.findXmlViolations(file, ":test", file.parentFile)

        assertEquals(1, violations.size)
    }

    @Test
    fun acceptsStringReferenceInXml() {
        val file = tempFolder.newFile("AndroidManifest.xml")
        file.writeText(
            """
            <manifest>
                <application android:label="@string/app_name" />
            </manifest>
            """.trimIndent(),
        )

        val violations = UiTextScanner.findXmlViolations(file, ":test", file.parentFile)

        assertTrue(violations.isEmpty())
    }

    @Test
    fun resourceCheckAcceptsParity() {
        val resRoot = tempFolder.newFolder("res")
        writeStrings(resRoot, "values", listOf("greeting", "title"))
        writeStrings(resRoot, "values-de", listOf("greeting", "title"))

        val violations = UiTextScanner.resourceViolations(":test", resRoot)

        assertTrue(violations.isEmpty())
    }

    @Test
    fun resourceCheckDetectsMissingGermanFallback() {
        val resRoot = tempFolder.newFolder("res")
        writeStrings(resRoot, "values", listOf("greeting", "title"))
        writeStrings(resRoot, "values-de", listOf("greeting"))

        val violations = UiTextScanner.resourceViolations(":test", resRoot)

        assertEquals(1, violations.size)
        assertTrue(violations.single().contains("title"))
    }

    @Test
    fun resourceCheckDetectsMissingEnglishFallback() {
        val resRoot = tempFolder.newFolder("res")
        writeStrings(resRoot, "values", listOf("greeting"))
        writeStrings(resRoot, "values-de", listOf("greeting", "title"))

        val violations = UiTextScanner.resourceViolations(":test", resRoot)

        assertEquals(1, violations.size)
        assertTrue(violations.single().contains("title"))
    }

    @Test
    fun resourceCheckIgnoresModulesWithoutStrings() {
        val resRoot = tempFolder.newFolder("res")
        writeStrings(resRoot, "values", emptyList())
        writeStrings(resRoot, "values-de", emptyList())

        val violations = UiTextScanner.resourceViolations(":test", resRoot)

        assertTrue(violations.isEmpty())
    }

    private fun writeStrings(resRoot: File, locale: String, names: List<String>) {
        val localeDir = resRoot.resolve(locale)
        localeDir.mkdirs()
        val body = names.joinToString("\n") { "<string name=\"$it\">value</string>" }
        localeDir.resolve("strings.xml").writeText(
            """
            <?xml version="1.0" encoding="utf-8"?>
            <resources>
            $body
            </resources>
            """.trimIndent(),
        )
    }
}
