package com.cognitivenexus.mobile.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
import com.cognitivenexus.mobile.viewmodel.MemoryUiState

@Composable
fun MemoryScreen(
    state: MemoryUiState,
    onLoad: () -> Unit,
    onRemember: (String) -> Unit,
    onForget: (String) -> Unit,
    onClear: () -> Unit,
) {
    var rememberText by remember { mutableStateOf("") }
    var forgetText by remember { mutableStateOf("") }
    var confirmClear by remember { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Memory", style = MaterialTheme.typography.headlineSmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onLoad) { Text("Load") }
            Button(onClick = { confirmClear = true }) { Text("Clear all") }
        }
        OutlinedTextField(value = rememberText, onValueChange = { rememberText = it }, modifier = Modifier.fillMaxWidth(), label = { Text("Remember fact") })
        Button(onClick = { onRemember(rememberText) }) { Text("Remember") }
        OutlinedTextField(value = forgetText, onValueChange = { forgetText = it }, modifier = Modifier.fillMaxWidth(), label = { Text("Forget query") })
        Button(onClick = { onForget(forgetText) }) { Text("Forget") }
        state.error?.let { Text("Error: $it") }
        Text("Status: ${state.status}")
        Text("Overview: ${state.overview}")
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            confirmButton = { Button(onClick = { onClear(); confirmClear = false }) { Text("Confirm") } },
            dismissButton = { Button(onClick = { confirmClear = false }) { Text("Cancel") } },
            title = { Text("Clear all memory?") },
            text = { Text("This sends an explicit clear request to the backend.") },
        )
    }
}
