package com.cognitivenexus.mobile

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.cognitivenexus.mobile.ui.screen.ChatScreen
import com.cognitivenexus.mobile.viewmodel.ChatUiState
import org.junit.Rule
import org.junit.Test

class ChatScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun chatScreen_rendersCoreControls() {
        composeRule.setContent {
            ChatScreen(state = ChatUiState(), onSend = {}, onRefresh = {})
        }
        composeRule.onNodeWithText("Chat").assertIsDisplayed()
        composeRule.onNodeWithText("Send").assertIsDisplayed()
    }
}
