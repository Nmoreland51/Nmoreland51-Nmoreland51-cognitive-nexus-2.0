"""
Cognitive Web Research Module for Streamlit AI App
=================================================

A production-ready web research module that silently processes URLs,
chunks content, generates embeddings, and provides intelligent retrieval.

Architecture:
- WebResearchModule: Main class with all functionality
- Silent URL processing with loading indicators
- Unified vector database ("brain") for all content
- Reactive responses only when user asks questions
- Modular design for easy Streamlit integration

Features:
- URL scraping with requests + BeautifulSoup
- Intelligent text preprocessing and chunking
- Vector embeddings with sentence-transformers
- FAISS vector database for fast retrieval
- Local LLM integration (placeholder)
- Loading indicators and progress tracking
- Session state management

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
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PLACEHOLDER IMPORTS - Replace with actual implementations
try:
    from sentence_transformers import SentenceTransformer
    EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_AVAILABLE = False
    print("⚠️ sentence-transformers not available. Install with: pip install sentence-transformers")

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("⚠️ faiss-cpu not available. Install with: pip install faiss-cpu")

class WebResearchModule:
    """
    Main Web Research Module for Cognitive Nexus AI
    
    This class handles the complete pipeline:
    1. URL scraping and content extraction
    2. Text preprocessing and intelligent chunking
    3. Vector embedding generation
    4. Unified vector database storage ("brain")
    5. Semantic search and retrieval
    6. LLM-powered response generation
    """
    
    def __init__(self, brain_path: str = "ai_system/knowledge_bank/web_brain"):
        """
        Initialize the Web Research Module
        
        Args:
            brain_path: Path to store the vector database and metadata
        """
        self.brain_path = Path(brain_path)
        self.brain_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize storage paths
        self.vector_db_path = self.brain_path / "vector_index.faiss"
        self.metadata_path = self.brain_path / "metadata.json"
        self.chunks_path = self.brain_path / "chunks.json"
        
        # Initialize components
        self.embedding_model = None
        self.vector_index = None
        self.metadata = self._load_json(self.metadata_path, {})
        self.chunks = self._load_json(self.chunks_path, {})
        self.embedding_dim = 384  # sentence-transformers/all-MiniLM-L6-v2 dimension
        
        # Initialize embedding model and vector database
        self._initialize_embedding_model()
        self._initialize_vector_database()
        
        logger.info(f"WebResearchModule initialized with {len(self.metadata)} URLs and {len(self.chunks)} chunks")
    
    def _load_json(self, file_path: Path, default: Any = None) -> Any:
        """Load JSON file with error handling"""
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
        return default or {}
    
    def _save_json(self, file_path: Path, data: Any) -> bool:
        """Save JSON file with error handling"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving {file_path}: {e}")
            return False
    
    def _initialize_embedding_model(self):
        """Initialize the embedding model"""
        if EMBEDDING_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("✅ Embedding model loaded: all-MiniLM-L6-v2")
            except Exception as e:
                logger.error(f"Failed to load embedding model: {e}")
                self.embedding_model = None
        else:
            logger.warning("⚠️ Using placeholder embedding model")
            self.embedding_model = None
    
    def _initialize_vector_database(self):
        """Initialize FAISS vector database"""
        if FAISS_AVAILABLE and self.embedding_dim:
            try:
                if self.vector_db_path.exists():
                    # Load existing index
                    self.vector_index = faiss.read_index(str(self.vector_db_path))
                    logger.info(f"✅ Loaded existing vector database with {self.vector_index.ntotal} vectors")
                else:
                    # Create new index
                    self.vector_index = faiss.IndexFlatIP(self.embedding_dim)  # Inner product for cosine similarity
                    logger.info("✅ Created new vector database")
            except Exception as e:
                logger.error(f"Failed to initialize vector database: {e}")
                self.vector_index = None
        else:
            logger.warning("⚠️ Using placeholder vector database")
            self.vector_index = None
    
    def scrape_url(self, url: str) -> Dict[str, Any]:
        """
        Scrape visible text content from a URL
        
        Args:
            url: URL to scrape
            
        Returns:
            Dictionary containing scraped content and metadata
        """
        try:
            # Set up request headers to avoid blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
            
            # Fetch the URL
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse HTML content
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
                element.decompose()
            
            # Extract title
            title = soup.find('title')
            title_text = title.get_text().strip() if title else "Untitled"
            
            # Extract main content using multiple strategies
            main_content = self._extract_main_content(soup)
            
            # Extract text content
            text_content = main_content.get_text(separator='\n', strip=True)
            
            # Clean and preprocess text
            cleaned_text = self.preprocess_text(text_content)
            
            # Extract headings for structure
            headings = self._extract_headings(soup)
            
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
            logger.error(f"Error scraping {url}: {e}")
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
    
    def _extract_main_content(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Extract main content area from HTML"""
        # Try multiple content selectors in order of preference
        content_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.content',
            '.post',
            '.article',
            '.entry-content',
            '.post-content',
            '.main-content',
            '#content',
            '#main'
        ]
        
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content and len(content.get_text().strip()) > 100:
                return content
        
        # Fallback to body
        return soup.find('body') or soup
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract heading structure from HTML"""
        headings = []
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            headings.append({
                'level': int(heading.name[1]),
                'text': heading.get_text().strip(),
                'id': heading.get('id', '')
            })
        return headings
    
    def preprocess_text(self, text: str) -> str:
        """
        Clean and preprocess extracted text
        
        Args:
            text: Raw extracted text
            
        Returns:
            Cleaned and preprocessed text
        """
        # Remove excessive whitespace and normalize
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters but keep essential punctuation
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)\[\]\"\']', '', text)
        
        # Remove multiple spaces
        text = re.sub(r' +', ' ', text)
        
        # Remove very short lines (likely navigation/UI elements)
        lines = text.split('\n')
        cleaned_lines = [line.strip() for line in lines if len(line.strip()) > 10]
        
        return '\n'.join(cleaned_lines).strip()
    
    def chunk_text(self, text: str, target_size: int = 750, overlap: int = 150) -> List[Dict[str, Any]]:
        """
        Split text into overlapping chunks for optimal embedding
        
        Args:
            text: Text to chunk
            target_size: Target chunk size in words
            overlap: Overlap between chunks in words
            
        Returns:
            List of chunk dictionaries with metadata
        """
        words = text.split()
        chunks = []
        
        if len(words) <= target_size:
            return [{
                'text': text,
                'word_count': len(words),
                'chunk_id': self._generate_chunk_id(text[:100]),
                'start_word': 0,
                'end_word': len(words),
                'chunk_index': 0
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
            
            # Move start position with overlap
            start = end - overlap
            chunk_index += 1
            
            # Prevent infinite loop
            if start >= len(words) - overlap:
                break
        
        return chunks
    
    def _generate_chunk_id(self, text: str) -> str:
        """Generate unique ID for chunk"""
        return hashlib.md5(text.encode()).hexdigest()[:16]
    
    def embed_chunks(self, chunks: List[Dict[str, Any]]) -> List[np.ndarray]:
        """
        Convert text chunks to vector embeddings
        
        Args:
            chunks: List of text chunks
            
        Returns:
            List of embedding vectors
        """
        embeddings = []
        
        for chunk in chunks:
            if self.embedding_model:
                # Use real embedding model
                embedding = self.embedding_model.encode(chunk['text'])
                embeddings.append(embedding)
            else:
                # PLACEHOLDER: Generate dummy embedding
                # Replace this with your preferred embedding model
                embedding = self._generate_placeholder_embedding(chunk['text'])
                embeddings.append(embedding)
        
        return embeddings
    
    def _generate_placeholder_embedding(self, text: str) -> np.ndarray:
        """Generate placeholder embedding (replace with real model)"""
        # Create deterministic "embedding" based on text hash
        text_hash = hash(text) % (2**32)
        np.random.seed(text_hash)
        return np.random.normal(0, 1, self.embedding_dim).astype(np.float32)
    
    def store_in_brain(self, url: str, chunks: List[Dict[str, Any]], embeddings: List[np.ndarray]) -> bool:
        """
        Store chunks and embeddings in the unified vector database ("brain")
        
        Args:
            url: Source URL
            chunks: List of text chunks
            embeddings: List of embedding vectors
            
        Returns:
            Success status
        """
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
            
            # Store chunks metadata
            self.chunks[url_hash] = {
                'url': url,
                'chunks': chunks,
                'timestamp': datetime.now().isoformat(),
                'chunk_count': len(chunks)
            }
            
            # Store metadata
            self.metadata[url_hash] = {
                'url': url,
                'title': chunks[0].get('title', 'Untitled') if chunks else 'Untitled',
                'timestamp': datetime.now().isoformat(),
                'chunk_count': len(chunks),
                'total_words': sum(chunk['word_count'] for chunk in chunks)
            }
            
            # Store embeddings in vector database
            if self.vector_index is not None:
                # Convert embeddings to numpy array
                embedding_matrix = np.vstack(embeddings).astype(np.float32)
                
                # Add to FAISS index
                self.vector_index.add(embedding_matrix)
                
                # Save FAISS index
                faiss.write_index(self.vector_index, str(self.vector_db_path))
                
                logger.info(f"✅ Stored {len(chunks)} chunks and embeddings for {url}")
            
            # Save metadata and chunks
            self._save_json(self.metadata_path, self.metadata)
            self._save_json(self.chunks_path, self.chunks)
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing in brain: {e}")
            return False
    
    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve most relevant chunks for a query
        
        Args:
            query: Search query
            k: Number of results to return
            
        Returns:
            List of relevant chunks with similarity scores
        """
        try:
            if self.vector_index is None or self.vector_index.ntotal == 0:
                return []
            
            # Generate query embedding
            if self.embedding_model:
                query_embedding = self.embedding_model.encode([query])
            else:
                query_embedding = self._generate_placeholder_embedding(query).reshape(1, -1)
            
            # Search vector database
            scores, indices = self.vector_index.search(query_embedding, k)
            
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < self.vector_index.ntotal:
                    # Find which URL and chunk this index corresponds to
                    chunk_info = self._find_chunk_by_index(idx)
                    if chunk_info:
                        chunk_info['similarity'] = float(score)
                        results.append(chunk_info)
            
            return results
            
        except Exception as e:
            logger.error(f"Error in retrieval: {e}")
            return []
    
    def _find_chunk_by_index(self, vector_index: int) -> Optional[Dict[str, Any]]:
        """Find chunk information by vector database index"""
        current_index = 0
        
        for url_hash, url_data in self.chunks.items():
            chunk_count = len(url_data['chunks'])
            if current_index <= vector_index < current_index + chunk_count:
                chunk_idx = vector_index - current_index
                chunk = url_data['chunks'][chunk_idx]
                metadata = self.metadata.get(url_hash, {})
                
                return {
                    'text': chunk['text'],
                    'url': url_data['url'],
                    'title': metadata.get('title', 'Untitled'),
                    'chunk_id': chunk['chunk_id'],
                    'chunk_index': chunk['chunk_index']
                }
            
            current_index += chunk_count
        
        return None
    
    def answer_query(self, query: str) -> str:
        """
        Generate AI response using retrieved context
        
        Args:
            query: User question
            
        Returns:
            Generated response
        """
        try:
            # Retrieve relevant context
            relevant_chunks = self.retrieve(query, k=5)
            
            if not relevant_chunks:
                return "I don't have enough information to answer that question. Please process some URLs first."
            
            # Prepare context for LLM
            context = "\n\n".join([
                f"[Source: {chunk['title']}]\n{chunk['text']}"
                for chunk in relevant_chunks
            ])
            
            # Generate response using LLM
            response = self._call_llm(query, context, relevant_chunks)
            
            return response
            
        except Exception as e:
            logger.error(f"Error generating answer: {e}")
            return f"Sorry, I encountered an error while processing your question: {str(e)}"
    
    def _call_llm(self, query: str, context: str, sources: List[Dict[str, Any]]) -> str:
        """
        Call LLM to generate response (placeholder implementation)
        
        Args:
            query: User question
            context: Retrieved context
            sources: Source information
            
        Returns:
            LLM-generated response
        """
        # PLACEHOLDER: Replace with your preferred LLM
        
        # Option 1: OpenAI API
        # import openai
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
        
        # Option 2: Local LLM (Ollama)
        # import requests
        # prompt = f"Context: {context}\n\nQuestion: {query}\n\nAnswer:"
        # 
        # response = requests.post('http://localhost:11434/api/generate',
        #     json={'model': 'llama2', 'prompt': prompt, 'stream': False})
        # return response.json()['response']
        
        # Option 3: Hugging Face Transformers
        # from transformers import pipeline
        # if not hasattr(self, 'qa_pipeline'):
        #     self.qa_pipeline = pipeline("question-answering", model="distilbert-base-cased-distilled-squad")
        # 
        # result = self.qa_pipeline(question=query, context=context)
        # return result['answer']
        
        # PLACEHOLDER: Return mock response
        source_titles = list(set([chunk['title'] for chunk in sources]))
        sources_text = f" from {', '.join(source_titles)}" if source_titles else ""
        
        return f"""Based on the processed content{sources_text}, here's what I found:

**Question:** {query}

**Answer:** This is a placeholder response. The actual implementation would use an LLM (like GPT-4, LLaMA 2, or Mistral) to generate a comprehensive answer based on the retrieved context.

**Sources used:** {len(sources)} relevant sections from your processed URLs.

*Note: Replace the _call_llm method with your preferred LLM integration (OpenAI, Ollama, Hugging Face, etc.).*"""
    
    def optional_summary_alert(self, url: str, content_data: Dict[str, Any]) -> Optional[str]:
        """
        Generate optional summary alert if content is highly relevant
        
        Args:
            url: Processed URL
            content_data: Extracted content data
            
        Returns:
            Summary alert message if relevant, None otherwise
        """
        # Only show alert for substantial content
        if content_data['word_count'] > 1000:
            return f"💡 I've processed '{content_data['title']}' ({content_data['word_count']:,} words). Ask me any questions about this content!"
        
        return None
    
    def get_brain_stats(self) -> Dict[str, Any]:
        """Get statistics about the knowledge brain"""
        total_chunks = sum(data['chunk_count'] for data in self.metadata.values())
        total_words = sum(data['total_words'] for data in self.metadata.values())
        vector_count = self.vector_index.ntotal if self.vector_index else 0
        
        return {
            'urls_processed': len(self.metadata),
            'total_chunks': total_chunks,
            'total_words': total_words,
            'vectors_stored': vector_count,
            'brain_size_mb': self._calculate_brain_size()
        }
    
    def _calculate_brain_size(self) -> float:
        """Calculate approximate brain size in MB"""
        total_size = 0
        
        for file_path in [self.vector_db_path, self.metadata_path, self.chunks_path]:
            if file_path.exists():
                total_size += file_path.stat().st_size
        
        return round(total_size / (1024 * 1024), 2)


def render_web_research_tab():
    """
    Render the Web Research tab for Streamlit
    This is the main integration point for Cognitive Nexus AI
    """
    
    # Initialize the module in session state
    if 'web_research' not in st.session_state:
        st.session_state.web_research = WebResearchModule()
    
    web_research = st.session_state.web_research
    
    # Header
    st.header("🌐 Web Research & Knowledge Brain")
    
    # Display brain statistics
    stats = web_research.get_brain_stats()
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📄 URLs", stats['urls_processed'])
    with col2:
        st.metric("📝 Chunks", stats['total_chunks'])
    with col3:
        st.metric("📊 Words", f"{stats['total_words']:,}")
    with col4:
        st.metric("🧠 Brain Size", f"{stats['brain_size_mb']} MB")
    
    st.divider()
    
    # URL Processing Section
    st.subheader("📥 Process URL")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        url_input = st.text_input(
            "Paste URL to process:",
            placeholder="https://example.com/article",
            help="The AI will silently scrape, chunk, and store content in the knowledge brain."
        )
    
    with col2:
        if st.button("🗑️ Clear Brain"):
            # Clear all data
            web_research.metadata = {}
            web_research.chunks = {}
            web_research.vector_index = None
            web_research._initialize_vector_database()
            st.success("🧹 Brain cleared!")
            st.rerun()
    
    # Process URL button
    if st.button("🔍 Process URL", type="primary", disabled=not url_input):
        if not url_input.startswith(('http://', 'https://')):
            st.error("❌ Please enter a valid URL")
        else:
            # Create progress containers
            progress_container = st.container()
            status_container = st.container()
            
            with progress_container:
                progress_bar = st.progress(0)
                status_text = st.empty()
            
            # Step 1: Scrape URL
            status_text.text("🕷️ Scraping URL...")
            progress_bar.progress(20)
            
            content_data = web_research.scrape_url(url_input)
            
            if content_data['status'] == 'error':
                st.error(f"❌ Error: {content_data.get('error', 'Unknown error')}")
            else:
                # Step 2: Chunk text
                status_text.text("✂️ Chunking content...")
                progress_bar.progress(40)
                
                chunks = web_research.chunk_text(content_data['content'])
                
                # Step 3: Generate embeddings
                status_text.text("🧠 Generating embeddings...")
                progress_bar.progress(60)
                
                embeddings = web_research.embed_chunks(chunks)
                
                # Step 4: Store in brain
                status_text.text("💾 Storing in brain...")
                progress_bar.progress(80)
                
                success = web_research.store_in_brain(url_input, chunks, embeddings)
                
                if success:
                    status_text.text("✅ Processing complete!")
                    progress_bar.progress(100)
                    
                    # Show success message
                    st.success(f"✅ Processed: **{content_data['title']}**")
                    st.info(f"📊 Created {len(chunks)} chunks from {content_data['word_count']:,} words")
                    
                    # Optional summary alert
                    alert = web_research.optional_summary_alert(url_input, content_data)
                    if alert:
                        st.info(alert)
                    
                    # Clear the URL input
                    st.rerun()
                else:
                    st.error("❌ Failed to store content in brain")
    
    st.divider()
    
    # Question & Answer Section
    st.subheader("❓ Ask Questions")
    
    question = st.text_input(
        "Ask about processed content:",
        placeholder="What are the main topics covered in the processed articles?",
        help="The AI will search through the knowledge brain to answer your question."
    )
    
    if st.button("🤔 Ask Question", type="primary", disabled=not question):
        with st.spinner("🔍 Searching knowledge brain..."):
            # Generate answer
            answer = web_research.answer_query(question)
            
            # Display answer
            st.markdown("### 🤖 AI Response")
            st.markdown(answer)
            
            # Show retrieval stats
            relevant_chunks = web_research.retrieve(question, k=5)
            if relevant_chunks:
                with st.expander("📚 Sources Used"):
                    for i, chunk in enumerate(relevant_chunks, 1):
                        st.markdown(f"**{i}. {chunk['title']}** (Similarity: {chunk['similarity']:.3f})")
                        st.markdown(f"*URL:* {chunk['url']}")
                        st.text(chunk['text'][:200] + "..." if len(chunk['text']) > 200 else chunk['text'])
                        st.divider()
    
    st.divider()
    
    # Brain Overview
    if stats['urls_processed'] > 0:
        st.subheader("📚 Processed URLs")
        
        for url_hash, url_data in web_research.metadata.items():
            with st.expander(f"📄 {url_data['title']}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**URL:** {url_data['url']}")
                    st.markdown(f"**Processed:** {url_data['timestamp']}")
                with col2:
                    st.markdown(f"**Words:** {url_data['total_words']:,}")
                    st.markdown(f"**Chunks:** {url_data['chunk_count']}")
    
    # Debug Information
    with st.expander("🔧 Debug Information"):
        st.json(stats)


# Example usage and integration
if __name__ == "__main__":
    st.set_page_config(page_title="Web Research Module", layout="wide")
    
    st.title("🧪 Web Research Module - Standalone Test")
    
    # Render the web research tab
    render_web_research_tab()
    
    st.divider()
    st.markdown("""
    ### 🔧 Integration Instructions
    
    **To integrate into Cognitive Nexus AI:**
    
    1. **Copy the module file to your app directory**
    2. **Install dependencies:**
       ```bash
       pip install streamlit requests beautifulsoup4 sentence-transformers faiss-cpu
       ```
    
    3. **Import in your main app:**
       ```python
       from cognitive_web_research import render_web_research_tab
       ```
    
    4. **Add to your tab system:**
       ```python
       elif selected_tab == "🌐 Web Research":
           render_web_research_tab()
       ```
    
    5. **Replace placeholder implementations:**
       - Update `_call_llm()` with your preferred LLM
       - Update `embed_chunks()` if using different embedding model
       - Configure vector database settings as needed
    
    **Ready to use!** 🚀
    """)
