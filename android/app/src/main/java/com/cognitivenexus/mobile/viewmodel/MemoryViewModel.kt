package com.cognitivenexus.mobile.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cognitivenexus.mobile.data.repository.MemoryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class MemoryUiState(
    val overview: String = "",
    val status: String = "",
    val error: String? = null,
)

@HiltViewModel
class MemoryViewModel @Inject constructor(
    private val repository: MemoryRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(MemoryUiState())
    val state: StateFlow<MemoryUiState> = _state.asStateFlow()

    fun loadOverview() {
        viewModelScope.launch {
            repository.overview()
                .onSuccess { _state.value = _state.value.copy(overview = it.toString(), error = null) }
                .onFailure { _state.value = _state.value.copy(error = it.message ?: "Failed to load memory") }
        }
    }

    fun remember(text: String) {
        viewModelScope.launch {
            repository.remember(text)
                .onSuccess { _state.value = _state.value.copy(status = it.message, error = null) }
                .onFailure { _state.value = _state.value.copy(error = it.message ?: "Remember failed") }
        }
    }

    fun forget(query: String) {
        viewModelScope.launch {
            repository.forget(query)
                .onSuccess { _state.value = _state.value.copy(status = it.message, error = null) }
                .onFailure { _state.value = _state.value.copy(error = it.message ?: "Forget failed") }
        }
    }

    fun clearAll() {
        viewModelScope.launch {
            repository.clearAll()
                .onSuccess { _state.value = _state.value.copy(status = it.message, error = null) }
                .onFailure { _state.value = _state.value.copy(error = it.message ?: "Clear failed") }
        }
    }
}
