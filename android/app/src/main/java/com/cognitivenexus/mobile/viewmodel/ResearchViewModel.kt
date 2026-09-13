package com.cognitivenexus.mobile.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cognitivenexus.mobile.data.repository.ResearchRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class ResearchUiState(
    val loading: Boolean = false,
    val result: String = "",
    val error: String? = null,
)

@HiltViewModel
class ResearchViewModel @Inject constructor(
    private val repository: ResearchRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(ResearchUiState())
    val state: StateFlow<ResearchUiState> = _state.asStateFlow()

    fun run(query: String) {
        if (query.isBlank()) return
        _state.value = _state.value.copy(loading = true, error = null)
        viewModelScope.launch {
            repository.runResearch(query)
                .onSuccess { summary -> _state.value = ResearchUiState(loading = false, result = summary) }
                .onFailure { err -> _state.value = ResearchUiState(loading = false, error = err.message ?: "Research failed") }
        }
    }
}
