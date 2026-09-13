package com.cognitivenexus.mobile.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cognitivenexus.mobile.data.repository.ChatRepository
import com.cognitivenexus.mobile.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class SettingsUiState(
    val status: String = "",
    val webSearchToggle: Boolean = true,
    val learningToggle: Boolean = true,
    val groundingToggle: Boolean = true,
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsRepository: SettingsRepository,
    private val chatRepository: ChatRepository,
) : ViewModel() {
    val backendUrl = settingsRepository.backendUrl.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

    private val _state = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    fun saveBackendUrl(url: String) {
        viewModelScope.launch {
            settingsRepository.setBackendUrl(url)
            _state.value = _state.value.copy(status = "Saved backend URL")
        }
    }

    fun clearCache() {
        viewModelScope.launch {
            chatRepository.clearLocalCache()
            _state.value = _state.value.copy(status = "Android local cache cleared")
        }
    }

    fun setWebSearch(enabled: Boolean) {
        _state.value = _state.value.copy(webSearchToggle = enabled)
    }

    fun setLearning(enabled: Boolean) {
        _state.value = _state.value.copy(learningToggle = enabled)
    }

    fun setGrounding(enabled: Boolean) {
        _state.value = _state.value.copy(groundingToggle = enabled)
    }
}
