"""
Web Research Module for Cognitive Nexus AI
==========================================

A comprehensive module for processing URLs, extracting content, chunking text,
generating embeddings, and providing intelligent retrieval for AI responses.

Features:
- URL content extraction and preprocessing
- Intelligent text chunking (500-1000 words)
- Vector embeddings with unified storage
- Semantic search and retrieval
- Background processing with loading indicators
- Multi-URL support with unified knowledge base
- Modular design for easy integration

Author: Cognitive Nexus AI System
Version: 1.0
"""

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import json
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebResearchModule:
    """
    Main Web Research Module for URL processing and knowledge storage
    """
    
    def __init__(self, knowledge_base_path: str = "ai_system/knowledge_bank/web_research"):
        """
        Initialize the Web Research Module
        
        Args:
            knowledge_base_path: Path to store the knowledge base
        """
        self.knowledge_base_path = Path(knowledge_base_path)
        self.knowledge_base_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize storage files
        self.chunks_file = self.knowledge_base_path / "chunks.json"
        self.embeddings_file = self.knowledge_base_path / "embeddings.json"
        self.metadata_file = self.knowledge_base_path / "metadata.json"
        
        # Load existing data
        self.chunks = self._load_json_file(self.chunks_file, {})
        self.embeddings = self._load_json_file(self.embeddings_file, {})
        self.metadata = self._load_json_file(self.metadata_file, {})
        
        # Initialize embedding model (placeholder)
        self.embedding_model = None
        self.llm_model = None
        self._embedding_cache = {}
        
    def _load_json_file(self, file_path: Path, default: Any = None) -> Any:
        """Load JSON file with error handling"""
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
        return default or {}
    
    def _save_json_file(self, file_path: Path, data: Any) -> bool:
        """Save JSON file with error handling"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving {file_path}: {e}")
            return False
    
    def extract_content_from_url(self, url: str) -> Dict[str, Any]:
        """
        Extract and preprocess content from a URL
        
        Args:
            url: URL to process
            
        Returns:
            Dictionary containing extracted content and metadata
        """
        try:
            # Fetch the URL
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            
            # Extract title
            title = soup.find('title')
            title_text = title.get_text().strip() if title else "Untitled"
            
            # Extract main content
            content_selectors = [
                'article', 'main', '.content', '.post', '.article',
                'div[role="main"]', '.entry-content', '.post-content'
            ]
            
            main_content = None
            for selector in content_selectors:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            if not main_content:
                # Fallback to body
                main_content = soup.find('body') or soup
            
            # Extract text content
            text_content = main_content.get_text(separator='\n', strip=True)
            
            # Clean and preprocess text
            cleaned_text = self._clean_text(text_content)
            
            # Extract headings for structure
            headings = []
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                headings.append({
                    'level': int(heading.name[1]),
                    'text': heading.get_text().strip(),
                    'id': heading.get('id', '')
                })
            
            return {
                'url': url,
                'title': title_text,
                'content': cleaned_text,
                'headings': headings,
                'word_count': len(cleaned_text.split()),
                'timestamp': datetime.now().isoformat(),
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}")
            return {
                'url': url,
                'title': 'Error',
                'content': '',
                'headings': [],
                'word_count': 0,
                'timestamp': datetime.now().isoformat(),
                'status': 'error',
                'error': str(e)
            }
    
    def _clean_text(self, text: str) -> str:
        """Clean and preprocess extracted text"""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters but keep punctuation
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)]', '', text)
        
        # Remove multiple spaces
        text = re.sub(r' +', ' ', text)
        
        return text.strip()
    
    def chunk_text(self, text: str, target_size: int = 750, overlap: int = 100) -> List[Dict[str, Any]]:
        """
        Split text into overlapping chunks
        
        Args:
            text: Text to chunk
            target_size: Target chunk size in words
            overlap: Overlap between chunks in words
            
        Returns:
            List of chunk dictionaries
        """
        words = text.split()
        chunks = []
        
        if len(words) <= target_size:
            return [{
                'text': text,
                'word_count': len(words),
                'chunk_id': self._generate_chunk_id(text[:100]),
                'start_word': 0,
                'end_word': len(words)
            }]
        
        start = 0
        chunk_index = 0
        
        while start < len(words):
            end = min(start + target_size, len(words))
            chunk_words = words[start:end]
            chunk_text = ' '.join(chunk_words)
            
            chunk_id = self._generate_chunk_id(chunk_text[:100])
            
            chunks.append({
                'text': chunk_text,
                'word_count': len(chunk_words),
                'chunk_id': chunk_id,
                'start_word': start,
                'end_word': end,
                'chunk_index': chunk_index
            })
            
            start = end - overlap
            chunk_index += 1
            
            # Prevent infinite loop
            if start >= len(words) - overlap:
                break
        
        return chunks
    
    def _generate_chunk_id(self, text: str) -> str:
        """Generate unique ID for chunk"""
        return hashlib.md5(text.encode()).hexdigest()[:12]
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate vector embedding for text (placeholder implementation)
        
        Args:
            text: Text to embed
            
        Returns:
            Vector embedding as list of floats
        """
        # PLACEHOLDER: Replace with actual embedding model
        # Example implementations:
        
        # Option 1: Using sentence-transformers
        # from sentence_transformers import SentenceTransformer
        # if not self.embedding_model:
        #     self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        # return self.embedding_model.encode(text).tolist()
        
        # Option 2: Using OpenAI embeddings
        # import openai
        # response = openai.Embedding.create(
        #     input=text,
        #     model="text-embedding-ada-002"
        # )
        # return response['data'][0]['embedding']
        
        # Option 3: Using Hugging Face
        # from transformers import AutoTokenizer, AutoModel
        # import torch
        # if not self.embedding_model:
        #     model_name = "sentence-transformers/all-MiniLM-L6-v2"
        #     self.embedding_model = AutoModel.from_pretrained(model_name)
        #     self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        # 
        # inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        # with torch.no_grad():
        #     outputs = self.embedding_model(**inputs)
        #     embeddings = outputs.last_hidden_state.mean(dim=1).squeeze()
        # return embeddings.tolist()
        
        cache_key = hashlib.md5(text.encode("utf-8")).hexdigest()
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        # PLACEHOLDER: Return dummy embedding
        import random
        random.seed(int(cache_key[:8], 16))
        embedding = [random.random() for _ in range(384)]  # 384-dimensional embedding
        self._embedding_cache[cache_key] = embedding
        return embedding
    
    def store_chunks_and_embeddings(self, url: str, chunks: List[Dict[str, Any]]) -> bool:
        """
        Store chunks and generate embeddings
        
        Args:
            url: Source URL
            chunks: List of text chunks
            
        Returns:
            Success status
        """
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            
            # Store chunks
            if url_hash not in self.chunks:
                self.chunks[url_hash] = {}
            
            for chunk in chunks:
                chunk_id = chunk['chunk_id']
                self.chunks[url_hash][chunk_id] = chunk
                
                # Generate and store embedding
                if url_hash not in self.embeddings:
                    self.embeddings[url_hash] = {}
                if chunk_id in self.embeddings[url_hash]:
                    continue
                embedding = self.generate_embedding(chunk['text'])
                self.embeddings[url_hash][chunk_id] = embedding
            
            # Save to files
            self._save_json_file(self.chunks_file, self.chunks)
            self._save_json_file(self.embeddings_file, self.embeddings)
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing chunks and embeddings: {e}")
            return False
    
    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform semantic search across all stored content
        
        Args:
            query: Search query
            top_k: Number of top results to return
            
        Returns:
            List of relevant chunks with similarity scores
        """
        try:
            # Generate query embedding
            query_embedding = self.generate_embedding(query)
            
            results = []
            
            # Search across all URLs and chunks
            for url_hash, chunks in self.embeddings.items():
                for chunk_id, chunk_embedding in chunks.items():
                    # Calculate cosine similarity (placeholder)
                    similarity = self._cosine_similarity(query_embedding, chunk_embedding)
                    
                    # Get chunk metadata
                    chunk_data = self.chunks.get(url_hash, {}).get(chunk_id, {})
                    url_metadata = self.metadata.get(url_hash, {})
                    
                    results.append({
                        'chunk_id': chunk_id,
                        'text': chunk_data.get('text', ''),
                        'similarity': similarity,
                        'url': url_metadata.get('url', ''),
                        'title': url_metadata.get('title', ''),
                        'chunk_index': chunk_data.get('chunk_index', 0)
                    })
            
            # Sort by similarity and return top results
            results.sort(key=lambda x: x['similarity'], reverse=True)
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            return []
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        import math
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(a * a for a in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0
        
        return dot_product / (magnitude1 * magnitude2)
    
    def generate_response(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """
        Generate AI response using retrieved context (placeholder implementation)
        
        Args:
            query: User question
            context_chunks: Retrieved relevant chunks
            
        Returns:
            Generated response
        """
        # PLACEHOLDER: Replace with actual LLM call
        # Example implementations:
        
        # Option 1: Using OpenAI
        # import openai
        # context = "\n\n".join([chunk['text'] for chunk in context_chunks])
        # prompt = f"""Based on the following context, answer the user's question.
        # 
        # Context:
        # {context}
        # 
        # Question: {query}
        # 
        # Answer:"""
        # 
        # response = openai.ChatCompletion.create(
        #     model="gpt-3.5-turbo",
        #     messages=[{"role": "user", "content": prompt}],
        #     max_tokens=500
        # )
        # return response.choices[0].message.content
        
        # Option 2: Using local LLM (Ollama)
        # import requests
        # context = "\n\n".join([chunk['text'] for chunk in context_chunks])
        # prompt = f"Context: {context}\n\nQuestion: {query}\n\nAnswer:"
        # 
        # response = requests.post('http://localhost:11434/api/generate',
        #     json={'model': 'llama2', 'prompt': prompt, 'stream': False})
        # return response.json()['response']
        
        # PLACEHOLDER: Return mock response
        if not context_chunks:
            return "I don't have enough information to answer that question. Please process some URLs first."
        
        context_sources = [chunk['title'] for chunk in context_chunks if chunk['title']]
        sources_text = f" (from {', '.join(set(context_sources))})" if context_sources else ""
        
        return f"""Based on the processed content{sources_text}, here's what I found:

**Question:** {query}

**Answer:** This is a placeholder response. The actual implementation would use an LLM to generate a comprehensive answer based on the retrieved context chunks.

**Sources used:** {len(context_chunks)} relevant sections from your processed URLs.

*Note: This is a demo response. Replace the generate_response method with your preferred LLM integration.*"""
    
    def get_processing_summary(self) -> Dict[str, Any]:
        """Get summary of processed URLs and stored content"""
        total_chunks = sum(len(chunks) for chunks in self.chunks.values())
        total_urls = len(self.metadata)
        
        return {
            'total_urls': total_urls,
            'total_chunks': total_chunks,
            'total_words': sum(
                chunk.get('word_count', 0) 
                for url_chunks in self.chunks.values() 
                for chunk in url_chunks.values()
            ),
            'urls': list(self.metadata.values())
        }


def render_web_research_tab():
    """
    Render the Web Research tab for Streamlit
    This function can be called from your main Streamlit app
    """
    
    # Initialize the module
    if 'web_research' not in st.session_state:
        st.session_state.web_research = WebResearchModule()
    
    web_research = st.session_state.web_research
    
    st.header("🌐 Web Research & Knowledge Base")
    
    # Display summary
    summary = web_research.get_processing_summary()
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📄 URLs Processed", summary['total_urls'])
    with col2:
        st.metric("📝 Content Chunks", summary['total_chunks'])
    with col3:
        st.metric("📊 Total Words", f"{summary['total_words']:,}")
    with col4:
        st.metric("🧠 Knowledge Base", "Active")
    
    st.divider()
    
    # URL Processing Section
    st.subheader("📥 Process New URL")
    
    url_input = st.text_input(
        "Paste a URL to process:",
        placeholder="https://example.com/article",
        help="The AI will extract, chunk, and store the content for future questions."
    )
    
    col1, col2 = st.columns([1, 4])
    
    with col1:
        process_button = st.button("🔍 Process URL", type="primary")
    
    with col2:
        if st.button("🗑️ Clear All Data"):
            if st.session_state.web_research:
                # Clear all data
                st.session_state.web_research.chunks = {}
                st.session_state.web_research.embeddings = {}
                st.session_state.web_research.metadata = {}
                st.success("🧹 All data cleared!")
                st.rerun()
    
    # Process URL
    if process_button and url_input:
        if not url_input.startswith(('http://', 'https://')):
            st.error("❌ Please enter a valid URL starting with http:// or https://")
        else:
            with st.spinner("🔄 Processing URL..."):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Step 1: Extract content
                status_text.text("📄 Extracting content...")
                progress_bar.progress(25)
                
                content_data = web_research.extract_content_from_url(url_input)
                
                if content_data['status'] == 'error':
                    st.error(f"❌ Error processing URL: {content_data.get('error', 'Unknown error')}")
                else:
                    # Step 2: Chunk text
                    status_text.text("✂️ Chunking text...")
                    progress_bar.progress(50)
                    
                    chunks = web_research.chunk_text(content_data['content'])
                    
                    # Step 3: Generate embeddings
                    status_text.text("🧠 Generating embeddings...")
                    progress_bar.progress(75)
                    
                    # Store metadata
                    url_hash = hashlib.md5(url_input.encode()).hexdigest()[:12]
                    web_research.metadata[url_hash] = {
                        'url': url_input,
                        'title': content_data['title'],
                        'timestamp': content_data['timestamp'],
                        'word_count': content_data['word_count'],
                        'chunks_count': len(chunks)
                    }
                    
                    # Store chunks and embeddings
                    success = web_research.store_chunks_and_embeddings(url_input, chunks)
                    
                    if success:
                        status_text.text("💾 Saving to knowledge base...")
                        progress_bar.progress(100)
                        
                        # Save metadata
                        web_research._save_json_file(web_research.metadata_file, web_research.metadata)
                        
                        st.success(f"✅ Successfully processed: **{content_data['title']}**")
                        st.info(f"📊 Created {len(chunks)} chunks from {content_data['word_count']:,} words")
                        
                        # Show hint if content seems substantial
                        if content_data['word_count'] > 1000:
                            st.info("💡 I've processed this URL. Ask me a question whenever you want insights.")
                    else:
                        st.error("❌ Failed to store content in knowledge base")
    
    st.divider()
    
    # Question & Answer Section
    st.subheader("❓ Ask Questions About Processed Content")
    
    question = st.text_input(
        "Ask a question about the processed URLs:",
        placeholder="What are the main topics covered in the processed articles?",
        help="The AI will search through all processed content to answer your question."
    )
    
    if st.button("🤔 Ask Question", type="primary") and question:
        with st.spinner("🔍 Searching knowledge base..."):
            # Perform semantic search
            relevant_chunks = web_research.semantic_search(question, top_k=5)
            
            if relevant_chunks:
                # Generate response
                response = web_research.generate_response(question, relevant_chunks)
                
                st.success("✅ Found relevant information!")
                st.markdown("### 🤖 AI Response")
                st.markdown(response)
                
                # Show sources
                st.markdown("### 📚 Sources Used")
                for i, chunk in enumerate(relevant_chunks, 1):
                    with st.expander(f"Source {i}: {chunk['title']} (Similarity: {chunk['similarity']:.3f})"):
                        st.markdown(f"**URL:** {chunk['url']}")
                        st.markdown(f"**Relevant text:**")
                        st.text(chunk['text'][:500] + "..." if len(chunk['text']) > 500 else chunk['text'])
            else:
                st.warning("⚠️ No relevant information found. Try processing more URLs or rephrasing your question.")
    
    st.divider()
    
    # Knowledge Base Overview
    if summary['total_urls'] > 0:
        st.subheader("📚 Processed URLs")
        
        for url_data in summary['urls']:
            with st.expander(f"📄 {url_data['title']}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**URL:** {url_data['url']}")
                    st.markdown(f"**Processed:** {url_data['timestamp']}")
                with col2:
                    st.markdown(f"**Words:** {url_data['word_count']:,}")
                    st.markdown(f"**Chunks:** {url_data['chunks_count']}")
    
    # Debug Information (collapsible)
    with st.expander("🔧 Debug Information"):
        st.json(summary)


# Example usage in main Streamlit app
if __name__ == "__main__":
    st.set_page_config(page_title="Web Research Module", layout="wide")
    
    st.title("🧪 Web Research Module - Standalone Test")
    
    # Render the web research tab
    render_web_research_tab()
    
    st.divider()
    st.markdown("### 📋 Integration Instructions")
    st.markdown("""
    To integrate this module into your main Cognitive Nexus AI app:
    
    1. **Import the module:**
       ```python
       from web_research_module import render_web_research_tab
       ```
    
    2. **Add to your tab system:**
       ```python
       if selected_tab == "🌐 Web Research":
           render_web_research_tab()
       ```
    
    3. **Replace placeholder implementations:**
       - Update `generate_embedding()` with your preferred embedding model
       - Update `generate_response()` with your preferred LLM
       - Configure vector database if needed
    
    4. **Customize as needed:**
       - Adjust chunk sizes and overlap
       - Modify UI elements
       - Add additional features
    """)
