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
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.cognitivenexus.mobile.viewmodel.SettingsUiState

@Composable
fun SettingsScreen(
    backendUrl: String,
    state: SettingsUiState,
    onSaveBackend: (String) -> Unit,
    onSetWebSearch: (Boolean) -> Unit,
    onSetLearning: (Boolean) -> Unit,
    onSetGrounding: (Boolean) -> Unit,
    onClearCache: () -> Unit,
) {
    var draftUrl by remember(backendUrl) { mutableStateOf(backendUrl) }
    var confirmClear by remember { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        Text("Default emulator URL: http://10.0.2.2:8001/")
        Text("Use LAN IP for physical devices; require HTTPS in production.")
        OutlinedTextField(value = draftUrl, onValueChange = { draftUrl = it }, modifier = Modifier.fillMaxWidth(), label = { Text("Backend URL") })
        Button(onClick = { onSaveBackend(draftUrl) }) { Text("Save backend URL") }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Web search")
            Switch(checked = state.webSearchToggle, onCheckedChange = onSetWebSearch)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Learning")
            Switch(checked = state.learningToggle, onCheckedChange = onSetLearning)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Grounding")
            Switch(checked = state.groundingToggle, onCheckedChange = onSetGrounding)
        }

        Button(onClick = { confirmClear = true }) { Text("Clear Android cache") }
        Text(state.status)
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            confirmButton = { Button(onClick = { onClearCache(); confirmClear = false }) { Text("Confirm") } },
            dismissButton = { Button(onClick = { confirmClear = false }) { Text("Cancel") } },
            title = { Text("Clear local Android cache?") },
            text = { Text("This only clears Room cache on device.") },
        )
    }
}
