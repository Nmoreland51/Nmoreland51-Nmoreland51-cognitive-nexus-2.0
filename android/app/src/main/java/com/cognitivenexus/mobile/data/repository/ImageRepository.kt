package com.cognitivenexus.mobile.data.repository

import com.cognitivenexus.mobile.data.remote.ImageRequest
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first

@Singleton
class ImageRepository @Inject constructor(
    private val backendUrlStore: BackendUrlStore,
    private val apiClientFactory: ApiClientFactory,
) {
    suspend fun generate(prompt: String, mode: String) = runCatching {
        apiClientFactory.create(backendUrlStore.backendUrl.first()).generateImage(ImageRequest(prompt = prompt, mode = mode))
    }

    suspend fun history() = runCatching {
        apiClientFactory.create(backendUrlStore.backendUrl.first()).imageHistory()
    }
}
