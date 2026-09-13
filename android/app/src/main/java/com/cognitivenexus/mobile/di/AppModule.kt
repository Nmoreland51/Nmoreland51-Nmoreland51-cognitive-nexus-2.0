package com.cognitivenexus.mobile.di

import android.content.Context
import androidx.room.Room
import com.cognitivenexus.mobile.data.local.AppDatabase
import com.cognitivenexus.mobile.data.local.ChatDao
import com.cognitivenexus.mobile.data.local.ResearchDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): AppDatabase =
        Room.databaseBuilder(context, AppDatabase::class.java, "nexus_mobile.db").build()

    @Provides
    fun provideChatDao(db: AppDatabase): ChatDao = db.chatDao()

    @Provides
    fun provideResearchDao(db: AppDatabase): ResearchDao = db.researchDao()
}
