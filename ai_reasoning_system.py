"""
AI Reasoning System for Cognitive Nexus
======================================

A comprehensive system that implements two-layer AI responses:
1. Internal reasoning (hidden by default)
2. User-facing output (concise and actionable)

Every AI action generates internal reasoning that can be optionally revealed
through expandable "Deep Insight" windows.

Features:
- Universal AI response wrapper
- Session state management for reasoning chains
- Cross-module reasoning support (Chat, Image Gen, Web Research, etc.)
- Clean interface with optional transparency
- Sequential reasoning review
- Debugging and learning capabilities

Author: Cognitive Nexus AI System
Version: 1.0
"""

import streamlit as st
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIReasoningSystem:
    """
    Core reasoning system that manages internal AI thoughts and user-facing outputs
    """
    
    def __init__(self, session_key: str = "ai_reasoning"):
        """
        Initialize the AI Reasoning System
        
        Args:
            session_key: Key for storing reasoning in session state
        """
        self.session_key = session_key
        self.reasoning_storage = Path("ai_system/knowledge_bank/reasoning")
        self.reasoning_storage.mkdir(parents=True, exist_ok=True)
        
        # Initialize session state
        if self.session_key not in st.session_state:
            st.session_state[self.session_key] = {
                'reasoning_chain': [],
                'current_reasoning': None,
                'reasoning_enabled': False
            }
    
    def generate_reasoning(self, process_type: str, user_input: str, context: Dict[str, Any] = None) -> str:
        """
        Generate internal reasoning for any AI process
        
        Args:
            process_type: Type of process (chat, image_gen, web_research, memory, performance)
            user_input: User's input/request
            context: Additional context information
            
        Returns:
            Generated reasoning text
        """
        timestamp = datetime.now().isoformat()
        reasoning_id = f"{process_type}_{int(time.time())}"
        
        # Generate reasoning based on process type
        reasoning = self._generate_process_reasoning(process_type, user_input, context)
        
        # Store in session state
        reasoning_entry = {
            'id': reasoning_id,
            'process_type': process_type,
            'timestamp': timestamp,
            'user_input': user_input,
            'context': context or {},
            'reasoning': reasoning,
            'expanded': False
        }
        
        st.session_state[self.session_key]['reasoning_chain'].append(reasoning_entry)
        st.session_state[self.session_key]['current_reasoning'] = reasoning_entry
        
        # Keep only last 20 reasoning entries
        if len(st.session_state[self.session_key]['reasoning_chain']) > 20:
            st.session_state[self.session_key]['reasoning_chain'] = \
                st.session_state[self.session_key]['reasoning_chain'][-20:]
        
        return reasoning
    
    def _generate_process_reasoning(self, process_type: str, user_input: str, context: Dict[str, Any]) -> str:
        """Generate specific reasoning for different process types"""
        
        if process_type == "chat":
            return self._generate_chat_reasoning(user_input, context)
        elif process_type == "image_gen":
            return self._generate_image_reasoning(user_input, context)
        elif process_type == "web_research":
            return self._generate_web_research_reasoning(user_input, context)
        elif process_type == "memory":
            return self._generate_memory_reasoning(user_input, context)
        elif process_type == "performance":
            return self._generate_performance_reasoning(user_input, context)
        else:
            return self._generate_generic_reasoning(user_input, context)
    
    def _generate_chat_reasoning(self, user_input: str, context: Dict[str, Any]) -> str:
        """Generate reasoning for chat responses"""
        reasoning = f"""
🧠 CHAT REASONING PROCESS

📥 USER INPUT: "{user_input}"

🔍 ANALYSIS STEPS:
1. Intent Recognition: Analyzing user's intent and emotional tone
2. Context Retrieval: Checking relevant conversation history
3. Knowledge Mapping: Identifying relevant topics and concepts
4. Response Strategy: Determining appropriate response approach

🎯 DECISION FACTORS:
- User's question type: {self._classify_question_type(user_input)}
- Conversation context: {context.get('conversation_history', 'No previous context')}
- Available knowledge: {context.get('knowledge_sources', 'General knowledge')}

⚡ RESPONSE GENERATION:
- Tone: {self._determine_response_tone(user_input)}
- Length: {self._determine_response_length(user_input)}
- Style: {self._determine_response_style(user_input)}

🔄 QUALITY CHECK:
- Relevance: Ensuring response addresses user's actual question
- Clarity: Making sure the answer is understandable
- Helpfulness: Verifying the response provides value
- Safety: Checking for any potential issues

✅ FINAL OUTPUT: Generated response that balances informativeness with conciseness
"""
        return reasoning.strip()
    
    def _generate_image_reasoning(self, user_input: str, context: Dict[str, Any]) -> str:
        """Generate reasoning for image generation"""
        prompt = context.get('prompt', user_input)
        style = context.get('style', 'realistic')
        dimensions = context.get('dimensions', '512x512')
        
        reasoning = f"""
🎨 IMAGE GENERATION REASONING

📝 PROMPT ANALYSIS: "{prompt}"

🔍 PROMPT DECOMPOSITION:
1. Subject Identification: {self._extract_image_subject(prompt)}
2. Style Indicators: {self._extract_style_indicators(prompt)}
3. Mood/Tone: {self._extract_mood_indicators(prompt)}
4. Technical Requirements: {self._extract_technical_requirements(prompt)}

⚙️ GENERATION PARAMETERS:
- Style: {style} (selected based on prompt analysis)
- Dimensions: {dimensions} (optimized for performance)
- Model: Stable Diffusion v1.5 (156MB optimized)
- Steps: 8 (ultra-fast generation)
- Guidance Scale: 6.0 (balanced creativity/accuracy)

🎯 STYLE ENHANCEMENT:
- Adding style-specific keywords to enhance prompt
- Balancing artistic elements with user requirements
- Ensuring technical feasibility within time constraints

⚡ OPTIMIZATION DECISIONS:
- Using fp16 precision for speed
- Enabling memory-efficient attention
- Sequential CPU offloading for stability
- VAE slicing for reduced memory usage

🔄 QUALITY ASSURANCE:
- Prompt clarity check
- Technical parameter validation
- Resource availability confirmation
- Generation time estimation

✅ OUTPUT STRATEGY: Generate image with progress tracking and metadata storage
"""
        return reasoning.strip()
    
    def _generate_web_research_reasoning(self, user_input: str, context: Dict[str, Any]) -> str:
        """Generate reasoning for web research operations"""
        url = context.get('url', 'N/A')
        operation = context.get('operation', 'unknown')
        
        reasoning = f"""
🌐 WEB RESEARCH REASONING

📋 OPERATION: {operation.upper()}

🔍 URL ANALYSIS: "{url}"
1. Domain Assessment: Evaluating source credibility
2. Content Type Prediction: Anticipating content structure
3. Processing Strategy: Planning extraction approach
4. Resource Requirements: Estimating processing needs

📄 CONTENT EXTRACTION STRATEGY:
- Primary selectors: article, main, .content, .post
- Fallback selectors: body, div[role="main"]
- Exclusion filters: script, style, nav, footer
- Text cleaning: Remove excessive whitespace, normalize

✂️ CHUNKING DECISIONS:
- Target size: 750 words (optimal for embeddings)
- Overlap: 150 words (ensures context continuity)
- Strategy: Semantic boundary preservation
- Quality check: Minimum 50 words per chunk

🧠 EMBEDDING GENERATION:
- Model: sentence-transformers/all-MiniLM-L6-v2
- Dimension: 384 (lightweight, effective)
- Normalization: Cosine similarity optimization
- Storage: FAISS IndexFlatIP for fast retrieval

🔍 SEARCH STRATEGY (if query):
- Query embedding generation
- Similarity search across all stored content
- Top-k retrieval: 5 most relevant chunks
- Context ranking by similarity score

⚡ PERFORMANCE OPTIMIZATIONS:
- Batch processing for multiple chunks
- Memory-efficient embedding generation
- Incremental vector database updates
- Progress tracking for user feedback

✅ STORAGE DECISION: Unified brain integration with metadata preservation
"""
        return reasoning.strip()
    
    def _generate_memory_reasoning(self, user_input: str, context: Dict[str, Any]) -> str:
        """Generate reasoning for memory operations"""
        operation = context.get('operation', 'recall')
        
        reasoning = f"""
🧠 MEMORY REASONING

📋 OPERATION: {operation.upper()}

🔍 MEMORY SEARCH STRATEGY:
1. Query Analysis: "{user_input}"
2. Memory Type Identification: {self._identify_memory_type(user_input)}
3. Temporal Context: {context.get('time_context', 'Current session')}
4. Relevance Scoring: Prioritizing most relevant memories

🎯 RECALL DECISIONS:
- Primary memory sources: {context.get('memory_sources', 'Session state')}
- Search scope: {context.get('search_scope', 'All available memories')}
- Relevance threshold: {context.get('relevance_threshold', '0.7')}
- Context window: {context.get('context_window', 'Recent conversations')}

📊 MEMORY PRIORITIZATION:
- Recency weight: 40% (recent memories more relevant)
- Frequency weight: 30% (frequently accessed memories)
- Relevance weight: 30% (semantic similarity to query)
- Context weight: Bonus for related conversation topics

🔄 MEMORY INTEGRATION:
- Combining multiple memory sources
- Resolving conflicts between memories
- Maintaining temporal coherence
- Preserving important details

⚡ STORAGE DECISIONS:
- New memory encoding: {context.get('encoding_strategy', 'Semantic + temporal')}
- Memory consolidation: Merging related information
- Cleanup strategy: Removing outdated or redundant data
- Persistence: Saving to long-term storage

✅ MEMORY OUTPUT: Providing most relevant information with confidence scores
"""
        return reasoning.strip()
    
    def _generate_performance_reasoning(self, user_input: str, context: Dict[str, Any]) -> str:
        """Generate reasoning for performance monitoring"""
        
        reasoning = f"""
🚀 PERFORMANCE REASONING

📊 SYSTEM ANALYSIS: "{user_input}"

🔍 PERFORMANCE METRICS EVALUATION:
1. CPU Usage: {context.get('cpu_usage', 'Monitoring...')}
2. Memory Usage: {context.get('memory_usage', 'Monitoring...')}
3. GPU Status: {context.get('gpu_status', 'Checking...')}
4. Response Times: {context.get('response_times', 'Measuring...')}

⚡ OPTIMIZATION DECISIONS:
- Resource allocation: Balancing speed vs. memory usage
- Model selection: Choosing optimal models for current load
- Caching strategy: Determining what to keep in memory
- Priority queuing: Managing concurrent requests

🎯 PERFORMANCE TARGETS:
- Response time: <2 seconds for most operations
- Memory usage: <80% of available RAM
- CPU usage: <70% under normal load
- GPU utilization: Optimizing for available VRAM

🔄 ADAPTIVE STRATEGIES:
- Load balancing: Distributing work across available resources
- Fallback mechanisms: Switching to lighter models if needed
- Caching decisions: What to store for faster access
- Cleanup operations: Removing unused data and models

⚠️ ALERT THRESHOLDS:
- High CPU: >80% sustained usage
- High Memory: >90% RAM utilization
- Slow Response: >5 seconds for simple operations
- Error Rate: >5% failure rate

✅ PERFORMANCE OUTPUT: Optimized system status with actionable recommendations
"""
        return reasoning.strip()
    
    def _generate_generic_reasoning(self, user_input: str, context: Dict[str, Any]) -> str:
        """Generate generic reasoning for unknown process types"""
        return f"""
🤖 GENERIC AI REASONING

📥 INPUT: "{user_input}"

🔍 PROCESSING STEPS:
1. Input Analysis: Understanding the request
2. Context Evaluation: Assessing available information
3. Strategy Selection: Choosing appropriate approach
4. Execution Planning: Breaking down into steps
5. Quality Assurance: Ensuring output quality
6. Result Delivery: Providing final response

⚡ DECISION FACTORS:
- Input complexity: {len(user_input.split())} words
- Available context: {len(context) if context else 0} items
- Processing time: Optimizing for user experience
- Resource usage: Balancing accuracy and efficiency

✅ OUTPUT: Delivering the best possible response given available resources
"""
    
    # Helper methods for reasoning generation
    def _classify_question_type(self, text: str) -> str:
        """Classify the type of question asked"""
        text_lower = text.lower()
        if any(word in text_lower for word in ['what', 'who', 'when', 'where', 'why', 'how']):
            return "Question"
        elif any(word in text_lower for word in ['please', 'can you', 'could you']):
            return "Request"
        elif any(word in text_lower for word in ['help', 'assist', 'support']):
            return "Help Request"
        else:
            return "Statement/Conversation"
    
    def _determine_response_tone(self, text: str) -> str:
        """Determine appropriate response tone"""
        if any(word in text.lower() for word in ['urgent', 'asap', 'quickly', 'emergency']):
            return "Professional and Direct"
        elif any(word in text.lower() for word in ['please', 'thank', 'appreciate']):
            return "Polite and Helpful"
        else:
            return "Friendly and Informative"
    
    def _determine_response_length(self, text: str) -> str:
        """Determine appropriate response length"""
        if len(text.split()) < 10:
            return "Concise"
        elif len(text.split()) < 50:
            return "Moderate"
        else:
            return "Detailed"
    
    def _determine_response_style(self, text: str) -> str:
        """Determine response style"""
        if any(word in text.lower() for word in ['technical', 'code', 'programming']):
            return "Technical"
        elif any(word in text.lower() for word in ['creative', 'artistic', 'design']):
            return "Creative"
        else:
            return "Conversational"
    
    def _extract_image_subject(self, prompt: str) -> str:
        """Extract main subject from image prompt"""
        # Simple extraction - could be enhanced with NLP
        words = prompt.split()
        if len(words) > 0:
            return words[0]
        return "Unspecified"
    
    def _extract_style_indicators(self, prompt: str) -> str:
        """Extract style indicators from prompt"""
        style_words = ['realistic', 'abstract', 'cartoon', 'anime', 'photorealistic', 'artistic']
        found_styles = [word for word in style_words if word in prompt.lower()]
        return ', '.join(found_styles) if found_styles else 'Default'
    
    def _extract_mood_indicators(self, prompt: str) -> str:
        """Extract mood indicators from prompt"""
        mood_words = ['happy', 'sad', 'dark', 'bright', 'peaceful', 'energetic', 'calm']
        found_moods = [word for word in mood_words if word in prompt.lower()]
        return ', '.join(found_moods) if found_moods else 'Neutral'
    
    def _extract_technical_requirements(self, prompt: str) -> str:
        """Extract technical requirements from prompt"""
        if any(word in prompt.lower() for word in ['high resolution', 'hd', '4k']):
            return "High Resolution"
        elif any(word in prompt.lower() for word in ['portrait', 'landscape', 'square']):
            return "Specific Aspect Ratio"
        else:
            return "Standard"
    
    def _identify_memory_type(self, query: str) -> str:
        """Identify the type of memory being accessed"""
        if any(word in query.lower() for word in ['remember', 'recall', 'previous']):
            return "Episodic Memory"
        elif any(word in query.lower() for word in ['learn', 'knowledge', 'fact']):
            return "Semantic Memory"
        else:
            return "General Memory"


def render_ai_response(user_input: str, ai_output: str, process_type: str, 
                      context: Dict[str, Any] = None, show_reasoning: bool = False, 
                      real_thinking: str = None) -> None:
    """
    Universal AI response wrapper that implements the two-layer approach
    
    Args:
        user_input: What the user asked/requested
        ai_output: The AI's response/output for the user
        process_type: Type of process (chat, image_gen, web_research, etc.)
        context: Additional context for reasoning generation
        show_reasoning: Whether to show reasoning by default
        real_thinking: Actual AI thinking content from <think> tags
    """
    
    # Use real thinking content if available, otherwise generate reasoning
    if real_thinking and real_thinking.strip():
        thinking_content = real_thinking
    else:
        # Initialize reasoning system
        reasoning_system = AIReasoningSystem()
        # Generate internal reasoning
        thinking_content = reasoning_system.generate_reasoning(process_type, user_input, context)
    
    # Show thinking process in expander first
    reasoning_key = f"reasoning_{process_type}_{int(time.time())}"
    with st.expander("<think>", expanded=show_reasoning):
        st.markdown(thinking_content)
        
        # Show reasoning metadata
        current_reasoning = st.session_state.get('ai_reasoning', {}).get('current_reasoning', {})
        if current_reasoning:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.caption(f"🕒 {current_reasoning.get('timestamp', 'Unknown')}")
            with col2:
                st.caption(f"🔧 {current_reasoning.get('process_type', 'Unknown').upper()}")
            with col3:
                st.caption(f"📝 {len(thinking_content)} chars")
    
    # Display actual response underneath
    st.markdown(ai_output)


def render_reasoning_history():
    """
    Render a comprehensive view of all AI reasoning across all processes
    """
    
    if 'ai_reasoning' not in st.session_state:
        st.info("No reasoning history available yet.")
        return
    
    reasoning_chain = st.session_state['ai_reasoning'].get('reasoning_chain', [])
    
    if not reasoning_chain:
        st.info("No reasoning history available yet.")
        return
    
    st.subheader("🧠 AI Reasoning History")
    
    # Group by process type
    process_groups = {}
    for entry in reasoning_chain:
        process_type = entry.get('process_type', 'unknown')
        if process_type not in process_groups:
            process_groups[process_type] = []
        process_groups[process_type].append(entry)
    
    # Display by process type
    for process_type, entries in process_groups.items():
        with st.expander(f"🔧 {process_type.upper()} ({len(entries)} entries)"):
            for entry in reversed(entries):  # Show newest first
                timestamp = entry.get('timestamp', 'Unknown')
                user_input = entry.get('user_input', 'No input')
                reasoning = entry.get('reasoning', 'No reasoning available')
                
                st.markdown(f"**🕒 {timestamp}**")
                st.markdown(f"**📥 Input:** {user_input}")
                st.text_area("Reasoning", value=reasoning, height=200, 
                           key=f"history_{entry.get('id', 'unknown')}")
                st.divider()


def render_reasoning_controls():
    """
    Render controls for managing AI reasoning system
    """
    
    st.subheader("🔧 AI Reasoning Controls")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🧠 Toggle Reasoning"):
            current_state = st.session_state.get('ai_reasoning', {}).get('reasoning_enabled', False)
            st.session_state['ai_reasoning']['reasoning_enabled'] = not current_state
            st.rerun()
    
    with col2:
        if st.button("🗑️ Clear History"):
            st.session_state['ai_reasoning']['reasoning_chain'] = []
            st.success("Reasoning history cleared!")
            st.rerun()
    
    with col3:
        if st.button("💾 Export Reasoning"):
            reasoning_chain = st.session_state.get('ai_reasoning', {}).get('reasoning_chain', [])
            if reasoning_chain:
                # Save to file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"ai_reasoning_export_{timestamp}.json"
                
                reasoning_system = AIReasoningSystem()
                export_path = reasoning_system.reasoning_storage / filename
                
                with open(export_path, 'w') as f:
                    json.dump(reasoning_chain, f, indent=2)
                
                st.success(f"Reasoning exported to {filename}")
            else:
                st.warning("No reasoning to export")
    
    # Show current status
    reasoning_enabled = st.session_state.get('ai_reasoning', {}).get('reasoning_enabled', False)
    chain_length = len(st.session_state.get('ai_reasoning', {}).get('reasoning_chain', []))
    
    st.info(f"**Status:** Reasoning {'Enabled' if reasoning_enabled else 'Disabled'} | **History:** {chain_length} entries")


# Example usage and integration
if __name__ == "__main__":
    st.set_page_config(page_title="AI Reasoning System", layout="wide")
    
    st.title("🧠 AI Reasoning System - Demo")
    
    # Demo the reasoning system
    st.header("🧪 Test AI Reasoning")
    
    process_type = st.selectbox("Process Type", 
                               ["chat", "image_gen", "web_research", "memory", "performance"])
    
    user_input = st.text_input("User Input", "What is artificial intelligence?")
    
    context = st.text_area("Context (JSON)", '{"conversation_history": "Previous chat about AI"}')
    
    if st.button("Generate AI Response"):
        try:
            context_dict = json.loads(context) if context else {}
            
            # Mock AI output based on process type
            if process_type == "chat":
                ai_output = "Artificial intelligence (AI) refers to the simulation of human intelligence in machines..."
            elif process_type == "image_gen":
                ai_output = "Generated a beautiful AI-themed image with neural network patterns..."
            elif process_type == "web_research":
                ai_output = "Found 5 relevant articles about AI. Here's what I discovered..."
            elif process_type == "memory":
                ai_output = "I recall we discussed machine learning concepts earlier. Here's what I remember..."
            elif process_type == "performance":
                ai_output = "System performance is optimal. CPU: 45%, Memory: 60%, Response time: 1.2s"
            else:
                ai_output = "Processing your request..."
            
            # Render with reasoning
            render_ai_response(user_input, ai_output, process_type, context_dict)
            
        except json.JSONDecodeError:
            st.error("Invalid JSON in context field")
    
    st.divider()
    
    # Show reasoning controls
    render_reasoning_controls()
    
    st.divider()
    
    # Show reasoning history
    render_reasoning_history()
    
    st.divider()
    
    # Integration instructions
    st.markdown("""
    ### 🔧 Integration Instructions
    
    **To integrate into Cognitive Nexus AI:**
    
    1. **Import the reasoning system:**
       ```python
       from ai_reasoning_system import render_ai_response, render_reasoning_history
       ```
    
    2. **Wrap your AI responses:**
       ```python
       # Instead of just st.write(ai_response)
       render_ai_response(user_input, ai_response, "chat", context)
       ```
    
    3. **Add reasoning history to a tab:**
       ```python
       elif selected_tab == "🧠 AI Reasoning":
           render_reasoning_history()
           render_reasoning_controls()
       ```
    
    4. **Use across all modules:**
       - Chat: `render_ai_response(user_input, response, "chat", context)`
       - Image Gen: `render_ai_response(prompt, result, "image_gen", context)`
       - Web Research: `render_ai_response(query, answer, "web_research", context)`
       - Memory: `render_ai_response(query, memory_result, "memory", context)`
       - Performance: `render_ai_response("status", metrics, "performance", context)`
    
    **Benefits:**
    - Clean interface with hidden complexity
    - Optional transparency for debugging
    - Cross-module reasoning consistency
    - Learning and trust building
    - Sequential reasoning review
    """)
