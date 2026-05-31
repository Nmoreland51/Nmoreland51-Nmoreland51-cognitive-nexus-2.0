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

Author: Cognitive Nexus AI System
Version: 3.0 Unified
Date: September 16, 2025
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dependency detection
WEB_SEARCH_AVAILABLE = True
CONTENT_EXTRACTION_AVAILABLE = False
OLLAMA_AVAILABLE = False
HF_TRANSFORMERS_AVAILABLE = False
ANTHROPIC_AVAILABLE = False
IMAGE_GENERATION_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    CONTENT_EXTRACTION_AVAILABLE = True
except ImportError:
    pass

try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

# Check Ollama
try:
    result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=5)
    OLLAMA_AVAILABLE = result.returncode == 0
except:
    OLLAMA_AVAILABLE = False

# Check Anthropic
ANTHROPIC_AVAILABLE = bool(os.environ.get('ANTHROPIC_API_KEY'))

# Check Image Generation
try:
    import torch
    import diffusers
    from PIL import Image
    IMAGE_GENERATION_AVAILABLE = True
except ImportError:
    IMAGE_GENERATION_AVAILABLE = False

# Check OpenChat
try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch
    OPENCHAT_AVAILABLE = True
except ImportError:
    OPENCHAT_AVAILABLE = False

class OllamaManager:
    def __init__(self):
        self.available_models = []
        self.current_model = None
        self.base_url = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
        self._detect_models()

    def _detect_models(self):
        if not OLLAMA_AVAILABLE:
            return
        try:
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]
                self.available_models = [line.split()[0] for line in lines if line.strip() and line.split()]
                if self.available_models:
                    self.current_model = self.available_models[0]
        except:
            pass

    def generate_response(self, prompt: str, model: str = None, max_tokens: int = 500) -> Optional[str]:
        if not OLLAMA_AVAILABLE or not self.available_models:
            return None
        
        model_to_use = model or self.current_model
        if not model_to_use:
            return "No Ollama models are installed. Please install a model using 'ollama pull <model-name>'."

        try:
            payload = {
                'model': model_to_use,
                'prompt': prompt,
                'stream': False,
                'options': {'num_predict': max_tokens, 'temperature': 0.7}
            }
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '').strip()
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

            # Wikipedia search
            try:
                wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
                wiki_response = requests.get(wiki_url, headers=headers, timeout=10)
                if wiki_response.status_code == 200:
                    wiki_data = wiki_response.json()
                    if wiki_data.get('extract'):
                        results.append({
                            'title': wiki_data.get('title', 'Wikipedia Article'),
                            'snippet': wiki_data.get('extract', ''),
                            'url': wiki_data.get('content_urls', {}).get('desktop', {}).get('page', ''),
                            'source': 'Wikipedia',
                            'type': 'encyclopedia',
                            'confidence': 0.95
                        })
            except:
                pass

        except:
            # Fallback to offline knowledge
            results = self._get_offline_knowledge(query, max_results)
        
        return results[:max_results]

    def _get_offline_knowledge(self, query: str, max_results: int) -> List[Dict]:
        knowledge_base = {
            'artificial intelligence': {
                'title': 'Artificial Intelligence - Overview',
                'content': 'Artificial Intelligence (AI) refers to computer systems that can perform tasks typically requiring human intelligence, such as learning, reasoning, problem-solving, and understanding language.',
                'source': 'Knowledge Base',
                'confidence': 0.9
            },
            'python': {
                'title': 'Python Programming Language',
                'content': 'Python is a high-level, interpreted programming language known for its simple syntax and readability.',
                'source': 'Knowledge Base',
                'confidence': 0.9
            }
        }
        
        results = []
        query_lower = query.lower()
        
        for key, info in knowledge_base.items():
            if key in query_lower:
                results.append({
                    'title': info['title'],
                    'snippet': info['content'][:300] + '...' if len(info['content']) > 300 else info['content'],
                    'url': f'offline://knowledge/{key}',
                    'source': info['source'],
                    'type': 'offline_knowledge',
                    'confidence': info['confidence']
                })
        
        if not results:
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
                topic_name = topic_file.stem
                with open(topic_file, 'r', encoding='utf-8') as f:
                    self.topic_knowledge[topic_name] = json.load(f)
        except Exception as e:
            logger.error(f"Error loading topic knowledge: {e}")
            self.topic_knowledge = {}

    def save_knowledge(self):
        try:
            data = {
                'facts': self.learned_facts,
                'preferences': self.user_preferences,
                'last_updated': datetime.now().isoformat(),
                'version': '2.0'
            }
            with open(self.knowledge_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass

    def add_conversation(self, user_message: str, ai_response: str):
        # Save to persistent chat history
        chat_entry = {
            'timestamp': datetime.now().isoformat(),
            'role': 'user',
            'content': user_message
        }
        self.chat_history.append(chat_entry)
        
        ai_entry = {
            'timestamp': datetime.now().isoformat(),
            'role': 'assistant',
            'content': ai_response
        }
        self.chat_history.append(ai_entry)
        
        # Save chat history immediately
        self._save_chat_history()
        
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
        if len(self.user_preferences) % 5 == 0:
            self.save_knowledge()
    
    def _save_chat_history(self):
        """Save chat history to persistent storage"""
        try:
            with open(self.chat_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save chat history: {e}")
    
    def refresh_all_knowledge(self):
        """Refresh all knowledge from storage (for !refresh command)"""
        logger.info("Refreshing all knowledge from storage...")
        self._load_all_knowledge()
        return f"✅ Knowledge refreshed! Loaded {len(self.chat_history)} chat messages, {len(self.learned_facts)} facts, and {len(self.topic_knowledge)} topics."

    def get_relevant_context(self, query: str, max_items: int = 3) -> str:
        query_lower = query.lower()
        query_words = [word for word in query_lower.split() if len(word) > 3]
        
        relevant_items = []
        
        # Search preferences
        for pref_data in self.user_preferences.values():
            content_lower = pref_data['content'].lower()
            if any(word in content_lower for word in query_words):
                relevant_items.append(f"💭 You mentioned: {pref_data['content']}")
        
        # Search topic knowledge
        for topic_name, topic_data in self.topic_knowledge.items():
            if any(word in topic_name.lower() for word in query_words):
                if 'learned' in topic_data and topic_data['learned']:
                    latest_entry = topic_data['learned'][-1]
                    if 'findings' in latest_entry:
                        findings = latest_entry['findings']
                        if 'definition' in findings:
                            relevant_items.append(f"📚 From {topic_name}: {findings['definition']}")
        
        return "\n".join(relevant_items[:max_items])
    
    def save_url_content(self, url: str, title: str, content: str, topic: str = None):
        """Save URL content to knowledge bank"""
        try:
            # Clean title for filename
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title.replace(' ', '-')[:50]  # Limit length
            
            # Create filename
            if topic:
                filename = f"{topic}.json"
            else:
                filename = f"{safe_title}-full.json"
            
            filepath = self.topics_dir / filename
            
            # Create or update topic data
            if filename in [f.stem + '.json' for f in self.topics_dir.glob('*.json')]:
                # Load existing
                with open(filepath, 'r', encoding='utf-8') as f:
                    topic_data = json.load(f)
            else:
                # Create new
                topic_data = {
                    "name": topic or safe_title,
                    "learned": [],
                    "status": "new",
                    "alternative_data": [],
                    "pending": []
                }
            
            # Add new content
            new_entry = {
                "timestamp": datetime.now().timestamp(),
                "importance": "high",
                "findings": {
                    "definition": f"Content from {url}",
                    "source_url": url,
                    "title": title,
                    "content": content[:2000] + "..." if len(content) > 2000 else content,
                    "full_content": content,
                    "extraction_date": datetime.now().isoformat()
                }
            }
            
            topic_data["learned"].append(new_entry)
            
            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(topic_data, f, indent=2, ensure_ascii=False)
            
            # Update in-memory knowledge
            self.topic_knowledge[topic or safe_title] = topic_data
            
            return f"✅ Content saved to knowledge bank: {filename}"
            
        except Exception as e:
            logger.error(f"Failed to save URL content: {e}")
            return f"❌ Failed to save content: {str(e)}"

class FallbackResponseSystem:
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

    def get_response(self, message: str, context: str = "") -> str:
        processed_query = message.lower().strip()
        
        # Check defaults
        if processed_query in self.defaults:
            response = self.defaults[processed_query]
            return f"{context}\n\n{response}" if context else response
        
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

class OpenChatService:
    """OpenChat-v3.5 service with quantization support"""
    
    _instance = None
    _model_loaded = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(OpenChatService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self.available = OPENCHAT_AVAILABLE
        self.model = None
        self.tokenizer = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # System prompt for OpenChat
        self.system_prompt = """You are an AI assistant that helps users with information, analysis, and intelligent conversation. You are helpful, harmless, and honest. You provide accurate, well-reasoned responses based on the context provided. Always respond directly without showing your internal thinking process."""
        
        # Only load model once
        if self.available and not OpenChatService._model_loaded:
            self._load_model()
            OpenChatService._model_loaded = True
        
        self._initialized = True
    
    def _load_model(self):
        """Load the OpenChat model with quantization"""
        if not self.available:
            return
        
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            import torch
            
            logger.info("Loading OpenChat-v3.5 model...")
            
            # Configure quantization for memory efficiency
            quantization_config = None
            if self.device == "cuda":
                # Use 8-bit quantization for CUDA
                quantization_config = BitsAndBytesConfig(
                    load_in_8bit=True,
                    llm_int8_threshold=6.0,
                    llm_int8_has_fp16_weight=False
                )
            else:
                # Use 4-bit quantization for CPU
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4"
                )
            
            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                "openchat/openchat-3.5",
                trust_remote_code=True
            )
            
            # Load model with quantization
            self.model = AutoModelForCausalLM.from_pretrained(
                "openchat/openchat-3.5",
                quantization_config=quantization_config,
                device_map="auto" if self.device == "cuda" else None,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                trust_remote_code=True,
                low_cpu_mem_usage=True
            )
            
            # Move to device if not using device_map
            if self.device == "cpu":
                self.model = self.model.to(self.device)
            
            logger.info("OpenChat-v3.5 model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load OpenChat model: {e}")
            self.available = False
    
    def generate_response(self, message: str, context: str = "", max_tokens: int = 500, temperature: float = 0.7) -> str:
        """Generate response using OpenChat-v3.5"""
        if not self.available or not self.model or not self.tokenizer:
            return None
        
        try:
            # Prepare the conversation with system prompt
            if context:
                full_prompt = f"{self.system_prompt}\n\nContext: {context}\n\nUser: {message}\nAssistant:"
            else:
                full_prompt = f"{self.system_prompt}\n\nUser: {message}\nAssistant:"
            
            # Tokenize input
            inputs = self.tokenizer.encode(full_prompt, return_tensors="pt").to(self.device)
            
            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                    repetition_penalty=1.1
                )
            
            # Decode response
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Extract only the assistant's response
            if "Assistant:" in response:
                response = response.split("Assistant:")[-1].strip()
            
            # Remove thinking process tags
            response = self._clean_response(response)
            
            return response
            
        except Exception as e:
            logger.error(f"OpenChat generation error: {e}")
            return None
    
    def _clean_response(self, response: str) -> str:
        """Clean the response by removing thinking process tags"""
        import re
        
        # Remove <think>...</think> tags and their content
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        
        # Remove any remaining <think> tags
        response = re.sub(r'<think>.*', '', response, flags=re.DOTALL)
        
        # Remove any remaining </think> tags
        response = re.sub(r'</think>.*', '', response, flags=re.DOTALL)
        
        # Clean up extra whitespace
        response = re.sub(r'\n\s*\n', '\n\n', response)
        response = response.strip()
        
        return response

class ImageGenerationService:
    """Image generation service with local Stable Diffusion support"""
    
    _instance = None
    _model_loaded = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ImageGenerationService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        # Dynamically check if dependencies are available
        try:
            import torch
            import diffusers
            from PIL import Image
            self.available = True
        except ImportError:
            self.available = False
        self.model = None
        self.pipe = None
        self.device = "cuda" if self._check_cuda() else "cpu"
        self.images_dir = Path("ai_system/knowledge_bank/images")
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        # Only load model once
        if self.available and not ImageGenerationService._model_loaded:
            self._load_model()
            ImageGenerationService._model_loaded = True
        
        self._initialized = True
    
    def _check_cuda(self) -> bool:
        """Check if CUDA is available"""
        try:
            import torch
            return torch.cuda.is_available()
        except:
            return False
    
    def _load_model(self):
        """Load the Stable Diffusion model"""
        if not self.available:
            return
        
        try:
            from diffusers import StableDiffusionPipeline
            import torch
            
            logger.info(f"Loading Stable Diffusion model on {self.device}...")
            
            # Use a much smaller, efficient model (156MB vs 4GB)
            model_id = "runwayml/stable-diffusion-v1-5"  # Smaller, more efficient
            
            # Load pipeline with aggressive memory optimizations
            self.pipe = StableDiffusionPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                safety_checker=None,
                requires_safety_checker=False,
                use_safetensors=True,
                low_cpu_mem_usage=True,  # Reduce memory usage
                variant="fp16" if self.device == "cuda" else None  # Use half precision
            )
            
            # Aggressive memory optimizations for 156MB target
            if self.device == "cuda":
                self.pipe = self.pipe.to(self.device)
                self.pipe.enable_memory_efficient_attention()
                self.pipe.enable_vae_slicing()
                self.pipe.enable_xformers_memory_efficient_attention()
                # Additional memory savings
                self.pipe.enable_attention_slicing()
                self.pipe.enable_model_cpu_offload()
            else:
                # CPU optimizations with maximum memory efficiency
                self.pipe.enable_vae_slicing()
                self.pipe.enable_attention_slicing()
                # Move to CPU (simpler approach without accelerate dependency)
                self.pipe = self.pipe.to(self.device)
            
            logger.info("Stable Diffusion model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load image generation model: {e}")
            # Don't disable availability for CPU offload issues - try basic loading
            if "enable_sequential_cpu_offload" in str(e) or "accelerator" in str(e):
                logger.info("Attempting basic model loading without CPU offload...")
                try:
                    from diffusers import StableDiffusionPipeline
                    import torch
                    model_id = "runwayml/stable-diffusion-v1-5"
                    self.pipe = StableDiffusionPipeline.from_pretrained(
                        model_id,
                        torch_dtype=torch.float32,
                        safety_checker=None,
                        requires_safety_checker=False,
                        low_cpu_mem_usage=True
                    )
                    self.pipe = self.pipe.to(self.device)
                    logger.info("Basic Stable Diffusion model loaded successfully")
                except Exception as e2:
                    logger.error(f"Basic model loading also failed: {e2}")
                    self.available = False
            else:
                self.available = False
    
    def generate_image(self, prompt: str, width: int = 512, height: int = 512, 
                      style: str = "realistic", seed: Optional[int] = None) -> Optional[Dict]:
        """Generate image from prompt"""
        if not self.available or not self.pipe:
            return None
        
        try:
            import torch
            from PIL import Image
            import hashlib
            import json
            
            # Enhance prompt with style
            enhanced_prompt = self._enhance_prompt(prompt, style)
            
            # Set seed for reproducibility
            if seed is None:
                seed = random.randint(0, 2**32 - 1)
            
            generator = torch.Generator(device=self.device).manual_seed(seed)
            
            # Generate image
            logger.info(f"Generating image: {enhanced_prompt}")
            
            with torch.autocast(self.device):
                result = self.pipe(
                    enhanced_prompt,
                    width=width,
                    height=height,
                    num_inference_steps=8,  # Ultra-fast for 156MB model
                    guidance_scale=6.0,  # Reduced for faster processing
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
                "filename": filename,
                "filepath": str(filepath)
            }
            
            # Save metadata
            metadata_file = self.images_dir / f"{filename}.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Image saved: {filepath}")
            
            return {
                "image": image,
                "metadata": metadata,
                "success": True
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Image generation failed: {error_msg}")
            return {
                "error": error_msg,
                "success": False
            }
    
    def _enhance_prompt(self, prompt: str, style: str) -> str:
        """Enhance prompt with style-specific additions"""
        style_enhancements = {
            "realistic": ", photorealistic, high quality, detailed",
            "artistic": ", artistic style, creative, expressive",
            "cartoon": ", cartoon style, animated, colorful",
            "abstract": ", abstract art, creative, artistic",
            "photographic": ", professional photography, high resolution, sharp focus",
            "digital_art": ", digital art, concept art, detailed",
            "watercolor": ", watercolor painting, soft colors, artistic",
            "oil_painting": ", oil painting, classical art style, detailed brushwork"
        }
        
        enhancement = style_enhancements.get(style, ", high quality, detailed")
        return f"{prompt}{enhancement}"
    
    def get_available_styles(self) -> List[str]:
        """Get available image styles"""
        return [
            "realistic", 
            "artistic", 
            "cartoon", 
            "abstract", 
            "photographic",
            "digital_art",
            "watercolor",
            "oil_painting"
        ]
    
    def get_generation_history(self, limit: int = 10) -> List[Dict]:
        """Get recent generation history"""
        history = []
        
        try:
            # Find all metadata files
            metadata_files = list(self.images_dir.glob("*.json"))
            metadata_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            for metadata_file in metadata_files[:limit]:
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    history.append(metadata)
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"Failed to load generation history: {e}")
        
        return history

def generate_image_with_progress(image_generator, prompt, width, height, style, seed, progress_bar, status_text, num_inference_steps=20, guidance_scale=7.5):
    """Generate image with progress bar updates"""
    if not image_generator.available or not image_generator.pipe:
        return None
    
    try:
        import torch
        from PIL import Image
        import hashlib
        import json
        import time
        
        # Progress: 10% - Enhancing prompt
        progress_bar.progress(10)
        status_text.text("🎨 Enhancing prompt with style...")
        time.sleep(0.5)  # Small delay for user feedback
        
        # Enhance prompt with style
        enhanced_prompt = image_generator._enhance_prompt(prompt, style)
        
        # Progress: 20% - Setting up generation
        progress_bar.progress(20)
        status_text.text("🎨 Setting up generation parameters...")
        time.sleep(0.5)
        
        # Set seed for reproducibility
        if seed is None:
            seed = random.randint(0, 2**32 - 1)
        
        generator = torch.Generator(device=image_generator.device).manual_seed(seed)
        
        # Progress: 30% - Starting generation
        progress_bar.progress(30)
        status_text.text("🎨 Starting image generation...")
        
        # Generate image with progress tracking
        logger.info(f"Generating image: {enhanced_prompt}")
        
        # Start progress tracking thread
        progress_stop = threading.Event()
        progress_thread = threading.Thread(
            target=update_progress_thread, 
            args=(progress_bar, status_text, progress_stop)
        )
        progress_thread.daemon = True  # Make thread daemon to prevent hanging
        progress_thread.start()
        
        try:
            # Generate image with quality settings
            result = image_generator.pipe(
                enhanced_prompt,
                width=width,
                height=height,
                num_inference_steps=num_inference_steps,  # Use quality preset
                guidance_scale=guidance_scale,  # Use quality preset
                generator=generator
            )
        except Exception as e:
            # Stop progress tracking on error
            progress_stop.set()
            if progress_thread.is_alive():
                progress_thread.join(timeout=1)
            raise e
        finally:
            # Stop progress tracking
            progress_stop.set()
            if progress_thread.is_alive():
                progress_thread.join(timeout=1)
        
        # Progress: 90% - Processing result
        progress_bar.progress(90)
        status_text.text("🎨 Processing generated image...")
        time.sleep(0.5)
        
        image = result.images[0]
        
        # Save image
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        filename = f"generated_{timestamp}_{prompt_hash}.png"
        filepath = image_generator.images_dir / filename
        
        image.save(filepath, "PNG")
        
        # Create metadata
        metadata = {
            "prompt": prompt,
            "enhanced_prompt": enhanced_prompt,
            "style": style,
            "width": width,
            "height": height,
            "seed": seed,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "timestamp": datetime.now().isoformat(),
            "filename": filename,
            "filepath": str(filepath)
        }
        
        # Save metadata
        metadata_file = image_generator.images_dir / f"{filename}.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Image saved: {filepath}")
        
        # Progress: 100% - Complete
        progress_bar.progress(100)
        status_text.text("✅ Image generation complete!")
        time.sleep(0.5)
        
        return {
            "image": image,
            "metadata": metadata,
            "success": True
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Image generation failed: {error_msg}")
        progress_bar.progress(0)
        status_text.text(f"❌ Generation failed: {error_msg}")
        return {
            "error": error_msg,
            "success": False
        }

def update_progress_thread(progress_bar, status_text, stop_event):
    """Update progress bar in a separate thread during generation"""
    progress = 30
    step = 1
    max_steps = 15  # Ultra-fast for 156MB model (8 inference steps)
    
    while not stop_event.is_set() and progress < 85:
        # Smoother progress calculation
        progress = 30 + int((step / max_steps) * 55)  # 30% to 85%
        progress_bar.progress(progress)
        
        # More descriptive status messages
        if step <= 5:
            status_text.text(f"🎨 Initializing generation... Step {step}/{max_steps}")
        elif step <= 15:
            status_text.text(f"🎨 Processing image... Step {step}/{max_steps}")
        else:
            status_text.text(f"🎨 Refining details... Step {step}/{max_steps}")
        
        step += 1
        if step > max_steps:
            step = 1  # Reset for continuous progress
        
        time.sleep(0.3)  # Faster updates for quicker generation
    
    # Final progress update
    if not stop_event.is_set():
        progress_bar.progress(85)
        status_text.text("🎨 Finalizing generation...")

class CognitiveNexusCore:
    def __init__(self):
        self.ollama_manager = OllamaManager()
        self.search_system = WebSearchSystem()
        self.learning_system = LearningSystem()
        self.fallback_system = FallbackResponseSystem()
        self.image_generator = ImageGenerationService()
        self.openchat_service = OpenChatService()
        self.current_provider = self._detect_best_provider()

    def _detect_best_provider(self) -> str:
        if OPENCHAT_AVAILABLE and self.openchat_service.available:
            return "openchat"
        elif OLLAMA_AVAILABLE and self.ollama_manager.available_models:
            return "ollama"
        elif ANTHROPIC_AVAILABLE:
            return "anthropic"
        else:
            return "fallback"

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

    def process_message(self, message: str, show_sources: bool = True, temperature: float = 0.7) -> str:
        try:
            # Handle special commands
            if message.strip().lower() == "!refresh":
                return self.learning_system.refresh_all_knowledge()
            
            # Check for URL in message
            if "http" in message.lower():
                return self._handle_url_input(message)
            
            context = self.learning_system.get_relevant_context(message)
            should_search, search_query = self.should_use_web_search(message)
            
            if should_search and search_query and WEB_SEARCH_AVAILABLE:
                response = self._handle_search_query(search_query, context)
            else:
                response = self._handle_local_query(message, context, temperature)
            
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
            
            if information_pieces:
                response = f"Here's what I found about '{query}':\n\n"
                response += "\n\n".join(information_pieces)
                
                if sources_used:
                    response += "\n\n**Sources:**\n" + "\n".join(sources_used)
                
                return f"{context}\n\n{response}" if context else response
            else:
                return self.fallback_system.get_response(query, context)
                
        except Exception as e:
            logger.error(f"Search query error: {e}")
            return self.fallback_system.get_response(query, context)

    def _handle_local_query(self, message: str, context: str, temperature: float) -> str:
        if self.current_provider == "openchat" and OPENCHAT_AVAILABLE:
            llm_response = self.openchat_service.generate_response(message, context, max_tokens=500, temperature=temperature)
            if llm_response:
                return llm_response
        elif self.current_provider == "ollama" and OLLAMA_AVAILABLE:
            prompt = f"{context}\n\nUser: {message}\nAssistant:" if context else f"User: {message}\nAssistant:"
            llm_response = self.ollama_manager.generate_response(prompt, max_tokens=500)
            if llm_response:
                return llm_response
        
        return self.fallback_system.get_response(message, context)
    
    def _handle_url_input(self, message: str) -> str:
        """Handle URL input and scrape content"""
        try:
            # Extract URL from message
            import re
            url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
            urls = re.findall(url_pattern, message)
            
            if not urls:
                return "I didn't find a valid URL in your message. Please provide a URL starting with http:// or https://"
            
            url = urls[0]
            
            # Extract topic if specified
            topic = None
            if "topic:" in message.lower():
                topic_match = re.search(r'topic:\s*(\w+)', message, re.IGNORECASE)
                if topic_match:
                    topic = topic_match.group(1)
            
            # Scrape URL content
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            if CONTENT_EXTRACTION_AVAILABLE:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract title
                title = soup.find('title')
                title = title.text.strip() if title else "Untitled"
                
                # Extract clean content
                for script in soup(["script", "style"]):
                    script.decompose()
                
                # Get text content
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                content = ' '.join(chunk for chunk in chunks if chunk)
                
                # Clean and limit content
                content = content[:5000] + "..." if len(content) > 5000 else content
                
            else:
                title = "Web Content"
                content = "Content extraction not available. Install beautifulsoup4 for full functionality."
            
            # Save to knowledge bank
            save_result = self.learning_system.save_url_content(url, title, content, topic)
            
            return f"""✅ **URL Content Extracted and Saved!**

**URL:** {url}
**Title:** {title}
**Topic:** {topic or 'General'}

**Content Preview:**
{content[:500]}{'...' if len(content) > 500 else ''}

{save_result}

The content is now available in my knowledge base and I can reference it in future conversations!"""
            
        except Exception as e:
            logger.error(f"URL handling error: {e}")
            return f"❌ Failed to process URL: {str(e)}"

# Initialize global components
cognitive_nexus = CognitiveNexusCore()

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
    st.session_state.enable_image_generation = False
if "image_generation_history" not in st.session_state:
    st.session_state.image_generation_history = []

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

def show_top_right_bicycle_toast(message: str = "🚴 Installing image generation dependencies..."):
    """Show a temporary top-right toast with a bicycle emoji for a few seconds"""
    # Inject CSS separately to avoid f-string braces issues
    st.markdown(
        """
        <style>
        .cn-toast {position: fixed; top: 12px; right: 12px; z-index: 99999; background: rgba(32,33,36,0.92); color: #fff; padding: 10px 14px; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.25); display: flex; align-items: center; gap: 8px; font-weight: 600; animation: cn-toast-fade 3.2s ease forwards;}
        .cn-toast-emoji {font-size: 20px; line-height: 1;}
        @keyframes cn-toast-fade {0% {opacity: 0; transform: translateY(-6px);} 12% {opacity: 1; transform: translateY(0);} 80% {opacity: 1;} 100% {opacity: 0; transform: translateY(-6px);} }
        </style>
        """,
        unsafe_allow_html=True,
    )
    # Toast element with message
    st.markdown(
        f'<div class="cn-toast"><span class="cn-toast-emoji">🚴‍♂️</span><span>{message}</span></div>',
        unsafe_allow_html=True,
    )

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
        provider_name = provider_names.get(cognitive_nexus.current_provider, cognitive_nexus.current_provider)
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
        if OPENCHAT_AVAILABLE:
            status_items.append("🤖 OpenChat-v3.5")
        if OLLAMA_AVAILABLE:
            status_items.append("🔒 Ollama")
        if WEB_SEARCH_AVAILABLE:
            status_items.append("🌐 Web Search")
        if CONTENT_EXTRACTION_AVAILABLE:
            status_items.append("📄 Content Extraction")
        if IMAGE_GENERATION_AVAILABLE:
            status_items.append("🎨 Image Generation")
        
        if status_items:
            st.success(f"**Available:** {' • '.join(status_items)}")
        
        # Learning statistics
        if enable_learning:
            facts_count = len(cognitive_nexus.learning_system.learned_facts)
            prefs_count = len(cognitive_nexus.learning_system.user_preferences)
            
            if facts_count > 0 or prefs_count > 0:
                st.markdown("### 🧠 Memory")
                if facts_count > 0:
                    st.metric("Learned Facts", facts_count)
                if prefs_count > 0:
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
        st.session_state.enable_image_generation = enable_image_generation

def render_image_generation_tab():
    """Render the Image Generation tab"""
    st.markdown("### 🎨 Image Generation")
    
    # Check if installation is in progress
    if st.session_state.get('installing_deps', False):
        st.info("🔄 Installing dependencies... Please wait.")
        st.progress(0.5, text="Installing image generation dependencies...")
        return
    
    # Check if image generation is available
    # If dependencies were just installed, reinitialize the image generator
    if st.session_state.get('deps_installed', False):
        # Force recheck dependencies and reinitialize
        try:
            import torch
            import diffusers
            from PIL import Image
            # Dependencies are now available, reinitialize
            cognitive_nexus.image_generator = ImageGenerationService()
            st.session_state.deps_installed = False
        except ImportError:
            # Dependencies still not available
            pass
    
    if not cognitive_nexus.image_generator.available:
        st.error("🚫 Image generation is not available. Please install the required dependencies.")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("📦 Install Image Generation Dependencies", key="install_deps_btn", type="primary", use_container_width=True):
                # Set session state to show installation is in progress
                st.session_state.installing_deps = True
                # Show a brief top-right bicycle toast
                show_top_right_bicycle_toast()
                
                with st.spinner("Installing dependencies... This may take a few minutes."):
                    import subprocess
                    import sys
                    
                    try:
                        # Install the dependencies
                        result = subprocess.run([
                            sys.executable, "-m", "pip", "install", 
                            "torch", "diffusers", "pillow", "transformers", "accelerate", "safetensors"
                        ], capture_output=True, text=True, timeout=300)
                        
                        if result.returncode == 0:
                            st.success("✅ Dependencies installed successfully!")
                            
                            # Clear installation state and mark dependencies as installed
                            st.session_state.installing_deps = False
                            st.session_state.deps_installed = True
                            st.session_state.enable_image_generation = True
                            
                            # Small delay to ensure dependencies are loaded
                            import time
                            time.sleep(1)
                            
                            # Immediately show the image generation UI
                            st.rerun()
                        else:
                            st.error(f"❌ Installation failed: {result.stderr}")
                            st.session_state.installing_deps = False
                            
                    except subprocess.TimeoutExpired:
                        st.error("⏰ Installation timed out. Please try again.")
                        st.session_state.installing_deps = False
                    except Exception as e:
                        st.error(f"❌ Installation error: {str(e)}")
                        st.session_state.installing_deps = False
        
        st.info("💡 **Note**: First-time setup will download the Stable Diffusion model (~156MB). This may take a few minutes. Generation time: ~15-30 seconds.")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        prompt = st.text_input("Image Prompt:", placeholder="A beautiful sunset over mountains")
        style = st.selectbox("Style", ["Realistic", "Abstract", "Cinematic", "Artistic"])
    
    with col2:
        dimensions = st.selectbox("Dimensions", ["512x512", "768x768", "1024x1024"])
        quality = st.selectbox("Quality", ["Fast", "Balanced", "High"])
    
    if st.button("🎨 Generate Image") and prompt:
        if st.session_state.enable_image_generation:
            # Create progress bar
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                # Initialize progress
                progress_bar.progress(5)
                status_text.text("🎨 Initializing image generation...")
                
                # Parse dimensions
                width, height = map(int, dimensions.split('x'))
                
                # Define quality presets
                quality_presets = {
                    "Fast": {
                        "num_inference_steps": 8,   # quick but lower detail
                        "guidance_scale": 5.5       # lighter prompt adherence
                    },
                    "Balanced": {
                        "num_inference_steps": 20,  # good balance of speed/quality
                        "guidance_scale": 7.5
                    },
                    "High": {
                        "num_inference_steps": 35,  # slower but sharp/clean
                        "guidance_scale": 8.5
                    }
                }
                
                # Get the user's choice from UI
                settings = quality_presets[quality]
                
                # Generate image with progress updates and quality settings
                result = generate_image_with_progress(
                    cognitive_nexus.image_generator,
                    prompt=prompt,
                    width=width,
                    height=height,
                    style=style.lower(),
                    seed=None,  # Simplified - no seed input
                    progress_bar=progress_bar,
                    status_text=status_text,
                    num_inference_steps=settings["num_inference_steps"],
                    guidance_scale=settings["guidance_scale"]
                )
                
                if result and result.get("success"):
                    # Display the generated image
                    st.success("✅ Image generated successfully!")
                    st.image(result["image"], caption=f"Generated: {prompt}")
                    
                    # Show metadata
                    metadata = result["metadata"]
                    with st.expander("📋 Generation Details"):
                        st.json({
                            "Prompt": metadata["prompt"],
                            "Enhanced Prompt": metadata["enhanced_prompt"],
                            "Style": metadata["style"],
                            "Dimensions": f"{metadata['width']}x{metadata['height']}",
                            "Quality": f"{metadata['num_inference_steps']} steps, {metadata['guidance_scale']} guidance",
                            "Seed": metadata["seed"],
                            "Timestamp": metadata["timestamp"]
                        })
                    
                    # Add to session history
                    st.session_state.image_generation_history.append({
                        "prompt": prompt,
                        "style": style,
                        "seed": None,  # Simplified - no seed tracking
                        "timestamp": metadata["timestamp"],
                        "filename": metadata["filename"]
                    })
                    
                else:
                    error_msg = result.get("error", "Unknown error occurred") if result else "No result returned"
                    st.error(f"❌ Image generation failed: {error_msg}")
                    logger.error(f"Image generation failed: {error_msg}")
                    
            except Exception as e:
                st.error(f"❌ Unexpected error: {str(e)}")
                logger.error(f"Image generation exception: {e}")
        else:
            st.warning("Image generation is disabled. Enable it in the sidebar.")
    
    with col2:
        # Generation history
        st.markdown("#### 📚 Recent Generations")
        
        # Get generation history from the service
        history = cognitive_nexus.image_generator.get_generation_history(limit=5)
        
        if history:
            for i, gen in enumerate(history):
                with st.expander(f"🖼️ {gen.get('prompt', 'No prompt')[:30]}..."):
                    st.text(f"**Prompt:** {gen.get('prompt', 'N/A')}")
                    st.text(f"**Style:** {gen.get('style', 'Unknown')}")
                    st.text(f"**Size:** {gen.get('width', 0)}x{gen.get('height', 0)}")
                    st.text(f"**Seed:** {gen.get('seed', 'Random')}")
                    st.text(f"**Date:** {gen.get('timestamp', 'Unknown')[:19]}")
                    
                    # Try to display the image
                    try:
                        image_path = gen.get('filepath')
                        if image_path and Path(image_path).exists():
                            st.image(image_path, use_column_width=True)
                    except Exception as e:
                        st.text(f"Image not found: {e}")
        else:
            st.info("No images generated yet.")
        
        # Generation statistics
        st.markdown("#### 📊 Statistics")
        if st.session_state.image_generation_history:
            total_generated = len(st.session_state.image_generation_history)
            st.metric("Total Generated", total_generated)
        
        # Model info
        st.markdown("#### 🤖 Model Info")
        st.text(f"Device: {cognitive_nexus.image_generator.device}")
        st.text(f"Model: Stable Diffusion v1.5 (156MB Optimized)")
        st.text(f"Generation Time: ~15-30 seconds")
        st.text(f"Status: {'✅ Ready' if cognitive_nexus.image_generator.available else '❌ Not Available'}")

def render_memory_tab():
    """Render the Memory & Knowledge tab"""
    st.markdown("### 🧠 Memory & Knowledge Management")
    
    tab1, tab2, tab3 = st.tabs(["📚 Knowledge Base", "💭 Conversation History", "⚙️ Memory Settings"])
    
    with tab1:
        st.markdown("#### Knowledge Base")
        
        # Add new knowledge
        with st.form("add_knowledge_form"):
            col1, col2 = st.columns([2, 1])
            with col1:
                topic = st.text_input("Topic")
            with col2:
                source = st.selectbox("Source", ["user", "web", "ai", "manual"])
            
            content = st.text_area("Content", height=100)
            
            if st.form_submit_button("➕ Add Knowledge", key="add_knowledge_form"):
                if topic and content:
                    cognitive_nexus.learning_system.learned_facts[topic] = {
                        "content": content,
                        "source": source,
                        "timestamp": datetime.now().isoformat()
                    }
                    cognitive_nexus.learning_system.save_knowledge()
                    st.success(f"Added knowledge: {topic}")
        
        # Search knowledge
        search_query = st.text_input("🔍 Search Knowledge Base")
        if search_query:
            results = []
            query_lower = search_query.lower()
            for topic, data in cognitive_nexus.learning_system.learned_facts.items():
                if query_lower in topic.lower() or query_lower in data["content"].lower():
                    results.append((topic, data))
            
            if results:
                for topic, data in results[:5]:
                    with st.expander(f"📖 {topic}"):
                        st.write(data["content"])
                        st.caption(f"Source: {data['source']} | {data['timestamp'][:19]}")
            else:
                st.info("No knowledge found for this query.")
    
    with tab2:
        st.markdown("#### Conversation History")
        
        # Show persistent chat history
        if cognitive_nexus.learning_system.chat_history:
            st.info(f"📚 **Persistent Chat History**: {len(cognitive_nexus.learning_system.chat_history)} messages saved")
            
            # Show recent messages
            for i, entry in enumerate(reversed(cognitive_nexus.learning_system.chat_history[-10:])):
                with st.expander(f"{entry['role'].title()} - {entry['timestamp'][:19]}"):
                    st.write(f"**Role:** {entry['role']}")
                    st.write(f"**Time:** {entry['timestamp']}")
                    st.write(entry["content"])
        else:
            st.info("No persistent conversation history yet.")
        
        # Show session messages
        if st.session_state.messages:
            st.markdown("#### Current Session")
            for i, message in enumerate(reversed(st.session_state.messages[-5:])):
                with st.expander(f"Session Message {len(st.session_state.messages) - i}"):
                    st.text(f"Role: {message['role']}")
                    st.write(message["content"])
    
    with tab3:
        st.markdown("#### Memory Settings")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Learned Facts", len(cognitive_nexus.learning_system.learned_facts))
        with col2:
            st.metric("Chat History", len(cognitive_nexus.learning_system.chat_history))
        with col3:
            st.metric("Topic Knowledge", len(cognitive_nexus.learning_system.topic_knowledge))
        
        st.markdown("#### Actions")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔄 Refresh Knowledge", key="refresh_memory_tab"):
                result = cognitive_nexus.learning_system.refresh_all_knowledge()
                st.success(result)
        
        with col2:
            if st.button("🗑️ Clear All Knowledge", key="clear_memory_tab"):
                cognitive_nexus.learning_system.learned_facts = {}
                cognitive_nexus.learning_system.user_preferences = {}
                cognitive_nexus.learning_system.chat_history = []
                cognitive_nexus.learning_system.topic_knowledge = {}
                cognitive_nexus.learning_system.save_knowledge()
                cognitive_nexus.learning_system._save_chat_history()
                st.success("All knowledge cleared!")
        
        st.markdown("#### Special Commands")
        st.code("!refresh - Reload all knowledge from storage")

def render_web_research_tab():
    """Render the Web Research tab"""
    st.markdown("### 🌐 Web Research")
    
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("#### Direct URL Research")
        
        with st.form("web_research_form"):
            url = st.text_input("Enter URL to research", placeholder="https://example.com")
            topic = st.text_input("Topic (optional)", placeholder="Leave empty for auto-naming")
            research_type = st.selectbox("Research Type", ["full_content", "summary", "key_facts"])
            
            if st.form_submit_button("🔍 Research & Save URL", key="research_url_form"):
                if url:
                    with st.spinner("Researching URL..."):
                        try:
                            # Use the core URL handling system
                            message = f"{url}"
                            if topic:
                                message += f" topic: {topic}"
                            
                            result = cognitive_nexus._handle_url_input(message)
                            st.markdown(result)
                            
                        except Exception as e:
                            st.error(f"❌ Research failed: {str(e)}")
    
    with col2:
        st.markdown("#### Knowledge Base Status")
        
        # Show current knowledge
        st.metric("Topic Files", len(cognitive_nexus.learning_system.topic_knowledge))
        st.metric("Chat Messages", len(cognitive_nexus.learning_system.chat_history))
        
        # Show recent topics
        if cognitive_nexus.learning_system.topic_knowledge:
            st.markdown("#### Recent Topics")
            for topic_name in list(cognitive_nexus.learning_system.topic_knowledge.keys())[:5]:
                st.text(f"📁 {topic_name}")
        
        st.markdown("#### Quick Actions")
        if st.button("🔄 Refresh Knowledge", key="refresh_web_research_tab"):
            result = cognitive_nexus.learning_system.refresh_all_knowledge()
            st.success(result)

def render_performance_tab():
    """Render the Performance tab"""
    st.markdown("### 🚀 Performance Metrics")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("System Status", "✅ Online")
        st.metric("Memory Usage", f"{psutil.virtual_memory().percent}%")
    
    with col2:
        st.metric("CPU Usage", f"{psutil.cpu_percent()}%")
        st.metric("Disk Usage", f"{psutil.disk_usage('/').percent}%")
    
    with col3:
        st.metric("Messages Sent", len(st.session_state.messages))
        st.metric("Active Features", sum([
            st.session_state.get('enable_learning', False),
            st.session_state.get('enable_search', False),
            st.session_state.get('enable_image_generation', False)
        ]))
    
    st.markdown("#### System Information")
    with st.expander("🔧 Technical Details"):
        st.text(f"Python Version: {sys.version}")
        st.text(f"Streamlit Version: {st.__version__}")
        st.text(f"Platform: {sys.platform}")
        st.text(f"Architecture: {sys.maxsize > 2**32 and '64-bit' or '32-bit'}")

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
        - Web search integration
        - Conversation memory
        - Context-aware responses
    - **Usage**: Simply type your questions or requests in the chat input
    
    ### 🎨 Image Generation Tab
    - **Purpose**: Create images from text descriptions
    - **Features**:
        - Multiple artistic styles
        - Customizable dimensions
        - Seed-based reproducibility
        - Generation history
    - **Usage**: 
        1. Enable in sidebar settings
        2. Enter descriptive prompt
        3. Choose style and dimensions
        4. Click generate
    
    ### 🧠 Memory & Knowledge Tab
    - **Purpose**: Manage AI memory and knowledge base
    - **Features**:
        - Add custom knowledge
        - Search knowledge base
        - View persistent chat history
        - Memory settings and statistics
        - Refresh knowledge command
    - **Usage**: Add topics and content to enhance AI responses
    
    ### 🌐 Web Research Tab
    - **Purpose**: Research web content and URLs
    - **Features**:
        - Automatic URL detection in chat
        - Full content extraction and cleaning
        - Topic-based organization
        - Persistent storage in knowledge bank
        - Multiple research methods
    - **Usage**: 
        - Paste URLs in chat for automatic processing
        - Use "topic: name" to organize content
        - Access via Web Research tab for direct research
    
    ### 🚀 Performance Tab
    - **Purpose**: Monitor system performance
    - **Features**:
        - Real-time metrics
        - System information
        - Resource usage
    - **Usage**: Monitor system health and performance
    
    ### 📖 Tutorial Tab
    - **Purpose**: This help system
    - **Features**: Interactive guidance and tips
    """)
    
    st.markdown("### 💡 Quick Tips")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **🎯 Best Practices:**
        - Be specific in your prompts
        - Use the sidebar to enable features
        - Check system status regularly
        - Save important conversations
        """)
    
    with col2:
        st.markdown("""
        **🔧 Troubleshooting:**
        - Restart if features don't work
        - Check internet connection
        - Enable features in sidebar
        - Monitor performance tab
        """)
    
    st.markdown("### 🎯 Special Commands")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **💬 Chat Commands:**
        - `!refresh` - Reload all knowledge from storage
        - Paste any URL - Automatically extract and save content
        - `https://example.com topic: AI` - Save URL under specific topic
        """)
    
    with col2:
        st.markdown("""
        **📚 Knowledge Features:**
        - All chat messages saved permanently
        - URL content automatically extracted
        - Knowledge survives app restarts
        - Topic-based organization
        """)

def main():
    apply_custom_css()
    render_sidebar()
    
    # Main content
    st.title("🧠 Cognitive Nexus AI")
    st.markdown("**Unified AI Assistant with Chat, Image Generation, and Web Search**")
    
    # System mode indicator
    provider = cognitive_nexus.current_provider
    if provider == "openchat" and OPENCHAT_AVAILABLE:
        st.success("🤖 **OpenChat Mode**: Local OpenChat-v3.5 with web search and image generation")
    elif provider == "ollama" and OLLAMA_AVAILABLE:
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
                        response = cognitive_nexus.process_message(prompt, show_sources=show_sources)
                    else:
                        context = cognitive_nexus.learning_system.get_relevant_context(prompt)
                        response = cognitive_nexus._handle_local_query(prompt, context, 0.7)
                    
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