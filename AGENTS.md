# Cognitive Nexus AI Agents

## Overview
Cognitive Nexus employs multiple specialized AI agents working together to provide reality-first research and conversation capabilities. Each agent has specific roles, expertise, and interaction patterns.

## Core Agents

### Nexus Core Router
**File**: `modules/nexus_core.py`
**Role**: Central orchestration and request routing
**Capabilities**:
- Analyzes user requests for intent and complexity
- Routes to appropriate specialized agents
- Manages conversation context and memory
- Optimizes for performance vs. depth

**Decision Logic**:
- Casual chat → Fast, simple responses
- Research queries → Reality-First Research Agent
- Technical questions → Provider routing with technical models
- Creative tasks → Creative model routing

### Reality-First Research Agent
**File**: `modules/reality_research_agent.py`
**Role**: Grounded research with verdict quality assessment
**Capabilities**:
- Orchestrates multi-source research
- Applies reality constraints before generation
- Generates verdicts on topic feasibility
- Scores source trust and reliability

**Verdict Types**:
- **Feasible**: Topic can be researched with current knowledge
- **Speculative**: Requires assumptions but possible
- **Impossible**: Contradicts known reality
- **Fiction**: Appropriate for creative writing only

### Bloodhound Search Agent
**File**: `search/bloodhound_search.py`
**Role**: Deep web search and data retrieval
**Capabilities**:
- Multi-engine web search (Google, Bing, DuckDuckGo)
- Link following and recursive discovery
- Source categorization and trust scoring
- Cache management and performance optimization

**Search Modes**:
- **Quick**: Fast overview search
- **Standard**: Balanced depth and speed
- **Deep**: Comprehensive research
- **Extreme**: Maximum depth with extensive following

### Reality Grounding Agent
**File**: `core/reality_grounding.py`
**Role**: Fact-checking and hallucination detection
**Capabilities**:
- Claims extraction from AI responses
- Contradiction detection across sources
- Confidence scoring and uncertainty notes
- Epistemic mode enforcement (fact vs. fiction)

**Audit Types**:
- **Confidence**: Overall reliability assessment
- **Hallucination**: Detection of fabricated information
- **Speculation**: Identification of unproven claims
- **Source Grounding**: Verification against trusted sources

## Provider Agents

### Ollama Provider
**Role**: Local AI model management
**Models**:
- llama3.2:3b (fast, default)
- llama3.1:8b (balanced)
- mistral:7b (technical)
- codellama:13b (coding)
- Custom fine-tuned models

### Fallback Providers
**OpenAI**: GPT-4, GPT-3.5-turbo
**Anthropic**: Claude-3 models
**HuggingFace Local**: Additional local models

## Specialized Agents

### Context Manager
**File**: `modules/context_manager.py`
**Role**: Conversation memory and adaptation
**Capabilities**:
- Maintains chat history and context
- Learns user preferences and patterns
- Provides relevant memory injection
- Manages token limits and context windows

### Image Generation Agent
**Integration**: ComfyUI workflow management
**Role**: AI-powered image creation
**Capabilities**:
- Text-to-image generation
- Style transfer and customization
- Batch processing and gallery management

### Adaptive Memory Agent
**Role**: Long-term learning and personalization
**Capabilities**:
- User profile building
- Fact extraction and storage
- Memory candidate generation
- Feedback learning from interactions

## Agent Interaction Patterns

### Research Workflow
1. **User Query** → Nexus Router
2. **Intent Analysis** → Route to Research Agent
3. **Reality Check** → Grounding Agent pre-check
4. **Source Search** → Bloodhound Agent
5. **Trust Scoring** → Grounding Agent verification
6. **Verdict Generation** → Research Agent synthesis
7. **Response** → Formatted with sources and confidence

### Chat Workflow
1. **User Message** → Nexus Router
2. **Context Retrieval** → Memory Agent
3. **Model Selection** → Provider Router
4. **Response Generation** → AI Model
5. **Grounding Audit** → Reality Check (if enabled)
6. **Memory Update** → Learning from interaction

## Configuration

### Router Configuration
- `god_mode`: Enhanced routing specificity
- `freedom_level`: Response detail control
- `use_llm_classifier`: AI-assisted routing

### Research Configuration
- `reality_research_enabled`: Agent activation
- `bloodhound_depth`: Search thoroughness
- `max_search_results`: Result limits
- `enable_link_following`: Recursive search

### Grounding Configuration
- `enable_reality_grounding`: Audit activation
- `epistemic_mode`: Fact vs. fiction constraints
- `show_grounding_notes`: User-visible uncertainty

## Development Notes

### Adding New Agents
1. Create agent class in appropriate module
2. Register with Nexus Core router
3. Add configuration options
4. Update AGENTS.md documentation
5. Add unit tests

### Agent Communication
- Agents communicate via structured data (dataclasses)
- Shared state through session management
- Event-driven updates for real-time features

### Performance Considerations
- Local models prioritized for speed
- Caching reduces redundant operations
- Async processing for long-running tasks
- Granular timing for optimization

## Future Agent Expansions

### Planned Agents
- **Code Review Agent**: Automated code analysis
- **Data Analysis Agent**: Statistical and visualization
- **Translation Agent**: Multi-language support
- **Creative Writing Agent**: Enhanced fiction generation

### Integration Opportunities
- **External APIs**: Weather, finance, news
- **Database Agents**: SQL and NoSQL integration
- **IoT Agents**: Hardware control and monitoring
- **Collaborative Agents**: Multi-user research sessions

## Self-Improvement Workflow

**Installed Skill**: `skills/self-improvement/SKILL.md`
**Learning Logs**: `.learnings/LEARNINGS.md`, `.learnings/ERRORS.md`, `.learnings/FEATURE_REQUESTS.md`

Use the self-improvement workflow when a command fails unexpectedly, a user correction changes project understanding, a missing capability is requested, or a reusable development pattern is discovered.

Before major project work, review `.learnings/` for relevant pending items. After non-obvious fixes, log the discovery with the skill's entry format and promote durable project conventions back into `AGENTS.md` when they should guide future agents.
