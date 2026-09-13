package com.cognitivenexus.mobile.data.repository

import com.cognitivenexus.mobile.data.local.ResearchDao
import com.cognitivenexus.mobile.data.local.ResearchEntity
import com.cognitivenexus.mobile.data.remote.ResearchRequest
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first

@Singleton
class ResearchRepository @Inject constructor(
    private val backendUrlStore: BackendUrlStore,
    private val apiClientFactory: ApiClientFactory,
    private val researchDao: ResearchDao,
) {
    suspend fun runResearch(query: String): Result<String> = runCatching {
        val api = apiClientFactory.create(backendUrlStore.backendUrl.first())
        val response = api.research(ResearchRequest(query))
        val summary = response.report["summary"]?.toString() ?: ""
        researchDao.upsert(
            ResearchEntity(
                id = "research_${System.currentTimeMillis()}",
                query = query,
                summary = summary,
                createdAt = System.currentTimeMillis(),
            )
        )
        summary
    }
}
