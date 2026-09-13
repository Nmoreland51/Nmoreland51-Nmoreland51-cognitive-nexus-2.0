package com.cognitivenexus.mobile.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.cognitivenexus.mobile.viewmodel.ImageUiState

@Composable
fun ImageScreen(state: ImageUiState, onGenerate: (String, String) -> Unit, onLoadHistory: () -> Unit) {
    var prompt by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf("local_private") }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Image Studio", style = MaterialTheme.typography.headlineSmall)
        Text("Modes: local_private, hosted_budget, hosted_premium")
        Text("Privacy: hosted modes send prompt to configured backend provider.")
        OutlinedTextField(value = prompt, onValueChange = { prompt = it }, modifier = Modifier.fillMaxWidth(), label = { Text("Prompt") })
        OutlinedTextField(value = mode, onValueChange = { mode = it }, modifier = Modifier.fillMaxWidth(), label = { Text("Mode") })
        Button(onClick = { onGenerate(prompt, mode) }) { Text("Generate") }
        Button(onClick = onLoadHistory) { Text("Load history") }
        if (state.loading) CircularProgressIndicator()
        state.error?.let { Text("Error: $it") }
        Text(state.status)
        LazyColumn {
            items(state.history) { row -> Text(row) }
        }
    }
}
