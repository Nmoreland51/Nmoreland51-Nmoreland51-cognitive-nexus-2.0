package com.cognitivenexus.mobile.data.repository

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.cognitivenexus.mobile.BuildConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.backendDataStore by preferencesDataStore(name = "backend_settings")

@Singleton
class BackendUrlStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val backendUrlKey = stringPreferencesKey("backend_url")

    val backendUrl: Flow<String> = context.backendDataStore.data.map { prefs: Preferences ->
        (prefs[backendUrlKey] ?: BuildConfig.DEFAULT_BACKEND_URL).ensureTrailingSlash()
    }

    suspend fun setBackendUrl(value: String) {
        context.backendDataStore.edit { prefs ->
            prefs[backendUrlKey] = value.ensureTrailingSlash()
        }
    }
}

private fun String.ensureTrailingSlash(): String = if (endsWith('/')) this else "$this/"
