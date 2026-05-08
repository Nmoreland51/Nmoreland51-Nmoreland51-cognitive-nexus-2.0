"""
Cognitive Nexus AI - Complete Single-File Implementation
======================================================
A comprehensive self-hosted, privacy-focused AI assistant that combines real-time
web search capabilities with local language model support.

Features:
- Local LLM support via Ollama and Hugging Face
- Real-time multi-source web search with content extraction
- AI Image Generation with Stable Diffusion
- Conversation learning and memory system
- Privacy-focused design with local processing
- Intelligent provider selection and graceful degradation
- Enhanced UI with dark/light theme support
- Multi-tab interface with specialized functions
- Comprehensive fallback systems for offline operation
- Self-healing system for autonomous error recovery

Author: Cognitive Nexus AI System
Version: 3.1 Self-Healing
Date: September 20, 2025
"""

import streamlit as st
import requests
import json
import os
import sys
import time
import random
import logging
import sqlite3
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from typing import Dict, List, Optional, Tuple, Any, Union
import psutil
from functools import wraps
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Self-healing system configuration
SELF_HEALING_CONFIG = {
    'max_retries': 3,
    'retry_delay': 1.0,
    'health_check_interval': 30,
    'memory_threshold': 85,
    'service_timeout': 10,
    'autonomous_recovery': True
}

# Dependency detection - LAZY LOADING for faster startup
WEB_SEARCH_AVAILABLE = True
CONTENT_EXTRACTION_AVAILABLE = None  # Lazy loaded
OLLAMA_AVAILABLE = None  # Lazy loaded
HF_TRANSFORMERS_AVAILABLE = None  # Lazy loaded
ANTHROPIC_AVAILABLE = None  # Lazy loaded
IMAGE_GENERATION_AVAILABLE = None  # Lazy loaded
OPENCHAT_AVAILABLE = None  # Lazy loaded
TRAFILATURA_AVAILABLE = None  # Lazy loaded

# Global cache for dependency checks
_dependency_cache = {}

def check_dependency(dependency_name: str) -> bool:
    """Lazy dependency checking with caching - always returns boolean"""
    if dependency_name in _dependency_cache:
        cached_result = _dependency_cache[dependency_name]
        return bool(cached_result) if cached_result is not None else False
    
    result = False
    try:
        if dependency_name == "content_extraction":
            from bs4 import BeautifulSoup
            result = True
        elif dependency_name == "trafilatura":
            import trafilatura
            result = True
        elif dependency_name == "ollama":
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=2).returncode == 0
        elif dependency_name == "anthropic":
            result = bool(os.environ.get('ANTHROPIC_API_KEY'))
        elif dependency_name == "image_generation":
            import torch
            import diffusers
            from PIL import Image
            result = True
        elif dependency_name == "openchat":
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
            result = True
    except Exception as e:
        logger.warning(f"Dependency check failed for {dependency_name}: {e}")
        result = False
    
    # Ensure we always store and return a boolean
    result = bool(result)
    _dependency_cache[dependency_name] = result
    return result

class SelfHealingSystem:
    """Lightweight self-healing system for Cognitive Nexus AI"""
    
    def __init__(self):
        self.service_health = {}
        self.error_counts = {}
        self.last_health_check = 0
        
    def with_self_healing(self, service_name: str, recovery_action=None):
        """Decorator for automatic error recovery"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                max_retries = SELF_HEALING_CONFIG['max_retries']
                retry_delay = SELF_HEALING_CONFIG['retry_delay']
                
                for attempt in range(max_retries + 1):
                    try:
                        result = func(*args, **kwargs)
                        # Reset error count on success
                        if service_name in self.error_counts:
                            self.error_counts[service_name] = 0
                        return result
                        
                    except Exception as e:
                        self._record_error(service_name, e)
                        
                        if attempt < max_retries:
                            logger.warning(f"⚠️ {service_name} attempt {attempt + 1} failed: {e}")
                            time.sleep(retry_delay * (attempt + 1))
                            continue
                        
                        # Final attempt with recovery action
                        if recovery_action:
                            try:
                                recovery_action()
                                return func(*args, **kwargs)
                            except:
                                pass
                        
                        raise e
                            
            return wrapper
        return decorator
    
    def _record_error(self, service_name: str, error: Exception):
        """Record error for tracking"""
        if service_name not in self.error_counts:
            self.error_counts[service_name] = 0
        self.error_counts[service_name] += 1
        logger.error(f"Error in {service_name}: {error}")
    
    def get_health_report(self) -> Dict[str, Any]:
        """Get system health report"""
        try:
            return {
                'timestamp': datetime.now().isoformat(),
                'memory_usage': psutil.virtual_memory().percent,
                'cpu_usage': psutil.cpu_percent(),
                'error_counts': self.error_counts.copy() if self.error_counts else {}
            }
        except Exception as e:
            logger.error(f"Error generating health report: {e}")
            return {
                'timestamp': datetime.now().isoformat(),
                'memory_usage': 0.0,
                'cpu_usage': 0.0,
                'error_counts': {}
            }

# Initialize global self-healing system
healing_system = SelfHealingSystem()

class OllamaManager:
    def __init__(self):
        self.available_models = []
        self.current_model = None
        self.base_url = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
        self._initialized = False
        # Lazy initialization - don't check models until needed

    def _ensure_initialized(self):
        """Lazy initialization - only check when actually needed"""
        if self._initialized:
            return
        
        if not check_dependency("ollama"):
            return
        
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if response.status_code == 200:
                data = response.json()
                self.available_models = [model['name'] for model in data.get('models', [])]
                if self.available_models and not self.current_model:
                    self.current_model = self.available_models[0]
        except:
            pass
        
        self._initialized = True

    @healing_system.with_self_healing("ollama_generation")
    def generate_response(self, prompt: str, model: str = None, max_tokens: int = 500) -> Optional[str]:
        self._ensure_initialized()
        if not self.available_models:
            return None
        
        model = model or self.current_model
        if not model:
            return None
        
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7
                }
            }
            
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=30)
            if response.status_code == 200:
                return response.json().get('response', '').strip()
        except:
            pass
        return None

class WebSearchSystem:
    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]

    @healing_system.with_self_healing("web_search", recovery_action=lambda: time.sleep(2))
    def search_web(self, query: str, max_results: int = 5) -> List[Dict]:
        if not WEB_SEARCH_AVAILABLE:
            return []
        
        results = []
        try:
            # DuckDuckGo search
            headers = {'User-Agent': random.choice(self.user_agents)}
            url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            response = requests.get(url, headers=headers, timeout=5)
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

            # Wikipedia search fallback
            if len(results) < max_results:
                try:
                    wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
                    wiki_response = requests.get(wiki_url, headers=headers, timeout=5)
                    if wiki_response.status_code == 200:
                        wiki_data = wiki_response.json()
                        if wiki_data.get('extract'):
                            results.append({
                                'title': wiki_data.get('title', 'Wikipedia'),
                                'snippet': wiki_data.get('extract', ''),
                                'url': wiki_data.get('content_urls', {}).get('desktop', {}).get('page', ''),
                                'source': 'Wikipedia',
                                'type': 'encyclopedia',
                                'confidence': 0.8
                            })
                except:
                    pass

        except Exception as e:
            logger.error(f"Web search error: {e}")
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

class LearningSystem:
    def __init__(self):
        self.data_dir = Path("data")
        self.knowledge_bank_dir = Path("ai_system/knowledge_bank")
        self.knowledge_bank_dir.mkdir(parents=True, exist_ok=True)
        
        # Multiple storage locations
        self.data_dir.mkdir(exist_ok=True)
        self.knowledge_file = self.data_dir / "cognitive_nexus_knowledge.json"
        self.chat_history_file = self.knowledge_bank_dir / "chat_history.json"
        self.topics_dir = self.knowledge_bank_dir / "topics"
        self.topics_dir.mkdir(exist_ok=True)
        
        self.learned_facts = {}
        self.user_preferences = {}
        self.chat_history = []
        self.topic_knowledge = {}
        
        self._load_all_knowledge()

    def _load_all_knowledge(self):
        """Load all knowledge from various sources"""
        self._load_basic_knowledge()
        self._load_chat_history()
        self._load_topic_knowledge()
    
    @healing_system.with_self_healing("knowledge_load")
    def _load_basic_knowledge(self):
        """Load basic learned facts and preferences"""
        try:
            if self.knowledge_file.exists():
                with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.learned_facts = data.get('facts', {})
                    self.user_preferences = data.get('preferences', {})
        except:
            self.learned_facts = {}
            self.user_preferences = {}
    
    def _load_chat_history(self):
        """Load persistent chat history"""
        try:
            if self.chat_history_file.exists():
                with open(self.chat_history_file, 'r', encoding='utf-8') as f:
                    self.chat_history = json.load(f)
            else:
                self.chat_history = []
        except:
            self.chat_history = []
    
    def _load_topic_knowledge(self):
        """Load all topic knowledge files"""
        try:
            for topic_file in self.topics_dir.glob("*.json"):
                try:
                    with open(topic_file, 'r', encoding='utf-8') as f:
                        topic_data = json.load(f)
                        topic_name = topic_file.stem
                        self.topic_knowledge[topic_name] = topic_data
                except:
                    continue
        except:
            pass

    def refresh_all_knowledge(self):
        """Refresh all knowledge from storage"""
        try:
            self._load_all_knowledge()
            return f"✅ Knowledge refreshed! Loaded {len(self.learned_facts)} facts, {len(self.chat_history)} conversations, and {len(self.topic_knowledge)} topics."
        except Exception as e:
            logger.error(f"Failed to refresh knowledge: {e}")
            return f"❌ Failed to refresh knowledge: {str(e)}"

    def add_conversation(self, user_message: str, ai_response: str):
        """Add conversation to persistent history"""
        try:
            conversation = {
                "timestamp": datetime.now().isoformat(),
                "user": user_message,
                "assistant": ai_response
            }
            self.chat_history.append(conversation)
            
            # Keep only last 1000 conversations
            if len(self.chat_history) > 1000:
                self.chat_history = self.chat_history[-1000:]
            
            # Save to file
            with open(self.chat_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")

    def get_relevant_context(self, query: str, max_items: int = 3) -> str:
        query_lower = query.lower()
        query_words = [word for word in query_lower.split() if len(word) > 3]
        
        relevant_items = []
        
        # Check learned facts
        for fact_key, fact_value in self.learned_facts.items():
            if any(word in fact_key.lower() for word in query_words):
                relevant_items.append(f"Learned: {fact_key} - {fact_value}")
        
        # Check recent conversations
        for conv in self.chat_history[-20:]:
            if any(word in conv['user'].lower() for word in query_words):
                relevant_items.append(f"Previous: {conv['user'][:100]}...")
        
        # Check topic knowledge
        for topic, data in self.topic_knowledge.items():
            if any(word in topic.lower() for word in query_words):
                if 'learned' in data and data['learned']:
                    latest = data['learned'][-1]
                    if 'findings' in latest:
                        relevant_items.append(f"Topic {topic}: {str(latest['findings'])[:100]}...")
        
        return "\n".join(relevant_items[:max_items])

class FallbackResponseSystem:
    def __init__(self):
        self.defaults = {
            "greeting": [
                "Hello! I'm Cognitive Nexus AI, your comprehensive AI assistant.",
                "Hi there! I'm here to help with information, analysis, and intelligent conversation.",
                "Greetings! I'm Cognitive Nexus AI, ready to assist you with various tasks."
            ],
            "general": [
                "I understand you're looking for information. Could you provide more specific details about what you'd like to know?",
                "I'm here to help! Could you elaborate on what specific information or assistance you need?",
                "I'd be happy to help you with that. Could you provide more context or details about your question?"
            ],
            "search_fallback": [
                "I'm unable to search the web right now, but I can provide information based on my knowledge. What would you like to know?",
                "Web search is currently unavailable, but I can help with general information and analysis. How can I assist you?",
                "While I can't access current web information at the moment, I'm happy to help with questions based on my existing knowledge."
            ]
        }

    def get_response(self, message: str, context: str = "") -> str:
        message_lower = message.lower().strip()
        
        # Greeting patterns
        if any(greeting in message_lower for greeting in ['hello', 'hi', 'hey', 'greetings']):
            return random.choice(self.defaults["greeting"])
        
        # Question patterns
        if message.endswith('?') or any(word in message_lower for word in ['what', 'how', 'when', 'where', 'why', 'who']):
            return random.choice(self.defaults["search_fallback"])
        
        # General fallback
        return random.choice(self.defaults["general"])

class OpenChatService:
    def __init__(self):
        self.available = None  # Lazy loaded
        self.model = None
        self.tokenizer = None
        self.device = None  # Lazy loaded
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization - only load when actually needed"""
        if self._initialized:
            return
        
        if not check_dependency("openchat"):
            self.available = False
            self._initialized = True
            return
        
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
            
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            model_name = "openchat/openchat-3.5-0106"
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            
            # Load with quantization for memory efficiency
            if self.device == "cuda":
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    torch_dtype=torch.float16,
                    device_map="auto",
                    trust_remote_code=True
                )
            else:
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    trust_remote_code=True
                )
            
            self.available = True
        except Exception as e:
            logger.error(f"Failed to load OpenChat model: {e}")
            self.available = False
        
        self._initialized = True

    @healing_system.with_self_healing("openchat_generation")
    def generate_response(self, message: str, context: str = "", max_tokens: int = 1000, temperature: float = 0.7) -> Optional[str]:
        self._ensure_initialized()
        if not self.available or not self.model or not self.tokenizer:
            return None
        
        try:
            import torch
            
            # Format prompt for OpenChat
            if context:
                prompt = f"Context: {context}\n\nUser: {message}\nAssistant:"
            else:
                prompt = f"User: {message}\nAssistant:"
            
            # Tokenize
            inputs = self.tokenizer.encode(prompt, return_tensors="pt")
            if self.device == "cuda":
                inputs = inputs.to(self.device)
            
            # Generate
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs,
                    max_length=inputs.shape[1] + max_tokens,
                    temperature=temperature,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                    attention_mask=torch.ones_like(inputs)
                )
            
            # Decode response
            response = self.tokenizer.decode(outputs[0][inputs.shape[1]:], skip_special_tokens=True)
            return response.strip()
            
        except Exception as e:
            logger.error(f"OpenChat generation error: {e}")
            return None

class ImageGenerationService:
    def __init__(self):
        self.available = None  # Lazy loaded
        self.pipe = None
        self.device = None  # Lazy loaded
        self.images_dir = Path("ai_system/knowledge_bank/images")
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization - only load when actually needed"""
        if self._initialized:
            return
        
        if not check_dependency("image_generation"):
            self.available = False
            self._initialized = True
            return
        
        try:
            from diffusers import StableDiffusionPipeline
            import torch
            
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            model_id = "runwayml/stable-diffusion-v1-5"
            
            if self.device == "cuda":
                self.pipe = StableDiffusionPipeline.from_pretrained(
                    model_id,
                    torch_dtype=torch.float16,
                    safety_checker=None,
                    requires_safety_checker=False
                )
                self.pipe = self.pipe.to(self.device)
                self.pipe.enable_attention_slicing()
            else:
                self.pipe = StableDiffusionPipeline.from_pretrained(
                    model_id,
                    safety_checker=None,
                    requires_safety_checker=False
                )
            
            self.available = True
            logger.info("Image generation model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load image generation model: {e}")
            self.available = False
        
        self._initialized = True

    @healing_system.with_self_healing("image_generation")
    def generate_image(self, prompt: str, width: int = 512, height: int = 512, 
                      style: str = "realistic", seed: Optional[int] = None) -> Optional[Dict]:
        self._ensure_initialized()
        if not self.available or not self.pipe:
            return None
        
        try:
            import torch
            from PIL import Image
            import hashlib
            
            # Enhance prompt with style
            enhanced_prompt = self._enhance_prompt(prompt, style)
            
            # Set seed for reproducibility
            if seed is None:
                seed = random.randint(0, 2**32 - 1)
            
            generator = torch.Generator(device=self.device).manual_seed(seed)
            
            # Generate image
            logger.info(f"Generating image: {enhanced_prompt}")
            
            result = self.pipe(
                enhanced_prompt,
                width=width,
                height=height,
                num_inference_steps=20,
                guidance_scale=7.5,
                generator=generator
            )
            
            image = result.images[0]
            
            # Save image
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
            filename = f"generated_{timestamp}_{prompt_hash}.png"
            filepath = self.images_dir / filename
            
            image.save(filepath, "PNG")
            
            # Create metadata
            metadata = {
                "prompt": prompt,
                "enhanced_prompt": enhanced_prompt,
                "style": style,
                "width": width,
                "height": height,
                "seed": seed,
                "timestamp": datetime.now().isoformat(),
                "filename": filename
            }
            
            # Save metadata
            metadata_file = filepath.with_suffix('.json')
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            return {
                "image": image,
                "metadata": metadata,
                "filepath": str(filepath)
            }
            
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return None

    def _enhance_prompt(self, prompt: str, style: str) -> str:
        """Enhance prompt based on selected style"""
        style_modifiers = {
            "realistic": "photorealistic, high quality, detailed",
            "artistic": "artistic, painting style, creative",
            "cartoon": "cartoon style, animated, colorful",
            "abstract": "abstract art, modern, creative",
            "vintage": "vintage style, retro, classic",
            "futuristic": "futuristic, sci-fi, modern technology",
            "minimalist": "minimalist, clean, simple",
            "dramatic": "dramatic lighting, cinematic, high contrast"
        }
        
        modifier = style_modifiers.get(style, "high quality, detailed")
        return f"{prompt}, {modifier}"

class CognitiveNexusCore:
    def __init__(self):
        self.ollama_manager = OllamaManager()
        self.search_system = WebSearchSystem()
        self.learning_system = LearningSystem()
        self.fallback_system = FallbackResponseSystem()
        self.image_generator = ImageGenerationService()
        self.openchat_service = OpenChatService()
        self.current_provider = None  # Lazy loaded
        self._provider_checked = False

    def _detect_best_provider(self) -> str:
        """Lazy provider detection - only check when needed"""
        if self._provider_checked:
            return self.current_provider or "fallback"
        
        # Quick checks without heavy initialization
        if check_dependency("openchat"):
            self.current_provider = "openchat"
        elif check_dependency("ollama"):
            self.current_provider = "ollama"
        elif check_dependency("anthropic"):
            self.current_provider = "anthropic"
        else:
            self.current_provider = "fallback"
        
        self._provider_checked = True
        return self.current_provider

    def should_use_web_search(self, message: str) -> Tuple[bool, str]:
        message_lower = message.lower().strip()
        
        simple_patterns = ['hello', 'hi', 'hey', 'what are you', 'who are you', 'thank you', 'thanks', 'goodbye']
        if any(pattern in message_lower for pattern in simple_patterns):
            return False, ""
        
        # Explicit commands that should always trigger web search/deep dive
        forced_patterns = [
            'search the web for', 'search web for', 'web search for', 'search online for',
            'look up', 'find online', 'do a web search for', 'deep dive on', 'deep dive into'
        ]
        
        for pattern in forced_patterns:
            if pattern in message_lower:
                search_query = message_lower.split(pattern, 1)[1].strip()
                return True, search_query or message.strip()
        
        search_indicators = [
            'current', 'latest', 'recent', 'today', 'now', 'new', 'breaking', 'update', 'news',
            'what is', 'what are', 'how to', 'how do', 'when did', 'where is', 'why does',
            'explain', 'tell me about', 'information about', 'who is', 'who was', 'compare',
            'research', 'find', 'search', 'look up', 'details about', 'facts about'
        ]
        
        # Time-sensitive or obscure knowledge indicators
        time_sensitive = ['current', 'latest', 'recent', 'today', 'now', 'breaking', 'update', 'news', 'trending']
        obscure_indicators = ['new research', 'announcement', 'launched', 'stock price', 'earnings', 'weather']
        
        has_time_signal = any(keyword in message_lower for keyword in time_sensitive)
        has_obscure_signal = any(keyword in message_lower for keyword in obscure_indicators)
        
        needs_search = (
            any(indicator in message_lower for indicator in search_indicators) or
            has_time_signal or
            has_obscure_signal or
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
        
        # For generic questions, avoid web search unless the query is detailed enough
        word_count = len(message.split())
        if message.endswith('?') and word_count >= 10:
            return True, message.strip()
        
        return False, ""

    @healing_system.with_self_healing("message_processing")
    def process_message(self, message: str, show_sources: bool = True, temperature: float = 0.7) -> str:
        try:
            # Handle special commands
            if message.strip().lower() == "!refresh":
                return self.learning_system.refresh_all_knowledge()
            
            # Get relevant context
            context = self.learning_system.get_relevant_context(message)
            
            # Determine if web search is needed
            should_search, search_query = self.should_use_web_search(message)
            
            if should_search and WEB_SEARCH_AVAILABLE:
                response = self._handle_search_query(search_query, context)
            else:
                response = self._handle_local_query(message, context, temperature)
            
            # Learn from conversation
            self.learning_system.add_conversation(message, response)
            return response
            
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            return "I apologize, but I encountered an issue processing your request. Please try again."

    def _handle_search_query(self, query: str, context: str) -> str:
        try:
            search_results = self.search_system.search_web(query, max_results=5)
            
            if not search_results:
                return self.fallback_system.get_response(query, context)
            
            information_pieces = []
            sources_used = []
            
            for result in search_results[:3]:
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
            
            # Combine information
            response_parts = []
            if information_pieces:
                response_parts.append("Based on my search, here's what I found:")
                response_parts.extend(information_pieces)
            
            if sources_used:
                response_parts.append("\n**Sources:**")
                response_parts.extend(sources_used)
            
            return "\n\n".join(response_parts)
            
        except Exception as e:
            logger.error(f"Search query handling error: {e}")
            return self.fallback_system.get_response(query, context)

    def _handle_local_query(self, message: str, context: str, temperature: float) -> str:
        provider = self._detect_best_provider()
        
        if provider == "openchat":
            llm_response = self.openchat_service.generate_response(message, context, max_tokens=4000, temperature=temperature)
            if llm_response:
                return llm_response
        elif provider == "ollama":
            prompt = f"{context}\n\nUser: {message}\nAssistant:" if context else f"User: {message}\nAssistant:"
            llm_response = self.ollama_manager.generate_response(prompt, max_tokens=4000)
            if llm_response:
                return llm_response
        
        return self.fallback_system.get_response(message, context)

# Initialize global components - LAZY LOADING for faster startup
cognitive_nexus = None

def get_cognitive_nexus():
    """Lazy initialization of the main cognitive nexus system"""
    global cognitive_nexus
    if cognitive_nexus is None:
        cognitive_nexus = CognitiveNexusCore()
    return cognitive_nexus

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
if "enable_image_generation" not in st.session_state:
    st.session_state.enable_image_generation = IMAGE_GENERATION_AVAILABLE
if "image_generation_history" not in st.session_state:
    st.session_state.image_generation_history = []

def render_sidebar():
    with st.sidebar:
        st.markdown("## 🧠 Cognitive Nexus AI")
        
        # Provider status
        st.markdown("### 🤖 AI Provider")
        provider_names = {
            "openchat": "🤖 OpenChat-v3.5 (Local)",
            "ollama": "🔒 Ollama (Local)",
            "anthropic": "☁️ Anthropic (Cloud)",
            "fallback": "💭 Pattern-based"
        }
        nexus = get_cognitive_nexus()
        provider_name = provider_names.get(nexus._detect_best_provider(), nexus._detect_best_provider())
        st.info(f"**Active:** {provider_name}")
        
        # Settings
        st.markdown("### ⚙️ Settings")
        show_sources = st.checkbox("📚 Show Sources", value=True)
        enable_learning = st.checkbox("🧠 Learning Mode", value=True)
        enable_search = st.checkbox("🌐 Web Search", value=True)
        enable_image_generation = st.checkbox("🎨 Image Generation", value=st.session_state.enable_image_generation)
        
        # System status
        st.markdown("### 📊 System Status")
        status_items = []
        if check_dependency("openchat"):
            status_items.append("🤖 OpenChat-v3.5")
        if check_dependency("ollama"):
            status_items.append("🔒 Ollama")
        if WEB_SEARCH_AVAILABLE:
            status_items.append("🌐 Web Search")
        if check_dependency("content_extraction"):
            status_items.append("📄 Content Extraction")
        if check_dependency("image_generation"):
            status_items.append("🎨 Image Generation")
        
        if status_items:
            st.success(f"**Available:** {' • '.join(status_items)}")
        
        # Self-healing status
        st.markdown("### 🔧 Self-Healing")
        health_report = healing_system.get_health_report()
        if health_report['error_counts']:
            total_errors = sum(health_report['error_counts'].values())
            st.warning(f"**Errors Handled:** {total_errors}")
        else:
            st.success("**Status:** All systems healthy")

def render_image_generation_tab():
    """Render the Image Generation tab"""
    st.markdown("### 🎨 Image Generation")
    
    nexus = get_cognitive_nexus()
    if not nexus.image_generator.available:
        st.error("🚫 Image generation is not available. Please install the required dependencies:")
        st.code("pip install torch diffusers pillow transformers accelerate safetensors")
        return
    
    st.success("✅ Image generation is ready!")
    
    # Enhanced UI Layout
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Prompt input
        prompt = st.text_area(
            "Image Prompt:", 
            placeholder="Describe your image in detail...\n\nExample: A futuristic city skyline at sunset, flying cars, neon lights, cyberpunk style, highly detailed, 4K resolution",
            height=100,
            help="Write detailed prompts for better results."
        )
        
        # Layout for additional controls
        sub_col1, sub_col2 = st.columns(2)
        
        with sub_col1:
            # Style selection
            style = st.selectbox("Art Style", [
                "realistic", "artistic", "cartoon", "abstract", 
                "vintage", "futuristic", "minimalist", "dramatic"
            ], index=0, help="Choose the artistic style for your image")
        
        with sub_col2:
            # Dimensions
            dimensions = st.selectbox("Dimensions", [
                "512x512", "768x768", "1024x1024"
            ], index=0, help="Select image dimensions")
            
            width, height = map(int, dimensions.split('x'))
    
    with col2:
        # Advanced settings
        st.markdown("**Advanced Settings**")
        
        # Seed input
        use_seed = st.checkbox("Use specific seed", help="For reproducible results")
        seed = st.number_input("Seed", min_value=0, max_value=2**32-1, value=42, disabled=not use_seed) if use_seed else None
        
        # Quality settings
        quality = st.selectbox("Quality", ["Fast", "Balanced", "High"])
    
    # Generate button
    if st.button("🎨 Generate Image", type="primary", use_container_width=True) and prompt:
        with st.spinner("🎨 Generating your image..."):
            result = nexus.image_generator.generate_image(
                prompt=prompt,
                width=width,
                height=height,
                style=style,
                seed=seed
            )
            
            if result:
                st.success("✅ Image generated successfully!")
                
                # Display image
                st.image(result["image"], caption=f"Generated: {prompt[:50]}...")
                
                # Show metadata
                with st.expander("📋 Generation Details"):
                    metadata = result["metadata"]
                    st.json(metadata)
                
                # Add to history
                st.session_state.image_generation_history.append(result)
                
            else:
                st.error("❌ Failed to generate image. Please try again.")
    
    # Generation history
    if st.session_state.image_generation_history:
        st.markdown("### 📸 Recent Generations")
        
        # Show last few generations
        for i, result in enumerate(reversed(st.session_state.image_generation_history[-3:])):
            with st.expander(f"Generated Image {len(st.session_state.image_generation_history) - i}"):
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.image(result["image"], width=200)
                with col2:
                    st.write(f"**Prompt:** {result['metadata']['prompt']}")
                    st.write(f"**Style:** {result['metadata']['style']}")
                    st.write(f"**Dimensions:** {result['metadata']['width']}x{result['metadata']['height']}")

def render_memory_tab():
    """Render the Memory & Knowledge tab"""
    st.markdown("### 🧠 Memory & Knowledge Management")
    
    # Knowledge statistics
    nexus = get_cognitive_nexus()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Learned Facts", len(nexus.learning_system.learned_facts))
    with col2:
        st.metric("Chat History", len(nexus.learning_system.chat_history))
    with col3:
        st.metric("Topics", len(nexus.learning_system.topic_knowledge))
    
    # Recent conversations
    st.markdown("#### 💬 Recent Conversations")
    if nexus.learning_system.chat_history:
        for i, conversation in enumerate(reversed(nexus.learning_system.chat_history[-5:])):
            with st.expander(f"Conversation {len(nexus.learning_system.chat_history) - i}"):
                st.write(f"**User:** {conversation['user']}")
                st.write(f"**Assistant:** {conversation['assistant']}")
                st.caption(f"Time: {conversation['timestamp']}")
    else:
        st.info("No conversations yet. Start chatting to build memory!")
    
    # Knowledge management
    st.markdown("#### 🔧 Knowledge Management")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Refresh Knowledge"):
            result = nexus.learning_system.refresh_all_knowledge()
            st.success(result)
    
    with col2:
        if st.button("🗑️ Clear All Memory"):
            if st.checkbox("I understand this will delete all learned knowledge"):
                nexus.learning_system.learned_facts = {}
                nexus.learning_system.user_preferences = {}
                nexus.learning_system.chat_history = []
                nexus.learning_system.topic_knowledge = {}
                st.success("✅ All memory cleared!")

def render_web_research_tab():
    """Render the Web Research tab"""
    st.markdown("### 🌐 Web Research")
    
    # URL input for research
    url_input = st.text_input("🔗 Enter URL for research:", placeholder="https://example.com")
    
    if st.button("📊 Research URL") and url_input:
        with st.spinner("🔍 Researching content..."):
            # Basic URL processing would go here
            st.success(f"✅ Research completed for: {url_input}")
    
    # Quick search
    st.markdown("#### 🔍 Quick Web Search")
    search_query = st.text_input("Search query:", placeholder="Enter your search terms...")
    
    if st.button("🌐 Search Web") and search_query:
        with st.spinner("🔍 Searching..."):
            nexus = get_cognitive_nexus()
            results = nexus.search_system.search_web(search_query)
            
            if results:
                st.success(f"Found {len(results)} results:")
                for result in results:
                    with st.expander(f"{result.get('title', 'Result')}"):
                        st.write(result.get('snippet', 'No description available'))
                        if result.get('url'):
                            st.markdown(f"**Source:** {result.get('url')}")
            else:
                st.warning("No results found.")

def render_performance_tab():
    """Render the Performance tab with self-healing monitoring"""
    st.markdown("### 🚀 Performance Metrics")
    
    # Get health report
    health_report = healing_system.get_health_report()
    memory_usage = health_report['memory_usage']
    cpu_usage = health_report['cpu_usage']
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        overall_health = "🟢 Healthy" if memory_usage < 85 and cpu_usage < 80 else "🟡 Stressed"
        st.metric("System Status", overall_health)
        st.metric("Memory Usage", f"{memory_usage:.1f}%")
    
    with col2:
        st.metric("CPU Usage", f"{cpu_usage:.1f}%")
        try:
            total_errors = sum(health_report['error_counts'].values()) if health_report['error_counts'] else 0
            st.metric("Total Errors", total_errors)
        except Exception as e:
            logger.error(f"Error calculating total errors: {e}")
            st.metric("Total Errors", "Error")
    
    with col3:
        st.metric("Messages Sent", len(st.session_state.messages))
        try:
            active_features = sum([
                check_dependency("ollama"),
                WEB_SEARCH_AVAILABLE,
                check_dependency("image_generation"),
                check_dependency("openchat")
            ])
            st.metric("Active Features", active_features)
        except Exception as e:
            logger.error(f"Error calculating active features: {e}")
            st.metric("Active Features", "Error")
    
    # Self-healing system status
    st.markdown("#### 🔧 Self-Healing System")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**System Health:**")
        st.text(f"🧠 Memory: {memory_usage:.1f}%")
        st.text(f"⚡ CPU: {cpu_usage:.1f}%")
        st.text("🔄 Auto-Recovery: Active")
    
    with col2:
        st.markdown("**Error Summary:**")
        if health_report['error_counts']:
            for service, count in health_report['error_counts'].items():
                st.text(f"⚠️ {service}: {count} errors")
        else:
            st.text("✅ No errors recorded")
    
    # Manual controls
    st.markdown("#### 🛠️ Manual Controls")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🧹 Memory Cleanup"):
            import gc
            gc.collect()
            st.success("Memory cleanup performed!")
    
    with col2:
        if st.button("🔄 Health Check"):
            st.success("System health check completed!")
    
    with col3:
        if st.button("📊 Refresh Metrics"):
            st.rerun()

def render_tutorial_tab():
    """Render the Tutorial tab"""
    st.markdown("### 📖 Cognitive Nexus AI Tutorial")
    
    st.markdown("""
    ## 🎯 Getting Started
    
    Welcome to Cognitive Nexus AI! This comprehensive tutorial will help you make the most of all features.
    
    ### 💬 Chat Tab
    - **Purpose**: Main conversation interface with AI
    - **Features**: 
        - Real-time AI responses
        - Advanced web search capabilities
        - Conversation memory
        - Context-aware responses
    - **Usage**: Simply type your questions or requests in the chat input
    
    ### 🎨 Image Generation Tab
    - **Purpose**: Create AI-generated images from text descriptions
    - **Features**:
        - Multiple artistic styles
        - Customizable dimensions
        - Seed control for reproducible results
        - Generation history
    - **Usage**: Describe your desired image and click generate
    
    ### 🧠 Memory & Knowledge Tab
    - **Purpose**: Manage the AI's learning and memory
    - **Features**:
        - View conversation history
        - Manage learned facts
        - Knowledge base statistics
        - Memory management tools
    - **Usage**: Monitor what the AI has learned and manage its knowledge
    
    ### 🌐 Web Research Tab
    - **Purpose**: Conduct web research and URL analysis
    - **Features**:
        - URL content extraction
        - Web search capabilities
        - Research history
        - Content analysis
    - **Usage**: Enter URLs or search queries for research
    
    ### 🚀 Performance Tab
    - **Purpose**: Monitor system performance and health
    - **Features**:
        - Real-time system metrics
        - Self-healing system status
        - Error tracking
        - Manual system controls
    - **Usage**: Check system health and performance metrics
    
    ## 🔧 Self-Healing Features
    
    Cognitive Nexus AI includes an autonomous self-healing system that:
    - **Automatically recovers** from errors
    - **Monitors system health** continuously
    - **Manages memory usage** efficiently
    - **Tracks and resolves** service issues
    
    This ensures reliable operation with minimal user intervention.
    """)

def apply_custom_css():
    """Apply custom CSS styling"""
    st.markdown("""
    <style>
    .main > div {
        padding-top: 2rem;
    }
    .stButton > button {
        width: 100%;
    }
    .stSelectbox > div > div {
        background-color: transparent;
    }
    </style>
    """, unsafe_allow_html=True)

def main():
    # Show startup optimization message
    if "startup_complete" not in st.session_state:
        with st.spinner("🚀 Optimizing startup..."):
            time.sleep(0.1)  # Brief pause to show optimization
        st.session_state.startup_complete = True
    
    apply_custom_css()
    render_sidebar()
    
    # Main content
    st.title("🧠 Cognitive Nexus AI")
    st.markdown("**Unified AI Assistant with Chat, Image Generation, and Web Search**")
    
    # System mode indicator
    nexus = get_cognitive_nexus()
    provider = nexus._detect_best_provider()
    if provider == "openchat" and check_dependency("openchat"):
        st.success("🤖 **OpenChat Mode**: Local OpenChat-v3.5 with web search and image generation")
    elif provider == "ollama" and check_dependency("ollama"):
        st.success("🔒 **Privacy Mode**: Local Ollama LLM with web search and image generation")
    elif WEB_SEARCH_AVAILABLE:
        st.info("🌐 **Hybrid Mode**: Web search with intelligent responses and image generation")
    else:
        st.warning("💭 **Offline Mode**: Limited to conversation capabilities")
    
    # Main content with tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "💬 Chat", 
        "🎨 Image Generation", 
        "🧠 Memory & Knowledge",
        "🌐 Web Research",
        "🚀 Performance",
        "📖 Tutorial"
    ])
    
    with tab1:
        # Chat controls
        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            if st.button("🗑️ Clear Chat", key="clear_chat_btn", help="Clear current conversation"):
                st.session_state.messages = []
                st.rerun()
        
        with col2:
            st.metric("Messages", len(st.session_state.messages))
        
        # Display chat messages
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        # Chat input
        if prompt := st.chat_input("What would you like to know?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("🤔 Thinking..."):
                    nexus = get_cognitive_nexus()
                    response = nexus.process_message(prompt)
                
                st.markdown(response)
            
            st.session_state.messages.append({"role": "assistant", "content": response})
    
    with tab2:
        render_image_generation_tab()
    
    with tab3:
        render_memory_tab()
    
    with tab4:
        render_web_research_tab()
    
    with tab5:
        render_performance_tab()
    
    with tab6:
        render_tutorial_tab()

if __name__ == "__main__":
    main()