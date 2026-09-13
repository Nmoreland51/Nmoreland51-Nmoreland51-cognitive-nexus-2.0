package com.cognitivenexus.mobile.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cognitivenexus.mobile.data.remote.ConversationSummary
import com.cognitivenexus.mobile.data.repository.ChatRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class ChatUiState(
    val isLoading: Boolean = false,
    val conversationId: String? = null,
    val messages: List<String> = emptyList(),
    val conversations: List<ConversationSummary> = emptyList(),
    val error: String? = null,
    val providerModelInfo: String = "",
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val repository: ChatRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    val userId = "android_user"
    val deviceId = "android_device"

    fun sendMessage(message: String) {
        if (message.isBlank()) return
        _state.value = _state.value.copy(isLoading = true, error = null, messages = _state.value.messages + "You: $message")
        viewModelScope.launch {
            val result = repository.sendMessage(message, _state.value.conversationId, userId, deviceId)
            result.onSuccess { (conversationId, reply) ->
                _state.value = _state.value.copy(
                    isLoading = false,
                    conversationId = conversationId,
                    messages = _state.value.messages + "Assistant: $reply",
                    providerModelInfo = "Provider/model info is returned by /api/v1/chat metadata",
                )
            }.onFailure {
                _state.value = _state.value.copy(isLoading = false, error = it.message ?: "Request failed")
            }
        }
    }

    fun refreshConversations() {
        viewModelScope.launch {
            repository.loadConversations(userId, deviceId)
                .onSuccess { rows -> _state.value = _state.value.copy(conversations = rows, error = null) }
                .onFailure { err -> _state.value = _state.value.copy(error = err.message ?: "Failed to load conversations") }
        }
    }
}
