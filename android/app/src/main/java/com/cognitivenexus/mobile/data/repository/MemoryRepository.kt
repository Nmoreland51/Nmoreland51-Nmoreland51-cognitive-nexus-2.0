package com.cognitivenexus.mobile.data.repository

import com.cognitivenexus.mobile.data.remote.MemoryFactRequest
import com.cognitivenexus.mobile.data.remote.MemoryForgetRequest
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first

@Singleton
class MemoryRepository @Inject constructor(
    private val backendUrlStore: BackendUrlStore,
    private val apiClientFactory: ApiClientFactory,
) {
    suspend fun overview() = runCatching {
        apiClientFactory.create(backendUrlStore.backendUrl.first()).memoryOverview()
    }

    suspend fun remember(text: String) = runCatching {
        apiClientFactory.create(backendUrlStore.backendUrl.first()).remember(MemoryFactRequest(text))
    }

    suspend fun forget(query: String) = runCatching {
        apiClientFactory.create(backendUrlStore.backendUrl.first()).forget(MemoryForgetRequest(query))
    }

    suspend fun clearAll() = runCatching {
        apiClientFactory.create(backendUrlStore.backendUrl.first()).clearMemory()
    }
}
