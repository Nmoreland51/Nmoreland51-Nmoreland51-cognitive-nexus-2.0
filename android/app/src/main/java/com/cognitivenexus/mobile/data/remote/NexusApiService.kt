package com.cognitivenexus.mobile.data.remote

import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface NexusApiService {
    @POST("api/v1/chat")
    suspend fun chat(@Body request: ChatRequest): ChatResponse

    @GET("api/v1/conversations")
    suspend fun conversations(
        @Query("user_id") userId: String,
        @Query("device_id") deviceId: String,
    ): List<ConversationSummary>

    @GET("api/v1/conversations/{conversationId}")
    suspend fun conversation(
        @Path("conversationId") conversationId: String,
        @Query("user_id") userId: String,
        @Query("device_id") deviceId: String,
    ): ConversationDetail

    @DELETE("api/v1/conversations/{conversationId}")
    suspend fun deleteConversation(
        @Path("conversationId") conversationId: String,
        @Query("user_id") userId: String,
        @Query("device_id") deviceId: String,
    )

    @POST("api/v1/research")
    suspend fun research(@Body request: ResearchRequest): ResearchResponse

    @GET("api/v1/research/history")
    suspend fun researchHistory(): List<Map<String, kotlinx.serialization.json.JsonElement>>

    @POST("api/v1/images/generate")
    suspend fun generateImage(@Body request: ImageRequest): ImageResponse

    @GET("api/v1/images/history")
    suspend fun imageHistory(): List<Map<String, kotlinx.serialization.json.JsonElement>>

    @DELETE("api/v1/images/{imageId}")
    suspend fun deleteImage(@Path("imageId") imageId: String)

    @GET("api/v1/memory")
    suspend fun memoryOverview(): Map<String, kotlinx.serialization.json.JsonElement>

    @POST("api/v1/memory/facts")
    suspend fun remember(@Body request: MemoryFactRequest): MemoryActionResponse

    @POST("api/v1/memory/forget")
    suspend fun forget(@Body request: MemoryForgetRequest): MemoryActionResponse

    @DELETE("api/v1/memory/all")
    suspend fun clearMemory(): MemoryActionResponse

    @GET("api/v1/providers")
    suspend fun providers(): Map<String, kotlinx.serialization.json.JsonElement>

    @GET("api/v1/settings")
    suspend fun settings(): Map<String, kotlinx.serialization.json.JsonElement>
}
