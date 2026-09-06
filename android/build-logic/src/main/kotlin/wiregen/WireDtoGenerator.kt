package com.smartnotebook.buildlogic.wiregen

import java.io.File
import java.security.MessageDigest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject

private val JsonElement.stringValue: String
    get() {
        val primitive = this as? JsonPrimitive
        require(primitive != null && primitive.isString) { "Expected JSON string, got: $this" }
        return primitive.content
    }

const val WIRE_PACKAGE = "com.smartnotebook.core.network.wire.generated"

object WireDtoGenerator {

    private const val EXPECTED_CONTRACT_VERSION = "1"
    private const val GENERATOR_VERSION = "1"
    private const val SOURCE_LABEL = "contracts/client-openapi-v1.json"

    private val parser = Json { ignoreUnknownKeys = true }

    fun generate(snapshot: File): Map<String, String> {
        require(snapshot.isFile) { "OpenAPI snapshot not found: ${snapshot.absolutePath}" }
        val root = parser.parseToJsonElement(snapshot.readText(Charsets.UTF_8)).jsonObject
        val version = root["info"]?.jsonObject?.get("version")?.stringValue
            ?: error("OpenAPI snapshot lacks info.version")
        require(version == EXPECTED_CONTRACT_VERSION) {
            "Unsupported OpenAPI contract version '$version' (expected '$EXPECTED_CONTRACT_VERSION')."
        }
        val schemas = root["components"]?.jsonObject?.get("schemas")?.jsonObject
            ?: error("OpenAPI snapshot lacks components.schemas")
        require(schemas.isNotEmpty()) { "OpenAPI snapshot has no component schemas" }

        val sha256 = sha256Hex(snapshot.readBytes())
        val files = LinkedHashMap<String, String>()

        val enums = LinkedHashMap<String, List<String>>()
        for ((schemaName, schemaElement) in schemas) {
            val props = schemaElement.jsonObject["properties"]?.jsonObject ?: continue
            for ((propName, propElement) in props) {
                val info = mapSchema(propElement.jsonObject, schemaName, propName)
                if (info.enumValues != null) {
                    require(!enums.containsKey(info.kotlinType)) {
                        "Enum name collision: ${info.kotlinType}"
                    }
                    enums[info.kotlinType] = info.enumValues!!
                }
            }
        }
        for ((className, values) in enums) {
            putFile(files, "$className.kt", enumFile(header(sha256), className, values))
        }

        for ((schemaName, schemaElement) in schemas) {
            val schema = schemaElement.jsonObject
            val type = schema["type"]?.stringValue
            val props = schema["properties"]?.jsonObject
            when {
                type == "array" && props == null -> {
                    val items = schema["items"]?.jsonObject
                        ?: error("Top-level array schema $schemaName lacks items")
                    val item = mapSchema(items, schemaName, "items")
                    val imports = if (item.kotlinType.contains("JsonElement")) {
                        "import kotlinx.serialization.json.JsonElement\n\n"
                    } else {
                        ""
                    }
                    putFile(
                        files,
                        "$schemaName.kt",
                        header(sha256) + imports +
                            "public typealias $schemaName = List<${item.kotlinType}>\n",
                    )
                }

                type == "object" && props == null -> {
                    putFile(
                        files,
                        "$schemaName.kt",
                        header(sha256) +
                            "import kotlinx.serialization.json.JsonElement\n\n" +
                            "public typealias $schemaName = Map<String, JsonElement>\n",
                    )
                }

                props != null -> {
                    putFile(files, "$schemaName.kt", dataClassFile(header(sha256), schemaName, schema))
                }

                else -> error("Unsupported top-level schema $schemaName: $schema")
            }
        }
        return files
    }

    private fun putFile(files: LinkedHashMap<String, String>, name: String, content: String) {
        require(!files.containsKey(name)) { "Generated file collision: $name" }
        files[name] = content
    }

    private fun header(sha256: String): String = buildString {
        appendLine("// GENERATED - DO NOT EDIT")
        appendLine("// Source: $SOURCE_LABEL (sha256:$sha256)")
        appendLine("// Generator: wiregen v$GENERATOR_VERSION (contract v$EXPECTED_CONTRACT_VERSION)")
        appendLine()
        appendLine("package $WIRE_PACKAGE")
    }

    private fun dataClassFile(header: String, schemaName: String, schema: JsonObject): String {
        val props = schema["properties"]!!.jsonObject
        val required = (schema["required"]?.jsonArray ?: emptyList<JsonElement>())
            .map { it.stringValue }.toSet()
        val fields = LinkedHashMap<String, Field>()
        for ((propName, propElement) in props) {
            val info = mapSchema(propElement.jsonObject, schemaName, propName)
            val kotlinName = snakeToCamel(propName)
            val declaredType = if (info.nullable || propName !in required) {
                "${info.kotlinType}?"
            } else {
                info.kotlinType
            }
            val default = if (propName in required) "" else " = null"
            fields[propName] = Field(propName, kotlinName, declaredType, default)
        }
        val entries = fields.values.toList()
        val imports = buildString {
            if (entries.any { it.type.contains("Instant") }) appendLine("import java.time.Instant")
            if (entries.any { it.type.contains("UUID") }) appendLine("import java.util.UUID")
            if (entries.any { it.usesContextual }) {
                appendLine("import kotlinx.serialization.Contextual")
            }
            if (entries.any { it.kotlinName != it.wireName }) appendLine("import kotlinx.serialization.SerialName")
            appendLine("import kotlinx.serialization.Serializable")
            if (entries.any { it.type.contains("JsonElement") }) {
                appendLine("import kotlinx.serialization.json.JsonElement")
            }
        }
        val body = buildString {
            appendLine("@Serializable")
            appendLine("public data class $schemaName(")
            entries.forEachIndexed { index, field ->
                val comma = if (index < entries.lastIndex) "," else ""
                if (field.usesContextual) {
                    appendLine("    @Contextual")
                }
                if (field.kotlinName != field.wireName) {
                    appendLine("    @SerialName(\"${field.wireName}\")")
                }
                appendLine("    val ${field.kotlinName}: ${field.type}${field.default}$comma")
            }
            append(")\n")
        }
        return header + imports + "\n" + body
    }

    private fun enumFile(header: String, className: String, values: List<String>): String {
        val serializerName = "${className}Serializer"
        val body = buildString {
            appendLine("@Serializable(with = $serializerName::class)")
            appendLine("public enum class $className {")
            values.forEach { value ->
                appendLine("    ${constantName(value)},")
            }
            appendLine("    UNKNOWN;")
            appendLine()
            appendLine("    public val wireValue: String")
            appendLine("        get() = when (this) {")
            values.forEach { value ->
                appendLine("            ${constantName(value)} -> \"$value\"")
            }
            appendLine("            UNKNOWN -> \"unknown\"")
            appendLine("        }")
            appendLine("}")
            appendLine()
            appendLine("public object $serializerName : KSerializer<$className> {")
            appendLine("    override val descriptor: SerialDescriptor =")
            appendLine("        PrimitiveSerialDescriptor(\"$className\", PrimitiveKind.STRING)")
            appendLine()
            appendLine("    override fun serialize(encoder: Encoder, value: $className) {")
            appendLine("        encoder.encodeString(value.wireValue)")
            appendLine("    }")
            appendLine()
            appendLine("    override fun deserialize(decoder: Decoder): $className {")
            appendLine("        val raw = decoder.decodeString()")
            appendLine("        return $className.entries.firstOrNull { it.wireValue == raw } ?: $className.UNKNOWN")
            appendLine("    }")
            appendLine("}")
            appendLine()
        }
        return header +
            "import kotlinx.serialization.KSerializer\n" +
            "import kotlinx.serialization.Serializable\n" +
            "import kotlinx.serialization.descriptors.PrimitiveKind\n" +
            "import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor\n" +
            "import kotlinx.serialization.descriptors.SerialDescriptor\n" +
            "import kotlinx.serialization.encoding.Decoder\n" +
            "import kotlinx.serialization.encoding.Encoder\n" +
            "\n" +
            body
    }

    private fun constantName(value: String): String =
        value.uppercase().replace(Regex("[^A-Z0-9]+"), "_").trim('_').ifEmpty { "VALUE" }

    private data class SchemaInfo(
        val nullable: Boolean,
        val kotlinType: String,
        val enumValues: List<String>?,
    )

    private data class Field(
        val wireName: String,
        val kotlinName: String,
        val type: String,
        val default: String,
    ) {
        val usesContextual: Boolean
            get() = type.contains("UUID") || type.contains("Instant")
    }

    private fun mapSchema(raw: JsonObject, schemaName: String, propName: String): SchemaInfo {
        val ctx = "$schemaName.$propName"
        raw["anyOf"]?.let { anyOf ->
            val branches = anyOf.jsonArray.map { it.jsonObject }
            val nonNull = branches.filter { it["type"]?.stringValue != "null" }
            require(nonNull.size == 1) { "Unsupported anyOf at $ctx: $anyOf" }
            return mapSchema(nonNull.single(), schemaName, propName).copy(nullable = true)
        }
        raw["${'$'}ref"]?.let { ref ->
            return SchemaInfo(false, ref.stringValue.substringAfterLast('/'), null)
        }
        val type = raw["type"]?.stringValue ?: error("Unsupported schema at $ctx: $raw")
        return when (type) {
            "string" -> when {
                raw["format"]?.stringValue == "uuid" -> SchemaInfo(false, "UUID", null)
                raw["format"]?.stringValue == "date-time" -> SchemaInfo(false, "Instant", null)
                raw["enum"] != null -> {
                    val values = raw["enum"]!!.jsonArray.map { it.stringValue }
                    require(values.all { it.isNotEmpty() }) { "Empty enum value at $ctx" }
                    SchemaInfo(false, enumClassName(schemaName, propName), values)
                }

                else -> SchemaInfo(false, "String", null)
            }

            "integer" -> SchemaInfo(false, "Long", null)
            "number" -> SchemaInfo(false, "Double", null)
            "boolean" -> SchemaInfo(false, "Boolean", null)
            "array" -> {
                val items = raw["items"]?.jsonObject ?: error("Array without items at $ctx")
                val item = mapSchema(items, schemaName, propName)
                require(item.enumValues == null) { "Enum array items not supported at $ctx" }
                SchemaInfo(false, "List<${item.kotlinType}>", null)
            }

            "object" -> {
                require(!raw.containsKey("properties")) { "Inline object with properties at $ctx" }
                SchemaInfo(false, "Map<String, JsonElement>", null)
            }

            else -> error("Unsupported type '$type' at $ctx")
        }
    }

    private fun enumClassName(schemaName: String, propName: String): String =
        pascal(schemaName) + pascal(propName)

    private fun pascal(name: String): String =
        name.split('_').filter { it.isNotEmpty() }
            .joinToString("") { it.replaceFirstChar { c -> c.uppercase() } }

    private fun snakeToCamel(name: String): String {
        val parts = name.split('_').filter { it.isNotEmpty() }
        return buildString {
            parts.firstOrNull()?.let { append(it.lowercase()) }
            parts.drop(1).forEach { append(it.replaceFirstChar { c -> c.uppercase() }) }
        }
    }

    private fun sha256Hex(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return digest.joinToString("") { "%02x".format(it) }
    }
}
