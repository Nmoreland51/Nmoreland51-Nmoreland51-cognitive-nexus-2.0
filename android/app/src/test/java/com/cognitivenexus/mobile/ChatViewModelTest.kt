package com.cognitivenexus.mobile

import com.cognitivenexus.mobile.data.repository.ChatRepository
import com.cognitivenexus.mobile.viewmodel.ChatViewModel
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun sendMessage_appendsAssistantReply() = runTest {
        val repo = mockk<ChatRepository>()
        coEvery { repo.sendMessage(any(), any(), any(), any()) } returns Result.success("conv_1" to "hello from backend")
        val vm = ChatViewModel(repo)

        vm.sendMessage("hi")
        dispatcher.scheduler.advanceUntilIdle()

        assertTrue(vm.state.value.messages.any { it.contains("Assistant: hello from backend") })
    }
}
