package com.cognitivenexus.mobile

import com.cognitivenexus.mobile.data.local.ChatDao
import com.cognitivenexus.mobile.data.remote.ChatResponse
import com.cognitivenexus.mobile.data.remote.NexusApiService
import com.cognitivenexus.mobile.data.repository.ApiClientFactory
import com.cognitivenexus.mobile.data.repository.BackendUrlStore
import com.cognitivenexus.mobile.data.repository.ChatRepository
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.serialization.json.buildJsonObject
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ChatRepositoryTest {
    @Test
    fun sendMessage_callsApiAndCachesResponse() = runTest {
        val store = mockk<BackendUrlStore>()
        val factory = mockk<ApiClientFactory>()
        val dao = mockk<ChatDao>(relaxed = true)
        val api = mockk<NexusApiService>()

        every { store.backendUrl } returns flowOf("http://10.0.2.2:8001/")
        every { factory.create(any()) } returns api
        coEvery { api.chat(any()) } returns ChatResponse("conv_1", "msg_1", "hi", buildJsonObject { })

        val repo = ChatRepository(store, factory, dao)
        val result = repo.sendMessage("hello", null, "u", "d")

        assertTrue(result.isSuccess)
        coVerify { dao.upsertMessage(any()) }
    }
}
