# 🌐 Web Research Module - Integration Guide

## 📋 Overview

The Web Research Module is a production-ready component for Cognitive Nexus AI that silently processes URLs, chunks content, generates embeddings, and provides intelligent retrieval. It's designed to be modular and easily integrated into your existing Streamlit app.

## 🏗️ Architecture

```
WebResearchModule
├── scrape_url(url)                # Scrape visible text
├── preprocess_text(text)          # Clean and chunk
├── embed_chunks(chunks)           # Convert to vector embeddings
├── store_in_brain(embeddings)     # Store embeddings in vector DB
├── retrieve(query, k=5)           # Get most relevant chunks
├── answer_query(query)            # Feed to LLM + return answer
├── optional_summary_alert()       # Only if highly relevant
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements_web_research.txt
```

**Core dependencies:**
- `streamlit` - Web interface
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `sentence-transformers` - Embeddings
- `faiss-cpu` - Vector database
- `numpy` - Numerical operations

### 2. Test the Module

```bash
# Test core functionality
python test_web_research_module.py

# Test UI
streamlit run cognitive_web_research.py
```

### 3. Integrate into Cognitive Nexus AI

```python
# In your main app file
from cognitive_web_research import render_web_research_tab

# In your tab system
elif selected_tab == "🌐 Web Research":
    render_web_research_tab()
```

## 🔧 Configuration

### Embedding Model

**Default:** `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, lightweight)

**To change:**
```python
# In WebResearchModule.__init__()
self.embedding_model = SentenceTransformer('your-preferred-model')
```

**Popular alternatives:**
- `all-mpnet-base-v2` (768 dim, better quality)
- `multi-qa-MiniLM-L6-cos-v1` (384 dim, optimized for Q&A)
- `paraphrase-multilingual-MiniLM-L12-v2` (384 dim, multilingual)

### Vector Database

**Default:** FAISS IndexFlatIP (Inner Product for cosine similarity)

**To change:**
```python
# In _initialize_vector_database()
self.vector_index = faiss.IndexHNSWFlat(self.embedding_dim, 32)  # HNSW for speed
```

### Chunking Parameters

**Default:** 750 words per chunk, 150 words overlap

**To change:**
```python
# In chunk_text()
chunks = web_research.chunk_text(text, target_size=1000, overlap=200)
```

## 🤖 LLM Integration

### OpenAI API

```python
def _call_llm(self, query: str, context: str, sources: List[Dict]) -> str:
    import openai
    
    prompt = f"""Based on the following context, answer the user's question.
    
    Context:
    {context}
    
    Question: {query}
    
    Answer:"""
    
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500
    )
    return response.choices[0].message.content
```

### Local LLM (Ollama)

```python
def _call_llm(self, query: str, context: str, sources: List[Dict]) -> str:
    import requests
    
    prompt = f"Context: {context}\n\nQuestion: {query}\n\nAnswer:"
    
    response = requests.post('http://localhost:11434/api/generate',
        json={'model': 'llama2', 'prompt': prompt, 'stream': False})
    return response.json()['response']
```

### Hugging Face Transformers

```python
def _call_llm(self, query: str, context: str, sources: List[Dict]) -> str:
    from transformers import pipeline
    
    if not hasattr(self, 'qa_pipeline'):
        self.qa_pipeline = pipeline("question-answering", 
                                  model="distilbert-base-cased-distilled-squad")
    
    result = self.qa_pipeline(question=query, context=context)
    return result['answer']
```

## 📊 Features

### ✅ Implemented Features

- **URL Scraping:** Extracts visible text from web pages
- **Text Preprocessing:** Cleans and normalizes content
- **Intelligent Chunking:** Splits text into optimal chunks (500-1000 words)
- **Vector Embeddings:** Converts text to high-dimensional vectors
- **FAISS Vector DB:** Fast similarity search and retrieval
- **Semantic Search:** Finds relevant content based on meaning
- **Loading Indicators:** Progress bars and status updates
- **Session Management:** Persistent storage across sessions
- **Multi-URL Support:** Unified knowledge base for all URLs
- **Reactive Responses:** Only responds when user asks questions

### 🔄 Workflow

1. **User pastes URL** → Module silently scrapes content
2. **Text preprocessing** → Cleans and chunks content
3. **Embedding generation** → Converts chunks to vectors
4. **Vector storage** → Stores in unified "brain" database
5. **User asks question** → Retrieves relevant chunks
6. **LLM response** → Generates answer using context

## 🎯 Usage Examples

### Basic Integration

```python
import streamlit as st
from cognitive_web_research import render_web_research_tab

# In your main app
tabs = ["💬 Chat", "🌐 Web Research", "🧠 Memory"]
selected_tab = st.sidebar.radio("Select Tab", tabs)

if selected_tab == "🌐 Web Research":
    render_web_research_tab()
```

### Custom Processing

```python
from cognitive_web_research import WebResearchModule

# Initialize module
web_research = WebResearchModule()

# Process URL
content = web_research.scrape_url("https://example.com")
chunks = web_research.chunk_text(content['content'])
embeddings = web_research.embed_chunks(chunks)
web_research.store_in_brain("https://example.com", chunks, embeddings)

# Ask question
answer = web_research.answer_query("What is the main topic?")
print(answer)
```

## 🔧 Customization

### Custom Text Processing

```python
def custom_preprocess_text(self, text: str) -> str:
    # Add your custom preprocessing logic
    text = text.lower()  # Convert to lowercase
    text = re.sub(r'\d+', '[NUMBER]', text)  # Replace numbers
    return text
```

### Custom Chunking Strategy

```python
def custom_chunk_text(self, text: str) -> List[Dict]:
    # Split by paragraphs instead of word count
    paragraphs = text.split('\n\n')
    chunks = []
    for i, para in enumerate(paragraphs):
        if len(para.strip()) > 50:  # Only include substantial paragraphs
            chunks.append({
                'text': para.strip(),
                'chunk_id': f"para_{i}",
                'chunk_index': i
            })
    return chunks
```

## 📁 File Structure

```
cognitive_nexus_ai/
├── cognitive_web_research.py          # Main module
├── test_web_research_module.py        # Test script
├── requirements_web_research.txt      # Dependencies
├── WEB_RESEARCH_INTEGRATION_GUIDE.md  # This guide
└── ai_system/
    └── knowledge_bank/
        └── web_brain/                 # Vector database storage
            ├── vector_index.faiss     # FAISS index
            ├── metadata.json          # URL metadata
            └── chunks.json            # Text chunks
```

## 🚨 Troubleshooting

### Common Issues

**1. Import Errors**
```bash
# Install missing dependencies
pip install sentence-transformers faiss-cpu
```

**2. Memory Issues**
```python
# Reduce chunk size
chunks = web_research.chunk_text(text, target_size=500, overlap=100)
```

**3. Slow Embeddings**
```python
# Use smaller model
self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
```

**4. FAISS Errors**
```bash
# Reinstall FAISS
pip uninstall faiss-cpu
pip install faiss-cpu
```

### Performance Tips

- **Use smaller embedding models** for faster processing
- **Reduce chunk overlap** to save storage space
- **Limit concurrent URL processing** to avoid memory issues
- **Use HNSW index** for faster retrieval on large datasets

## 🎉 Ready to Use!

The Web Research Module is production-ready and can be integrated into your Cognitive Nexus AI app immediately. Just follow the integration steps above and customize as needed for your specific use case.

**Happy researching!** 🚀