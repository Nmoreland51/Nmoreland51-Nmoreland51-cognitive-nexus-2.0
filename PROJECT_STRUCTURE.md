# Cognitive Nexus Project Structure

## Overview
Cognitive Nexus is a reality-first AI research platform built with Python, Streamlit, and Ollama. The project prioritizes factual accuracy, source verification, and user-friendly interfaces.

## Directory Structure

### Core Application
- `app.py` - Main Streamlit web application with tabbed interface
- `modules/` - Core business logic modules
  - `nexus_core.py` - Central routing and orchestration
  - `reality_research_agent.py` - Reality-first research with verdicts
  - `provider_router.py` - AI model provider management
  - `context_manager.py` - Conversation and memory management
- `core/` - Shared utilities and configurations
- `config/` - Configuration files and settings

### Research & Search
- `search/` - Web search and data retrieval
  - `bloodhound_search.py` - Deep web search engine
  - `reality_grounding.py` - Fact-checking and verification
- `web_research_module.py` - Web research integration

### AI & Learning
- `ai_reasoning_system.py` - Advanced reasoning capabilities
- `cognitive_nexus/` - AI personality and behavior
- `skills/` - Specialized AI capabilities

### Data & Storage
- `data/` - Persistent data storage
- `generated_images/` - AI-generated images
- `logs/` - Application logs

### Testing & Quality
- `tests/` - Unit tests and validation
- `audit/` - Code quality and security audits

### Build & Deployment
- `build/` - Build scripts and configurations
- `requirements.txt` - Python dependencies
- `setup.bat` / `complete_setup.ps1` - Setup scripts
- `launch.bat` / `run.py` - Launch scripts

### Documentation
- `README.md` - Main user documentation
- `QUICK_START.md` - Getting started guide
- `PACKAGING_GUIDE.md` - Build and deployment instructions
- Various integration guides in root

### Legacy (Archived)
- `legacy/` - Obsolete files and backups (kept for reference)

## Key Files

### Entry Points
- `app.py` - Web UI (main application)
- `run.py` - Command-line launcher
- `launch.bat` - Windows launcher

### Core Modules
- `modules/nexus_core.py` - Main orchestration
- `modules/reality_research_agent.py` - Research engine
- `search/bloodhound_search.py` - Web search
- `core/reality_grounding.py` - Fact verification

### Configuration
- `config/` - Runtime configurations
- `.env.example` - Environment variables template

## Architecture Principles

### Reality-First Design
- All research prioritizes factual accuracy
- Source trust scoring and verification
- Contradiction detection and resolution

### Modular Architecture
- Clean separation of concerns
- Pluggable providers and modules
- Extensible research agents

### User-Centric UI
- Streamlit-based web interface
- Advanced mode for developers
- Clean defaults with full access

### Performance Optimized
- Local AI models via Ollama
- Caching and memory management
- Granular performance timing

## Development Workflow

1. **Setup**: Run `complete_setup.ps1` or `setup.bat`
2. **Development**: Edit modules in `modules/`
3. **Testing**: Run `python -m unittest discover`
4. **Launch**: Use `launch.bat` or `python app.py`
5. **Build**: Use build scripts in `build/`

## Dependencies

### Core
- Python 3.8+
- Streamlit
- Ollama (local AI models)

### Research
- BeautifulSoup4, requests (web scraping)
- Newspaper3k (article extraction)

### Optional
- ComfyUI (image generation)
- OpenAI/Anthropic APIs (fallback providers)

See `requirements.txt` for full dependency list.</content>
<parameter name="filePath">c:\Users\Nmore\Downloads\Nmoreland51-cognitive-nexus-main\Nmoreland51-cognitive-nexus-main\PROJECT_STRUCTURE.md