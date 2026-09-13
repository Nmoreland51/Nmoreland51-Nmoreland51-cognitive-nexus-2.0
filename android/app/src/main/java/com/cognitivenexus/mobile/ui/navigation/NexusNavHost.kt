package com.cognitivenexus.mobile.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.cognitivenexus.mobile.ui.screen.ChatScreen
import com.cognitivenexus.mobile.ui.screen.ImageScreen
import com.cognitivenexus.mobile.ui.screen.MemoryScreen
import com.cognitivenexus.mobile.ui.screen.ResearchScreen
import com.cognitivenexus.mobile.ui.screen.SettingsScreen
import com.cognitivenexus.mobile.viewmodel.ChatViewModel
import com.cognitivenexus.mobile.viewmodel.ImageViewModel
import com.cognitivenexus.mobile.viewmodel.MemoryViewModel
import com.cognitivenexus.mobile.viewmodel.ResearchViewModel
import com.cognitivenexus.mobile.viewmodel.SettingsViewModel

private val tabs = listOf("chat", "research", "memory", "images", "settings")

@Composable
fun NexusNavHost() {
    val navController = rememberNavController()
    val backStack by navController.currentBackStackEntryAsState()
    val current = backStack?.destination?.route ?: "chat"

    Scaffold(
        bottomBar = {
            NavigationBar {
                tabs.forEach { route ->
                    NavigationBarItem(
                        selected = current == route,
                        onClick = {
                            navController.navigate(route) {
                                launchSingleTop = true
                                restoreState = true
                                popUpTo(navController.graph.startDestinationId) {
                                    saveState = true
                                }
                            }
                        },
                        label = { Text(route) },
                        icon = {},
                    )
                }
            }
        }
    ) { inner ->
        NavHost(navController = navController, startDestination = "chat", modifier = Modifier.padding(inner)) {
            composable("chat") {
                val vm: ChatViewModel = hiltViewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                ChatScreen(state = state, onSend = vm::sendMessage, onRefresh = vm::refreshConversations)
            }
            composable("research") {
                val vm: ResearchViewModel = hiltViewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                ResearchScreen(state = state, onRun = vm::run)
            }
            composable("memory") {
                val vm: MemoryViewModel = hiltViewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                MemoryScreen(
                    state = state,
                    onLoad = vm::loadOverview,
                    onRemember = vm::remember,
                    onForget = vm::forget,
                    onClear = vm::clearAll,
                )
            }
            composable("images") {
                val vm: ImageViewModel = hiltViewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                ImageScreen(state = state, onGenerate = vm::generate, onLoadHistory = vm::loadHistory)
            }
            composable("settings") {
                val vm: SettingsViewModel = hiltViewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                val backend by vm.backendUrl.collectAsStateWithLifecycle()
                SettingsScreen(
                    backendUrl = backend,
                    state = state,
                    onSaveBackend = vm::saveBackendUrl,
                    onSetWebSearch = vm::setWebSearch,
                    onSetLearning = vm::setLearning,
                    onSetGrounding = vm::setGrounding,
                    onClearCache = vm::clearCache,
                )
            }
        }
    }
}
