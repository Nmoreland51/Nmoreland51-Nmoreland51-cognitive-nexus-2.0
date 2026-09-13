package com.cognitivenexus.mobile.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cognitivenexus.mobile.data.repository.ImageRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class ImageUiState(
    val loading: Boolean = false,
    val status: String = "",
    val history: List<String> = emptyList(),
    val error: String? = null,
)

@HiltViewModel
class ImageViewModel @Inject constructor(
    private val repository: ImageRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(ImageUiState())
    val state: StateFlow<ImageUiState> = _state.asStateFlow()

    fun generate(prompt: String, mode: String) {
        _state.value = _state.value.copy(loading = true, error = null)
        viewModelScope.launch {
            repository.generate(prompt, mode)
                .onSuccess { resp ->
                    val status = if (resp.success) "Generated via ${resp.provider}" else "Unavailable: ${resp.result["error"]}"
                    _state.value = _state.value.copy(loading = false, status = status)
                }
                .onFailure { err -> _state.value = _state.value.copy(loading = false, error = err.message ?: "Image request failed") }
        }
    }

    fun loadHistory() {
        viewModelScope.launch {
            repository.history()
                .onSuccess { rows -> _state.value = _state.value.copy(history = rows.map { it.toString() }, error = null) }
                .onFailure { err -> _state.value = _state.value.copy(error = err.message ?: "Image history failed") }
        }
    }
}
