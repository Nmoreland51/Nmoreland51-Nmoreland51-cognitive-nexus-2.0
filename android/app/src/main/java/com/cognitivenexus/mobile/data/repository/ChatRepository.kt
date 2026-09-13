package com.cognitivenexus.mobile.data.repository

import com.cognitivenexus.mobile.data.local.ChatDao
import com.cognitivenexus.mobile.data.local.ChatMessageEntity
import com.cognitivenexus.mobile.data.remote.ChatRequest
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first

@Singleton
class ChatRepository @Inject constructor(
    private val backendUrlStore: BackendUrlStore,
    private val apiClientFactory: ApiClientFactory,
    private val chatDao: ChatDao,
) {
    suspend fun sendMessage(message: String, conversationId: String?, userId: String, deviceId: String): Result<Pair<String, String>> {
        return runCatching {
            val baseUrl = backendUrlStore.backendUrl.first()
            val api = apiClientFactory.create(baseUrl)
            val response = api.chat(
                ChatRequest(
                    message = message,
                    conversationId = conversationId,
                    userId = userId,
                    deviceId = deviceId,
                )
            )
            chatDao.upsertMessage(
                ChatMessageEntity(
                    id = response.userMessageId,
                    conversationId = response.conversationId,
                    role = "user",
                    content = message,
                    createdAt = System.currentTimeMillis(),
                )
            )
            chatDao.upsertMessage(
                ChatMessageEntity(
                    id = response.messageId,
                    conversationId = response.conversationId,
                    role = "assistant",
                    content = response.assistantReply,
                    createdAt = System.currentTimeMillis(),
                )
            )
            response.conversationId to response.assistantReply
        }
    }

    suspend fun loadConversations(userId: String, deviceId: String): Result<List<com.cognitivenexus.mobile.data.remote.ConversationSummary>> =
        runCatching {
            val api = apiClientFactory.create(backendUrlStore.backendUrl.first())
            api.conversations(userId = userId, deviceId = deviceId)
        }

    suspend fun clearLocalCache() {
        chatDao.clearAll()
    }
}
