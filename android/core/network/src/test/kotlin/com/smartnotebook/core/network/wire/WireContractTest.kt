package com.smartnotebook.core.network.wire

import com.google.common.truth.Truth.assertThat
import com.smartnotebook.core.network.wire.generated.AudioAckResponse
import com.smartnotebook.core.network.wire.generated.AudioDiagnosticResponse
import com.smartnotebook.core.network.wire.generated.CapabilitiesResponse
import com.smartnotebook.core.network.wire.generated.CaptureResponse
import com.smartnotebook.core.network.wire.generated.ChatSSEEvent
import com.smartnotebook.core.network.wire.generated.ClientSessionResponse
import com.smartnotebook.core.network.wire.generated.ClientSessionResponseState
import com.smartnotebook.core.network.wire.generated.ConversationCreatedResponse
import com.smartnotebook.core.network.wire.generated.ConversationDetailResponse
import com.smartnotebook.core.network.wire.generated.ConversationListResponse
import com.smartnotebook.core.network.wire.generated.DashboardEntityResponse
import com.smartnotebook.core.network.wire.generated.DashboardResponse
import com.smartnotebook.core.network.wire.generated.DashboardResponseMode
import com.smartnotebook.core.network.wire.generated.DashboardSSEEvent
import com.smartnotebook.core.network.wire.generated.ErrorResponse
import com.smartnotebook.core.network.wire.generated.ErrorResponseRetryClass
import com.smartnotebook.core.network.wire.generated.FinishResponse
import com.smartnotebook.core.network.wire.generated.FinishResponseCompletionStatus
import com.smartnotebook.core.network.wire.generated.HealthResponse
import com.smartnotebook.core.network.wire.generated.KnowledgeChange
import com.smartnotebook.core.network.wire.generated.KnowledgeChangeOperation
import com.smartnotebook.core.network.wire.generated.KnowledgeDeltaResponse
import com.smartnotebook.core.network.wire.generated.KnowledgeEntityResponse
import com.smartnotebook.core.network.wire.generated.KnowledgeSnapshotResponse
import com.smartnotebook.core.network.wire.generated.LibrariesResponse
import com.smartnotebook.core.network.wire.generated.ProcessingSummaryCompletionStatus
import com.smartnotebook.core.network.wire.generated.PushRegistration
import com.smartnotebook.core.network.wire.generated.PushRegistrationCreateResponse
import com.smartnotebook.core.network.wire.generated.PushRegistrationListResponse
import com.smartnotebook.core.network.wire.generated.ReconciliationResponse
import com.smartnotebook.core.network.wire.generated.ReconciliationResponseState
import com.smartnotebook.core.network.wire.generated.TurnResponse
import com.smartnotebook.core.network.wire.generated.UsageResponse
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.serializer
import org.junit.Assert.assertThrows
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths

private val contractsDir: Path =
    Paths.get(
        requireNotNull(System.getProperty("contractsDir")) {
            "System property 'contractsDir' is not set"
        },
    )

private val fixtures: JsonObject =
    WireJson
        .parseToJsonElement(
            String(Files.readAllBytes(contractsDir.resolve("client-reference-fixtures-v1.json")), Charsets.UTF_8),
        ).jsonObject

private val exampleDecoders: Map<String, DeserializationStrategy<Any>> =
    mapOf(
        "AudioAckResponse" to AudioAckResponse.serializer(),
        "AudioDiagnosticResponse" to AudioDiagnosticResponse.serializer(),
        "CapabilitiesResponse" to CapabilitiesResponse.serializer(),
        "CaptureResponse" to CaptureResponse.serializer(),
        "ChatSSEEvent" to ChatSSEEvent.serializer(),
        "ClientSessionResponse" to ClientSessionResponse.serializer(),
        "ConversationCreatedResponse" to ConversationCreatedResponse.serializer(),
        "ConversationDetailResponse" to ConversationDetailResponse.serializer(),
        "ConversationListResponse" to ConversationListResponse.serializer(),
        "DashboardEntityResponse" to DashboardEntityResponse.serializer(),
        "DashboardResponse" to DashboardResponse.serializer(),
        "DashboardSSEEvent" to DashboardSSEEvent.serializer(),
        "FinishResponse" to FinishResponse.serializer(),
        "HealthResponse" to HealthResponse.serializer(),
        "KnowledgeDeltaResponse" to KnowledgeDeltaResponse.serializer(),
        "KnowledgeEntityResponse" to KnowledgeEntityResponse.serializer(),
        "KnowledgeSnapshotResponse" to KnowledgeSnapshotResponse.serializer(),
        "LibrariesResponse" to LibrariesResponse.serializer(),
        "PushRegistration" to PushRegistration.serializer(),
        "PushRegistrationCreateResponse" to PushRegistrationCreateResponse.serializer(),
        "PushRegistrationListResponse" to PushRegistrationListResponse.serializer(),
        "ReconciliationResponse" to ReconciliationResponse.serializer(),
        "SessionListResponse" to serializer<List<ClientSessionResponse>>(),
        "TurnResponse" to TurnResponse.serializer(),
        "UsageResponse" to UsageResponse.serializer(),
    )

class WireContractTest {
    @Test
    fun contractVersionMatchesWireConstant() {
        assertThat(fixtures.getValue("contract_version").jsonPrimitive.content)
            .isEqualTo(WIRE_CONTRACT_VERSION)
    }

    @Test
    fun responseExamplesDecodeWithGeneratedDtos() {
        val examples = fixtures.getValue("response_examples").jsonObject
        assertThat(examples.keys).containsExactlyElementsIn(exampleDecoders.keys)
        for ((name, strategy) in exampleDecoders) {
            val decoded: Any = WireJson.decodeFromString(strategy, examples.getValue(name).toString())
            assertThat(decoded).isNotNull()
        }
    }

    @Test
    fun errorFixtureDecodes() {
        val error: ErrorResponse = decodeWire(fixtures.getValue("error"))
        assertThat(error.code).isEqualTo("SESSION_STATE_CONFLICT")
        assertThat(error.retryClass).isEqualTo(ErrorResponseRetryClass.USER_ACTION)
        assertThat(error.requestId).isNotEmpty()
    }

    @Test
    fun audioAckFixtureDecodes() {
        val ack: AudioAckResponse = decodeWire(fixtures.getValue("audio_ack"))
        assertThat(ack.chunk.sequence).isEqualTo(1L)
        assertThat(ack.durableAck).isTrue()
    }

    @Test
    fun reconciliationFixtureHasExpectedShape() {
        val raw = fixtures.getValue("reconciliation").jsonObject
        val state =
            WireJson.decodeFromString(
                ReconciliationResponseState.serializer(),
                raw.getValue("state").toString(),
            )
        assertThat(state).isEqualTo(ReconciliationResponseState.DRAINING)
        assertThat(raw.getValue("expected_final_sequence").jsonPrimitive.long).isEqualTo(3L)
        assertThat(raw.getValue("upload_complete").jsonPrimitive.boolean).isFalse()
        assertThat(raw.getValue("conflicts").jsonArray).isEmpty()
        val chunks = raw.getValue("chunks").jsonArray
        assertThat(chunks).hasSize(2)
        chunks.forEach { chunk ->
            assertThat(
                chunk.jsonObject
                    .getValue("sequence")
                    .jsonPrimitive.long,
            ).isGreaterThan(0L)
        }
    }

    @Test
    fun dashboardFixtureDecodes() {
        val dashboard: DashboardResponse = decodeWire(fixtures.getValue("dashboard"))
        assertThat(dashboard.mode).isEqualTo(DashboardResponseMode.IDLE)
        assertThat(dashboard.schemaVersion).isEqualTo(WIRE_CONTRACT_VERSION)
        assertThat(dashboard.revision).isEqualTo(1L)
        assertThat(dashboard.sections).hasSize(3)
    }

    @Test
    fun knowledgeChangeFixturesDecode() {
        val changes = decodeWireList<KnowledgeChange>(fixtures.getValue("knowledge_changes"))
        assertThat(changes).hasSize(3)
        assertThat(changes.map { it.operation })
            .containsExactly(
                KnowledgeChangeOperation.UPSERT,
                KnowledgeChangeOperation.DELETE,
                KnowledgeChangeOperation.REDIRECT,
            ).inOrder()
        changes.forEach { assertThat(it.entity).isNotEmpty() }
    }

    @Test
    fun chatEventSseFixturesHaveExpectedShape() {
        val events = fixtures.getValue("chat_events").jsonArray
        assertThat(events).hasSize(5)
        assertThat(
            events.map {
                it.jsonObject
                    .getValue("type")
                    .jsonPrimitive.content
            },
        ).containsExactly("started", "delta", "citation", "action", "completed")
            .inOrder()
        events.forEach { event ->
            val eventObject = event.jsonObject
            assertThat(eventObject.getValue("sequence").jsonPrimitive.long).isGreaterThan(0L)
            assertThat(eventObject.getValue("payload").jsonObject).isNotNull()
        }
    }

    @Test
    fun stateFixturesDecodeAsEnums() {
        for (raw in fixtures.getValue("session_states").jsonArray) {
            val state =
                WireJson.decodeFromString(
                    ClientSessionResponseState.serializer(),
                    raw.toString(),
                )
            assertThat(state.name).isNotEmpty()
        }
        for (raw in fixtures.getValue("completion_states").jsonArray) {
            val finish =
                WireJson.decodeFromString(
                    FinishResponseCompletionStatus.serializer(),
                    raw.toString(),
                )
            val processing =
                WireJson.decodeFromString(
                    ProcessingSummaryCompletionStatus.serializer(),
                    raw.toString(),
                )
            assertThat(finish.name).isEqualTo(processing.name)
        }
        assertThat(fixtures.getValue("dashboard_component_types").jsonArray).hasSize(12)
        assertThat(fixtures.getValue("dashboard_actions").jsonArray).hasSize(9)
    }

    @Test
    fun retentionFixtureHasExpectedKeys() {
        val retention = fixtures.getValue("retention").jsonObject
        assertThat(retention.keys).containsExactly(
            "server_raw_audio_days",
            "local_dashboard_hours",
            "local_chat_hours",
            "server_ephemeral_chat_hours",
            "server_technical_log_hours",
        )
        retention.values.forEach { assertThat(it.jsonPrimitive.long).isGreaterThan(0L) }
    }

    @Test
    fun unknownEnumValueFallsBackToUnknown() {
        val raw =
            fixtures
                .getValue("error")
                .jsonObject
                .replaced("retry_class" to JsonPrimitive("bogus_retry"))
        val error = WireJson.decodeFromString(ErrorResponse.serializer(), raw.toString())
        assertThat(error.retryClass).isEqualTo(ErrorResponseRetryClass.UNKNOWN)
    }

    @Test
    fun missingRequiredFieldIsRejected() {
        val raw = fixtures.getValue("audio_ack").jsonObject.without("client_session_id")
        assertThrows(SerializationException::class.java) {
            WireJson.decodeFromString(AudioAckResponse.serializer(), raw.toString())
        }
    }

    @Test
    fun unknownExtraKeyIsIgnored() {
        val raw =
            fixtures
                .getValue("audio_ack")
                .jsonObject
                .replaced("future_field" to JsonObject(mapOf("hint" to JsonPrimitive("ignored"))))
        val ack = WireJson.decodeFromString(AudioAckResponse.serializer(), raw.toString())
        assertThat(ack.chunk.sequence).isEqualTo(1L)
    }

    @Test
    fun wrongJsonTypeIsRejected() {
        val raw =
            fixtures
                .getValue("dashboard")
                .jsonObject
                .replaced("schema_version" to JsonPrimitive(1))
        assertThrows(SerializationException::class.java) {
            WireJson.decodeFromString(DashboardResponse.serializer(), raw.toString())
        }
    }
}

private inline fun <reified T> decodeWire(element: JsonElement): T =
    WireJson.decodeFromString(serializer(), element.toString())

private inline fun <reified T> decodeWireList(element: JsonElement): List<T> =
    WireJson.decodeFromString(serializer<List<T>>(), element.toString())

private fun JsonObject.replaced(vararg pairs: Pair<String, JsonElement>): JsonObject =
    JsonObject(toMutableMap().apply { pairs.forEach { (key, value) -> put(key, value) } })

private fun JsonObject.without(key: String): JsonObject = JsonObject(toMutableMap().apply { remove(key) })
