package com.cognitivenexus.mobile.data.repository

import com.cognitivenexus.mobile.data.remote.NexusApiService
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import okhttp3.MediaType.Companion.toMediaType
import java.util.concurrent.ConcurrentHashMap

@Singleton
class ApiClientFactory @Inject constructor() {
    private val json = Json { ignoreUnknownKeys = true }
    private val logger = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC }
    private val client = OkHttpClient.Builder().addInterceptor(logger).build()
    private val cache = ConcurrentHashMap<String, NexusApiService>()

    fun create(baseUrl: String): NexusApiService {
        return cache.getOrPut(baseUrl) {
            Retrofit.Builder()
                .baseUrl(baseUrl)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .client(client)
                .build()
                .create(NexusApiService::class.java)
        }
    }
}
