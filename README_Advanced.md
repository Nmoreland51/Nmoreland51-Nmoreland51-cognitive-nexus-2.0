# 🧠 Cognitive Nexus AI - Advanced Multi-Tab Interface

A comprehensive self-hosted, privacy-focused AI assistant with an advanced multi-tab interface featuring six specialized tabs and comprehensive sidebar controls.

## ✨ Features

### 🎯 Six Specialized Tabs

1. **💬 Chat** - Interactive conversation with AI
2. **🎨 Image Generation** - Create images from text prompts  
3. **🧠 Memory & Knowledge** - Manage AI memory and knowledge base
4. **🌐 Web Research** - Search the web for real-time information
5. **🚀 Performance** - Monitor system performance and metrics
6. **📖 Tutorial** - Interactive help and guidance

### 🔧 Advanced Sidebar Controls

- **🤖 AI Provider Settings** - Choose between Ollama, Anthropic, OpenAI, or local models
- **⚙️ Generation Settings** - Adjust temperature, max tokens, and response parameters
- **🔧 Feature Toggles** - Enable/disable learning, web search, and image generation
- **🧠 Memory Settings** - Configure retention periods and memory management
- **🔍 Search Settings** - Customize search behavior and result counts
- **📈 Performance Metrics** - Real-time system monitoring and statistics

### 🏗️ Architecture

- **Modular Design** - Each tab functions as an independent mini-application
- **Shared Backend Services** - Centralized services for all tabs
- **Session State Management** - Persistent state across tab switches
- **Real-time Updates** - Live metrics and status indicators
- **Privacy-Focused** - Local processing with optional cloud integration

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements_advanced.txt
   ```

2. **Run the application:**
   ```bash
   python -m streamlit run cognitive_nexus_advanced.py --server.port 8504
   ```

3. **Or use the launcher:**
   ```bash
   .\run_advanced_cognitive_nexus.bat
   ```

4. **Open your browser to:** `http://localhost:8504`

## 📋 Tab Descriptions

### 💬 Chat Tab
- Interactive conversation interface
- Real-time AI responses
- Context-aware conversations
- Memory integration
- Performance tracking

### 🎨 Image Generation Tab
- Text-to-image generation
- Multiple artistic styles
- Size customization
- Generation history
- Style selection

### 🧠 Memory & Knowledge Tab
- **Knowledge Base Management** - Add, search, and organize custom knowledge
- **Conversation History** - View and manage past conversations
- **Memory Settings** - Configure retention and cleanup policies
- **Search Functionality** - Find relevant information from memory

### 🌐 Web Research Tab
- Real-time web search
- Multiple search providers
- Result processing and summarization
- Search history tracking
- Performance metrics

### 🚀 Performance Tab
- Real-time system metrics
- Response time monitoring
- Success rate tracking
- Memory usage statistics
- System information display

### 📖 Tutorial Tab
- Interactive help system
- Step-by-step guidance
- Progress tracking
- Quick tips and best practices
- Feature explanations

## ⚙️ Configuration

### AI Provider Settings

- **Ollama** - Local LLM support (recommended for privacy)
- **Anthropic** - Cloud-based Claude models
- **OpenAI** - GPT models via API
- **Local** - Custom local implementations

### Generation Settings

- **Temperature** (0.0-2.0) - Controls response randomness
- **Max Tokens** (100-2000) - Maximum response length
- **Model Selection** - Choose specific models per provider

### Feature Toggles

- **🧠 Learning Mode** - Enable conversation learning and memory
- **🌐 Web Search** - Enable real-time web search capabilities
- **🎨 Image Generation** - Enable image creation features

### Memory Settings

- **Retention Period** (1-365 days) - How long to keep conversation history
- **Knowledge Management** - Add and organize custom knowledge
- **Memory Cleanup** - Automatic cleanup of old data

## 🔧 Backend Services

### WebSearchService
- DuckDuckGo API integration
- Result processing and filtering
- Error handling and fallbacks
- Performance monitoring

### MemorySystem
- Conversation storage and retrieval
- Knowledge base management
- Context extraction
- Data persistence

### ImageGenerationService
- Text-to-image generation (placeholder)
- Style selection
- Size customization
- Generation history

### PerformanceMonitor
- Real-time metrics collection
- Response time tracking
- Success rate monitoring
- System resource usage

### KnowledgeManager
- Knowledge base operations
- Search and retrieval
- Relevance scoring
- Content organization

## 📊 Session State Management

The application maintains comprehensive session state including:

- **Messages** - Chat conversation history
- **Settings** - All user preferences and configurations
- **Performance Metrics** - Real-time system statistics
- **Memory Data** - Knowledge base and conversation history
- **System Status** - Service availability and health
- **Tutorial Progress** - Help system completion tracking

## 🎨 UI Features

### Responsive Design
- Wide layout optimized for multi-tab interface
- Sidebar with comprehensive controls
- Dark/light theme support
- Mobile-friendly responsive design

### Real-time Updates
- Live performance metrics
- Dynamic status indicators
- Progress bars and spinners
- Auto-refreshing data

### Interactive Elements
- Tab-based navigation
- Form-based inputs
- Expandable sections
- Progress tracking

## 🔒 Privacy Features

- **Local Processing** - All AI inference happens locally when using Ollama
- **No Data Sharing** - Conversations stored locally only
- **User Control** - Full control over data retention and learning
- **Graceful Degradation** - Works offline with built-in knowledge base

## 🛠️ Development

### Adding New Tabs

1. Create a new tab function following the pattern:
   ```python
   def render_new_tab():
       st.markdown("### 🆕 New Tab")
       # Tab content here
   ```

2. Add the tab to the main tabs list:
   ```python
   tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
       "💬 Chat",
       "🎨 Image Generation", 
       "🧠 Memory & Knowledge",
       "🌐 Web Research",
       "🚀 Performance",
       "📖 Tutorial",
       "🆕 New Tab"  # Add here
   ])
   ```

3. Add the tab content:
   ```python
   with tab7:
       render_new_tab()
   ```

### Extending Backend Services

Add new services to the `BackendServices` class:

```python
class BackendServices:
    def __init__(self):
        # Existing services
        self.web_search = WebSearchService()
        self.memory_system = MemorySystem()
        # Add new service
        self.new_service = NewService()
```

## 📁 File Structure

```
cognitive_nexus_advanced.py          # Main application
requirements_advanced.txt            # Python dependencies
run_advanced_cognitive_nexus.bat     # Windows launcher
README_Advanced.md                   # This documentation
data/                               # Auto-created data directory
├── knowledge_base.json             # Knowledge base storage
├── memory.json                     # Conversation memory
└── performance_logs.json           # Performance metrics
```

## 🚨 Troubleshooting

### Common Issues

1. **Port already in use:**
   - Change the port in the launcher script
   - Or use: `--server.port 8505`

2. **Dependencies missing:**
   - Run: `pip install -r requirements_advanced.txt`
   - Check Python version: `python --version`

3. **Memory issues:**
   - Reduce retention period in Memory Settings
   - Clear conversation history
   - Restart the application

### Performance Optimization

- Use local Ollama models for better privacy
- Adjust max tokens based on your needs
- Enable only necessary features
- Monitor performance metrics regularly

## 🤝 Contributing

This is a modular implementation designed for easy extension:

1. Fork or download the project
2. Make your modifications
3. Test thoroughly across all tabs
4. Share your improvements

## 📄 License

This project is provided as-is for educational and personal use. Please respect the terms of service of any external APIs or services used.

## 🙏 Acknowledgments

- **Streamlit** for the excellent web framework
- **DuckDuckGo** for privacy-focused search API
- **Ollama** for local LLM capabilities
- **Community** for feedback and contributions

---

**Cognitive Nexus AI - Advanced Multi-Tab Interface** 🧠✨

Your privacy-focused, intelligent assistant with advanced UI and comprehensive features.
