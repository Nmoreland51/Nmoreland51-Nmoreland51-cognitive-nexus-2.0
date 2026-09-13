package com.cognitivenexus.mobile.data.local

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "chat_messages")
data class ChatMessageEntity(
    @PrimaryKey val id: String,
    val conversationId: String,
    val role: String,
    val content: String,
    val createdAt: Long,
)

@Entity(tableName = "research_cache")
data class ResearchEntity(
    @PrimaryKey val id: String,
    val query: String,
    val summary: String,
    val createdAt: Long,
)

@Dao
interface ChatDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertMessage(message: ChatMessageEntity)

    @Query("SELECT * FROM chat_messages WHERE conversationId = :conversationId ORDER BY createdAt ASC")
    fun messages(conversationId: String): Flow<List<ChatMessageEntity>>

    @Query("DELETE FROM chat_messages")
    suspend fun clearAll()
}

@Dao
interface ResearchDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(item: ResearchEntity)

    @Query("SELECT * FROM research_cache ORDER BY createdAt DESC")
    fun all(): Flow<List<ResearchEntity>>

    @Query("DELETE FROM research_cache")
    suspend fun clearAll()
}

@Database(entities = [ChatMessageEntity::class, ResearchEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun chatDao(): ChatDao
    abstract fun researchDao(): ResearchDao
}
