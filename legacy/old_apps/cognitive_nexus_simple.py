"""
Cognitive Nexus AI - Simplified Version
=======================================
A streamlined version of the Cognitive Nexus AI that focuses on core functionality
without complex dependencies that might cause issues.
"""

import streamlit as st
import requests
import json
import os
import time
import random
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from typing import Dict, List, Optional, Tuple

# Set page configuration
st.set_page_config(
    page_title="Cognitive Nexus AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = f"session_{int(time.time())}"

class SimpleWebSearch:
    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]

    def search_web(self, query: str, max_results: int = 3) -> List[Dict]:
        results = []
        try:
            # DuckDuckGo search
            headers = {'User-Agent': random.choice(self.user_agents)}
            url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Process instant answer
            if data.get('Abstract'):
                results.append({
                    'title': data.get('Heading', 'Information'),
                    'snippet': data.get('Abstract', ''),
                    'url': data.get('AbstractURL', ''),
                    'source': data.get('AbstractSource', 'DuckDuckGo'),
                    'type': 'instant_answer',
                    'confidence': 0.9
                })

            # Process related topics
            for topic in data.get('RelatedTopics', [])[:max_results-1]:
                if isinstance(topic, dict) and topic.get('Text'):
                    title = topic.get('Text', '').split(' - ')[0] if ' - ' in topic.get('Text', '') else 'Related Information'
                    results.append({
                        'title': title,
                        'snippet': topic.get('Text', ''),
                        'url': topic.get('FirstURL', ''),
                        'source': 'DuckDuckGo',
                        'type': 'related_topic',
                        'confidence': 0.7
                    })

        except Exception as e:
            st.error(f"Search error: {e}")
            # Fallback response
            results.append({
                'title': f'Information about: {query}',
                'snippet': f'I understand you\'re asking about "{query}". While I cannot access real-time web search due to network limitations, I can provide information based on my knowledge.',
                'url': 'offline://general',
                'source': 'Cognitive Nexus AI Knowledge',
                'type': 'general_response',
                'confidence': 0.6
            })
        
        return results[:max_results]

class SimpleLearningSystem:
    def __init__(self):
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.knowledge_file = self.data_dir / "simple_knowledge.json"
        self.user_preferences = {}
        self._load_knowledge()

    def _load_knowledge(self):
        try:
            if self.knowledge_file.exists():
                with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.user_preferences = data.get('preferences', {})
        except:
            self.user_preferences = {}

    def save_knowledge(self):
        try:
            data = {
                'preferences': self.user_preferences,
                'last_updated': datetime.now().isoformat(),
                'version': 'simple'
            }
            with open(self.knowledge_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass

    def add_conversation(self, user_message: str, ai_response: str):
        # Extract preferences
        user_lower = user_message.lower().strip()
        preference_patterns = [('i like', 'preference'), ('i prefer', 'preference'), ('i enjoy', 'preference')]
        
        for pattern, pref_type in preference_patterns:
            if pattern in user_lower:
                key = f"{pref_type}_{len(self.user_preferences)}"
                self.user_preferences[key] = {
                    'type': pref_type,
                    'content': user_message,
                    'timestamp': datetime.now().isoformat()
                }
                break

        # Save periodically
        if len(self.user_preferences) % 3 == 0:
            self.save_knowledge()

class SimpleFallbackSystem:
    def __init__(self):
        self.defaults = {
            "what is your name": "I'm Cognitive Nexus AI, your privacy-focused AI assistant.",
            "who are you": "I'm an AI designed to help you find information and provide intelligent analysis while maintaining your privacy.",
            "what can you do": "I can search the web for current information, analyze content, remember our conversations, and provide explanations while keeping your data private.",
            "hello": "Hello! I'm here to help you with intelligent search, analysis, and conversation.",
            "hi": "Hi there! How can I assist you today?",
            "thanks": "You're welcome! I'm always here to help.",
            "goodbye": "Goodbye! I've learned from our conversation and look forward to helping you again."
        }

    def get_response(self, message: str) -> str:
        processed_query = message.lower().strip()
        
        # Check defaults
        if processed_query in self.defaults:
            return self.defaults[processed_query]
        
        # Pattern matching
        if any(pattern in processed_query for pattern in ['hello', 'hi', 'hey']):
            return "Hello! I'm Cognitive Nexus AI. How can I help you today?"
        
        if any(pattern in processed_query for pattern in ['what are you', 'who are you']):
            return "I'm a privacy-focused AI assistant that combines local processing with web search capabilities."
        
        if any(pattern in processed_query for pattern in ['what can you do', 'capabilities']):
            return "I can search for information, explain concepts, compare topics, and help with research while keeping your data completely private."
        
        # Default response
        keywords = [word for word in processed_query.split() if len(word) > 3]
        if keywords:
            main_topic = keywords[0]
            return f"I understand you're asking about {main_topic}. I can search for current information, provide explanations, or help with analysis. Could you clarify what specific aspect of {main_topic} you're most interested in?"
        
        return "I'm here to help with information search, analysis, and intelligent conversation. Could you provide a bit more detail about what you're looking for?"

class SimpleCognitiveNexus:
    def __init__(self):
        self.search_system = SimpleWebSearch()
        self.learning_system = SimpleLearningSystem()
        self.fallback_system = SimpleFallbackSystem()

    def should_use_web_search(self, message: str) -> Tuple[bool, str]:
        message_lower = message.lower().strip()
        
        simple_patterns = ['hello', 'hi', 'hey', 'what are you', 'who are you', 'thank you', 'thanks', 'goodbye']
        if any(pattern in message_lower for pattern in simple_patterns):
            return False, ""
        
        search_indicators = [
            'current', 'latest', 'recent', 'today', 'now', 'new', 'breaking', 'update', 'news',
            'what is', 'what are', 'how to', 'how do', 'when did', 'where is', 'why does',
            'explain', 'tell me about', 'information about', 'who is', 'who was', 'compare',
            'research', 'find', 'search', 'look up', 'details about', 'facts about'
        ]
        
        needs_search = (
            any(indicator in message_lower for indicator in search_indicators) or
            message.endswith('?') or
            len(message.split()) > 5
        )
        
        if needs_search:
            search_query = message.strip()
            prefixes_to_remove = ['what is', 'what are', 'how to', 'tell me about', 'explain']
            for prefix in prefixes_to_remove:
                if search_query.lower().startswith(prefix):
                    search_query = search_query[len(prefix):].strip()
                    break
            return True, search_query
        
        return False, ""

    def process_message(self, message: str) -> str:
        try:
            should_search, search_query = self.should_use_web_search(message)
            
            if should_search and search_query:
                response = self._handle_search_query(search_query)
            else:
                response = self._handle_local_query(message)
            
            self.learning_system.add_conversation(message, response)
            return response
            
        except Exception as e:
            return f"I apologize, but I encountered an issue processing your request: {e}"

    def _handle_search_query(self, query: str) -> str:
        try:
            search_results = self.search_system.search_web(query, max_results=3)
            
            if not search_results:
                return self.fallback_system.get_response(query)
            
            information_pieces = []
            sources_used = []
            
            for result in search_results:
                title = result.get('title', 'Information')
                snippet = result.get('snippet', '')
                url = result.get('url', '')
                source = result.get('source', 'Web')
                result_type = result.get('type', 'search_result')
                
                if snippet:
                    type_emoji = {
                        'instant_answer': '⚡',
                        'related_topic': '🔗',
                        'encyclopedia': '📚',
                        'search_result': '📄'
                    }.get(result_type, '📄')
                    
                    summary = snippet[:300] + '...' if len(snippet) > 300 else snippet
                    information_pieces.append(f"**{type_emoji} {title}**: {summary}")
                    
                    if url and url.startswith('http'):
                        sources_used.append(f"- [{title}]({url}) ({source})")
                    else:
                        sources_used.append(f"- {title} ({source})")
            
            if information_pieces:
                response = f"Here's what I found about '{query}':\n\n"
                response += "\n\n".join(information_pieces)
                
                if sources_used:
                    response += "\n\n**Sources:**\n" + "\n".join(sources_used)
                
                return response
            else:
                return self.fallback_system.get_response(query)
                
        except Exception as e:
            return self.fallback_system.get_response(query)

    def _handle_local_query(self, message: str) -> str:
        return self.fallback_system.get_response(message)

# Initialize global components
cognitive_nexus = SimpleCognitiveNexus()

def apply_custom_css():
    st.markdown("""
    <style>
    .stApp {
        background-color: var(--background-color);
        color: var(--text-color);
    }
    
    @media (prefers-color-scheme: dark) {
        :root {
            --background-color: #0e1117;
            --text-color: #fafafa;
            --secondary-bg: #262730;
            --border-color: #3d4043;
            --accent-color: #ff6b6b;
        }
    }
    
    @media (prefers-color-scheme: light) {
        :root {
            --background-color: #ffffff;
            --text-color: #262730;
            --secondary-bg: #f0f2f6;
            --border-color: #d1d1d1;
            --accent-color: #1f77b4;
        }
    }
    
    .chat-message {
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 0.5rem;
        border-left: 4px solid var(--accent-color);
        background-color: var(--secondary-bg);
    }
    
    .stButton > button {
        background-color: var(--accent-color);
        color: white;
        border: none;
        border-radius: 0.5rem;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

def render_sidebar():
    with st.sidebar:
        st.markdown("## 🧠 Cognitive Nexus AI")
        st.markdown("**Simplified Version**")
        
        # Settings
        st.markdown("### ⚙️ Settings")
        show_sources = st.checkbox("📚 Show Sources", value=True)
        enable_learning = st.checkbox("🧠 Learning Mode", value=True)
        enable_search = st.checkbox("🌐 Web Search", value=True)
        
        # System status
        st.markdown("### 📊 System Status")
        st.success("**Available:** 🌐 Web Search • 💭 Pattern-based")
        
        # Learning statistics
        if enable_learning:
            prefs_count = len(cognitive_nexus.learning_system.user_preferences)
            
            if prefs_count > 0:
                st.markdown("### 🧠 Memory")
                st.metric("Preferences", prefs_count)
        
        # Usage tips
        st.markdown("### 💡 Usage Tips")
        st.markdown("""
        **Search queries:** "What's the latest news about AI?"
        **Explanations:** "Explain quantum computing"
        **Comparisons:** "Compare Python vs JavaScript"
        **Current info:** "Today's weather in Tokyo"
        """)
        
        # Store settings
        st.session_state.show_sources = show_sources
        st.session_state.enable_learning = enable_learning
        st.session_state.enable_search = enable_search

def main():
    apply_custom_css()
    render_sidebar()
    
    # Main content
    st.title("🧠 Cognitive Nexus AI")
    st.markdown("**Simplified, privacy-focused AI assistant with real-time web search**")
    
    # System mode indicator
    st.info("🌐 **Hybrid Mode**: Web search with intelligent pattern-based responses")
    
    # Clear chat button
    if st.button("🗑️ Clear Chat", help="Clear current session messages"):
        st.session_state.messages = []
        st.rerun()
    
    # Display conversation
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask me anything..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("🤔 Thinking..."):
                show_sources = st.session_state.get('show_sources', True)
                enable_search = st.session_state.get('enable_search', True)
                
                if enable_search:
                    response = cognitive_nexus.process_message(prompt)
                else:
                    response = cognitive_nexus._handle_local_query(prompt)
                
                st.markdown(response)
        
        st.session_state.messages.append({"role": "assistant", "content": response})

if __name__ == "__main__":
    main()

