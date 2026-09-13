package com.cognitivenexus.mobile.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import com.cognitivenexus.mobile.viewmodel.ChatUiState

@Composable
fun ChatScreen(state: ChatUiState, onSend: (String) -> Unit, onRefresh: () -> Unit) {
    var input by remember { mutableStateOf("") }
    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Chat", style = MaterialTheme.typography.headlineSmall)
        Text("Conversation ID: ${state.conversationId ?: "(new)"}")
        Text("${state.providerModelInfo}")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onRefresh) { Text("Refresh") }
            Button(onClick = { if (input.isNotBlank()) { onSend(input); input = "" } }) { Text("Send") }
        }
        OutlinedTextField(value = input, onValueChange = { input = it }, label = { Text("Message") }, modifier = Modifier.fillMaxWidth())
        if (state.isLoading) CircularProgressIndicator()
        state.error?.let { Text("Error: $it") }
        LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth()) {
            items(state.messages) { msg -> Text(msg, modifier = Modifier.padding(vertical = 2.dp)) }
        }
        Text("Actions: copy/regenerate/feedback/remember/share are backend-capability dependent.")
    }
}
