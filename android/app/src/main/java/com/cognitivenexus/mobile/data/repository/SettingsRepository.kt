package com.cognitivenexus.mobile.data.repository

import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow

@Singleton
class SettingsRepository @Inject constructor(
    private val backendUrlStore: BackendUrlStore,
) {
    val backendUrl: Flow<String> = backendUrlStore.backendUrl

    suspend fun setBackendUrl(url: String) {
        backendUrlStore.setBackendUrl(url)
    }
}
