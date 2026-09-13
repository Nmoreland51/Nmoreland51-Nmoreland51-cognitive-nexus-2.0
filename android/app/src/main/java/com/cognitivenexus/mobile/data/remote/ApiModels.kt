package com.cognitivenexus.mobile.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ChatRequest(
    val message: String,
    @SerialName("user_id") val userId: String,
    @SerialName("device_id") val deviceId: String,
    @SerialName("conversation_id") val conversationId: String? = null,
)

@Serializable
data class ChatResponse(
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("message_id") val messageId: String,
    @SerialName("user_message_id") val userMessageId: String,
    @SerialName("assistant_reply") val assistantReply: String,
    val metadata: Map<String, kotlinx.serialization.json.JsonElement> = emptyMap(),
)

@Serializable
data class ConversationSummary(
    @SerialName("conversation_id") val conversationId: String,
    val title: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class ConversationDetail(
    @SerialName("conversation_id") val conversationId: String,
    val messages: List<ConversationMessage>
)

@Serializable
data class ConversationMessage(
    @SerialName("message_id") val messageId: String,
    val role: String,
    val content: String,
)

@Serializable
data class ResearchRequest(val query: String)

@Serializable
data class ResearchResponse(val success: Boolean, val report: Map<String, kotlinx.serialization.json.JsonElement>)

@Serializable
data class ImageRequest(
    val prompt: String,
    val mode: String = "local_private"
)

@Serializable
data class ImageResponse(val success: Boolean, val provider: String, val result: Map<String, kotlinx.serialization.json.JsonElement>)

@Serializable
data class MemoryFactRequest(val text: String)

@Serializable
data class MemoryForgetRequest(val query: String)

@Serializable
data class MemoryActionResponse(val success: Boolean, val action: String, val message: String)
