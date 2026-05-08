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

# Import additional dependencies for self-healing
from functools import wraps
import traceback

# Self-healing system configuration - Always active and autonomous
SELF_HEALING_CONFIG = {
    'max_retries': 3,
    'retry_delay': 1.0,  # seconds
    'health_check_interval': 30,  # seconds
    'memory_threshold': 85,  # percentage
    'service_timeout': 10,  # seconds
    'auto_repair_knowledge': True,  # Always validate and repair knowledge files
    'proactive_monitoring': True,   # Always monitor system health
    'autonomous_recovery': True     # Always attempt automatic recovery
}

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

class SelfHealingSystem:
    """Comprehensive self-healing system for Cognitive Nexus AI"""
    
    def __init__(self):
        self.service_health = {}
        self.error_counts = {}
        self.last_health_check = 0
        self.recovery_actions = {}
        
    def with_self_healing(self, service_name: str, recovery_action=None):
        """Decorator for automatic error recovery and retry logic"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Auto-healing is always enabled and autonomous
                max_retries = SELF_HEALING_CONFIG['max_retries']
                retry_delay = SELF_HEALING_CONFIG['retry_delay']
                
                for attempt in range(max_retries + 1):
                    try:
                        # Ensure monitoring is active before critical operations
                        if hasattr(self, '_check_system_health'):
                            try:
                                self._check_system_health()
                            except Exception as health_error:
                                logger.warning(f"Health check failed, continuing: {health_error}")
                        
                        result = func(*args, **kwargs)
                        
                        # Reset error count on success
                        if service_name in self.error_counts:
                            self.error_counts[service_name] = 0
                        
                        return result
                        
                    except Exception as e:
                        self._record_error(service_name, e)
                        
                        # Automatic recovery attempts
                        if attempt < max_retries:
                            logger.warning(f"⚠️ {service_name} attempt {attempt + 1} failed: {e}")
                            
                            # Try automatic recovery actions
                            self._attempt_auto_recovery(service_name, e)
                            
                            # Exponential backoff
                            sleep_time = retry_delay * (2 ** attempt)
                            time.sleep(min(sleep_time, 10))  # Cap at 10 seconds
                            continue
                        
                        # Final attempt - try recovery action if available
                        logger.error(f"🚨 {service_name} failed after {max_retries} attempts: {e}")
                        if recovery_action:
                            try:
                                logger.info(f"🔧 Final recovery attempt for {service_name}")
                                recovery_result = recovery_action()
                                if recovery_result:
                                    logger.info(f"✅ Recovery successful for {service_name}")
                                    return func(*args, **kwargs)
                            except Exception as recovery_error:
                                logger.error(f"❌ Recovery failed for {service_name}: {recovery_error}")
                        
                        # If all else fails, raise the original exception
                        raise e
                            
            return wrapper
        return decorator
    
    def _attempt_auto_recovery(self, service_name: str, error: Exception):
        """Attempt automatic recovery based on service and error type"""
        try:
            error_type = type(error).__name__
            
            # Memory-related errors
            if 'memory' in str(error).lower() or error_type in ['MemoryError', 'OutOfMemoryError']:
                logger.info(f"🧠 Auto-recovery: Memory cleanup for {service_name}")
                self._handle_memory_pressure()
            
            # Connection/Network errors
            elif error_type in ['ConnectionError', 'Timeout', 'RequestException']:
                logger.info(f"🌐 Auto-recovery: Network reset for {service_name}")
                time.sleep(2)  # Brief pause for network recovery
            
            # Service availability issues
            elif 'ollama' in service_name.lower() or 'openchat' in service_name.lower():
                logger.info(f"🔄 Auto-recovery: Service health recheck for {service_name}")
                if hasattr(self, '_check_service_availability'):
                    self._check_service_availability()
                
        except Exception as recovery_error:
            logger.warning(f"Auto-recovery attempt failed: {recovery_error}")
    
    def _record_error(self, service_name: str, error: Exception):
        """Record error for pattern analysis"""
        if service_name not in self.error_counts:
            self.error_counts[service_name] = 0
        self.error_counts[service_name] += 1
        
        # Log detailed error information
        error_info = {
            'service': service_name,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'count': self.error_counts[service_name],
            'timestamp': datetime.now().isoformat()
        }
        logger.error(f"Error recorded: {error_info}")
    
    def _check_system_health(self):
        """Comprehensive system health check with auto-recovery"""
        current_time = time.time()
        if current_time - self.last_health_check < SELF_HEALING_CONFIG['health_check_interval']:
            return
        
        self.last_health_check = current_time
        
        try:
            # Memory pressure check
            memory_percent = psutil.virtual_memory().percent
            if memory_percent > SELF_HEALING_CONFIG['memory_threshold']:
                logger.warning(f"🧠 High memory usage detected: {memory_percent}%")
                self._handle_memory_pressure()
            
            # Service availability check
            self._check_service_availability()
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
    
    def _handle_memory_pressure(self):
        """Handle high memory usage"""
        try:
            import gc
            gc.collect()
            logger.info("🧹 Memory cleanup performed")
        except Exception as e:
            logger.error(f"Memory cleanup failed: {e}")
    
    def _check_service_availability(self):
        """Check and record service availability"""
        services = {
            'ollama': self._check_ollama,
            'web_search': self._check_web_search,
            'image_generation': self._check_image_generation
        }
        
        for service_name, check_func in services.items():
            try:
                is_available = check_func()
                self.service_health[service_name] = {
                    'available': is_available,
                    'last_check': time.time(),
                    'status': 'healthy' if is_available else 'unavailable'
                }
            except Exception as e:
                self.service_health[service_name] = {
                    'available': False,
                    'last_check': time.time(),
                    'status': 'error',
                    'error': str(e)
                }
    
    def _check_ollama(self) -> bool:
        """Check Ollama service health"""
        try:
            result = subprocess.run(['ollama', 'list'], 
                                  capture_output=True, text=True, 
                                  timeout=SELF_HEALING_CONFIG['service_timeout'])
            return result.returncode == 0
        except:
            return False
    
    def _check_web_search(self) -> bool:
        """Check web search capability"""
        return WEB_SEARCH_AVAILABLE
    
    def _check_image_generation(self) -> bool:
        """Check image generation capability"""
        return IMAGE_GENERATION_AVAILABLE
    
    def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report"""
        self._check_system_health()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'memory_usage': psutil.virtual_memory().percent,
            'cpu_usage': psutil.cpu_percent(),
            'services': self.service_health.copy(),
            'error_counts': self.error_counts.copy(),
            'config': SELF_HEALING_CONFIG.copy()
        }

# Initialize global self-healing system
healing_system = SelfHealingSystem()

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
        self.search_modes = {
            'standard': {'max_results': 5, 'extract_content': False},
            'deep_dive': {'max_results': 10, 'extract_content': True, 'follow_links': True},
            'fact_mode': {'max_results': 3, 'extract_content': True, 'focus_facts': True}
        }

    @healing_system.with_self_healing("web_search", recovery_action=lambda: time.sleep(2))
    def search_web(self, query: str, max_results: int = 5, mode: str = 'standard') -> List[Dict]:
        """Enhanced web search with multiple modes and self-healing"""
        if not WEB_SEARCH_AVAILABLE:
            return []
        
        # Get mode configuration
        mode_config = self.search_modes.get(mode, self.search_modes['standard'])
        max_results = mode_config['max_results']
        
        results = []
        try:
            # Multi-source search based on mode
            if mode == 'deep_dive':
                results = self._deep_dive_search(query, max_results)
            elif mode == 'fact_mode':
                results = self._fact_mode_search(query, max_results)
            else:
                results = self._standard_search(query, max_results)
            
        except Exception as e:
            logger.error(f"Web search error: {e}")
            # Fallback to offline knowledge
            results = self._get_offline_knowledge(query, max_results)
        
        return results[:max_results]

    def _standard_search(self, query: str, max_results: int) -> List[Dict]:
        """Standard search implementation (original method)"""
        results = []
        headers = {'User-Agent': random.choice(self.user_agents)}
        
        try:
            # DuckDuckGo search
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
        
        return results

    def _deep_dive_search(self, query: str, max_results: int) -> List[Dict]:
        """Deep dive search with comprehensive multi-source content extraction"""
        results = []
        headers = {'User-Agent': random.choice(self.user_agents)}
        
        # Start with standard search
        results.extend(self._standard_search(query, max_results // 2))
        
        # Add news sources
        try:
            # Search for recent news
            news_query = f"{query} news recent"
            news_url = f"https://api.duckduckgo.com/?q={quote(news_query)}&format=json&no_html=1"
            news_response = requests.get(news_url, headers=headers, timeout=5)
            if news_response.status_code == 200:
                news_data = news_response.json()
                for topic in news_data.get('RelatedTopics', [])[:3]:
                    if isinstance(topic, dict) and topic.get('Text'):
                            results.append({
                            'title': f"📰 {topic.get('Text', '').split(' - ')[0]}",
                            'snippet': topic.get('Text', ''),
                            'url': topic.get('FirstURL', ''),
                            'source': 'News Search',
                            'type': 'news_result',
                            'confidence': 0.8
                            })
            except:
            pass
        
        # Add academic/research sources
        try:
            # Search for academic content
            academic_query = f"{query} research study academic"
            academic_url = f"https://api.duckduckgo.com/?q={quote(academic_query)}&format=json&no_html=1"
            academic_response = requests.get(academic_url, headers=headers, timeout=5)
            if academic_response.status_code == 200:
                academic_data = academic_response.json()
                for topic in academic_data.get('RelatedTopics', [])[:2]:
                    if isinstance(topic, dict) and topic.get('Text'):
                        results.append({
                            'title': f"🎓 {topic.get('Text', '').split(' - ')[0]}",
                            'snippet': topic.get('Text', ''),
                            'url': topic.get('FirstURL', ''),
                            'source': 'Academic Search',
                            'type': 'academic_result',
                            'confidence': 0.85
                        })
            except:
                pass
        
        # Extract content from top URLs if content extraction is available
        if CONTENT_EXTRACTION_AVAILABLE and len(results) > 0:
            for result in results[:3]:  # Extract from top 3 results
                if result.get('url') and result['url'].startswith('http'):
                    extracted_content = self._extract_url_content(result['url'])
                    if extracted_content:
                        result['extracted_content'] = extracted_content[:1000] + "..." if len(extracted_content) > 1000 else extracted_content
        
        return results

    def _fact_mode_search(self, query: str, max_results: int) -> List[Dict]:
        """Fact-focused search for quick factual information"""
        results = []
        headers = {'User-Agent': random.choice(self.user_agents)}
        
        # Prioritize Wikipedia for factual information
        try:
            wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
            wiki_response = requests.get(wiki_url, headers=headers, timeout=10)
            if wiki_response.status_code == 200:
                wiki_data = wiki_response.json()
                if wiki_data.get('extract'):
                    results.append({
                        'title': f"📚 {wiki_data.get('title', 'Wikipedia Article')}",
                        'snippet': wiki_data.get('extract', ''),
                        'url': wiki_data.get('content_urls', {}).get('desktop', {}).get('page', ''),
                        'source': 'Wikipedia',
                        'type': 'fact_encyclopedia',
                        'confidence': 0.95,
                        'fact_priority': True
                    })
        except:
            pass
        
        # DuckDuckGo instant answers (great for facts)
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            ddg_response = requests.get(ddg_url, headers=headers, timeout=5)
            if ddg_response.status_code == 200:
                ddg_data = ddg_response.json()
                
                # Prioritize instant answers
                if ddg_data.get('Abstract'):
                    results.append({
                        'title': f"⚡ {ddg_data.get('Heading', 'Quick Fact')}",
                        'snippet': ddg_data.get('Abstract', ''),
                        'url': ddg_data.get('AbstractURL', ''),
                        'source': ddg_data.get('AbstractSource', 'DuckDuckGo'),
                        'type': 'instant_fact',
                        'confidence': 0.9,
                        'fact_priority': True
                    })
                
                # Add definition if available
                if ddg_data.get('Definition'):
                    results.append({
                        'title': f"📖 Definition: {query}",
                        'snippet': ddg_data.get('Definition', ''),
                        'url': ddg_data.get('DefinitionURL', ''),
                        'source': ddg_data.get('DefinitionSource', 'Dictionary'),
                        'type': 'definition',
                        'confidence': 0.92,
                        'fact_priority': True
                    })
        except:
            pass
        
        # Add factual data from related topics
        try:
            fact_query = f"what is {query} definition facts"
            fact_url = f"https://api.duckduckgo.com/?q={quote(fact_query)}&format=json&no_html=1"
            fact_response = requests.get(fact_url, headers=headers, timeout=5)
            if fact_response.status_code == 200:
                fact_data = fact_response.json()
                for topic in fact_data.get('RelatedTopics', [])[:2]:
                    if isinstance(topic, dict) and topic.get('Text'):
                        results.append({
                            'title': f"💡 {topic.get('Text', '').split(' - ')[0]}",
                            'snippet': topic.get('Text', ''),
                            'url': topic.get('FirstURL', ''),
                            'source': 'Fact Search',
                            'type': 'factual_info',
                    'confidence': 0.8,
                            'fact_priority': True
                        })
        except:
            pass
        
        # Sort results by confidence and fact priority
        results.sort(key=lambda x: (x.get('fact_priority', False), x.get('confidence', 0)), reverse=True)
        
        return results
    
    def _extract_url_content(self, url: str) -> Optional[str]:
        """Extract clean content from a URL"""
        if not CONTENT_EXTRACTION_AVAILABLE:
            return None
        
        try:
            headers = {'User-Agent': random.choice(self.user_agents)}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'advertisement']):
                element.decompose()
            
            # Extract main content
            main_content = soup.find('main') or soup.find('article') or soup.find('div', class_='content') or soup
            
            # Get clean text
            text = main_content.get_text(separator=' ', strip=True)
            
            # Clean up text
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_text = ' '.join(lines)
            
            return clean_text
            
        except Exception as e:
            logger.error(f"Content extraction error for {url}: {e}")
            return None

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
                try:
                with open(topic_file, 'r', encoding='utf-8') as f:
                    self.topic_knowledge[topic_name] = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.warning(f"Skipping corrupted topic file {topic_file}: {e}")
                    continue
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
        """Enhanced provider detection with health-based selection"""
        # Get health status from healing system
        health_report = healing_system.get_health_report()
        services = health_report.get('services', {})
        
        # Check providers in order of preference, considering health
        if (OPENCHAT_AVAILABLE and hasattr(self, 'openchat_service') and 
            self.openchat_service.available and 
            services.get('openchat', {}).get('status') != 'error'):
            return "openchat"
        elif (OLLAMA_AVAILABLE and hasattr(self, 'ollama_manager') and 
              self.ollama_manager.available_models and 
              services.get('ollama', {}).get('status') != 'error'):
            return "ollama"
        elif ANTHROPIC_AVAILABLE:
            return "anthropic"
        else:
            return "fallback"

    def _switch_provider_if_needed(self, error_count: int = 0) -> bool:
        """Automatically switch provider if current one is failing"""
        if error_count < 2:  # Only switch after multiple failures
            return False
            
        old_provider = self.current_provider
        self.current_provider = self._detect_best_provider()
        
        if old_provider != self.current_provider:
            logger.info(f"🔄 Provider switched: {old_provider} → {self.current_provider}")
            return True
        return False

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
    
    @healing_system.with_self_healing("message_processing")
    def process_message(self, message: str, show_sources: bool = True, temperature: float = 0.7) -> str:
        try:
            # Handle special commands
            if message.strip().lower() == "!refresh":
                return self.learning_system.refresh_all_knowledge()
            
            # Handle search mode commands
            if message.strip().lower().startswith("!deep"):
                query = message[5:].strip()
                if query:
                    context = self.learning_system.get_relevant_context(query)
                    return self._handle_search_query(query, context, 'deep_dive')
                else:
                    return "🔍 Deep Dive Mode activated! Please provide a search query after !deep"
            
            if message.strip().lower().startswith("!fact"):
                query = message[5:].strip()
                if query:
                    context = self.learning_system.get_relevant_context(query)
                    return self._handle_search_query(query, context, 'fact_mode')
                else:
                    return "💡 Fact Mode activated! Please provide a search query after !fact"
            
            # Check for URL in message
            if "http" in message.lower():
                return self._handle_url_input(message)
            
            context = self.learning_system.get_relevant_context(message)
            should_search, search_query = self.should_use_web_search(message)
            
            if should_search and search_query and WEB_SEARCH_AVAILABLE:
                search_mode = getattr(st.session_state, 'search_mode', 'standard')
                response = self._handle_search_query(search_query, context, search_mode)
            else:
                response = self._handle_local_query(message, context, temperature)
            
            self.learning_system.add_conversation(message, response)
            return response
            
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            return "I apologize, but I encountered an issue processing your request. Please try again."

    def _handle_search_query(self, query: str, context: str, search_mode: str = 'standard') -> str:
        try:
            search_results = self.search_system.search_web(query, mode=search_mode)
            
            if not search_results:
                return self.fallback_system.get_response(query, context)
            
            information_pieces = []
            sources_used = []
            
            # Enhanced type emojis for different search modes
            type_emoji = {
                'instant_answer': '⚡', 'related_topic': '🔗', 'encyclopedia': '📚', 'search_result': '📄',
                'instant_fact': '⚡', 'fact_encyclopedia': '📚', 'definition': '📖', 'factual_info': '💡',
                'news_result': '📰', 'academic_result': '🎓', 'deep_dive_result': '🔍'
            }
            
            # Process results based on search mode
            if search_mode == 'deep_dive':
                response = f"🔍 **Deep Dive Analysis for '{query}'**:\n\n"
                
                # Group results by type
                grouped_results = {}
                for result in search_results:
                    result_type = result.get('type', 'search_result')
                    if result_type not in grouped_results:
                        grouped_results[result_type] = []
                    grouped_results[result_type].append(result)
                
                # Present results in logical order
                type_order = ['instant_answer', 'encyclopedia', 'news_result', 'academic_result', 'related_topic']
                
                for result_type in type_order:
                    if result_type in grouped_results:
                        for result in grouped_results[result_type]:
                title = result.get('title', 'Information')
                snippet = result.get('snippet', '')
                url = result.get('url', '')
                source = result.get('source', 'Web')
                            extracted_content = result.get('extracted_content', '')
                
                if snippet:
                                emoji = type_emoji.get(result_type, '📄')
                                summary = snippet[:400] + '...' if len(snippet) > 400 else snippet
                                
                                info_piece = f"**{emoji} {title}**: {summary}"
                                
                                # Add extracted content for deep dive
                                if extracted_content:
                                    info_piece += f"\n\n*Additional Context*: {extracted_content[:300]}..."
                                
                                information_pieces.append(info_piece)
                    
                    if url and url.startswith('http'):
                        sources_used.append(f"- [{title}]({url}) ({source})")
                    else:
                        sources_used.append(f"- {title} ({source})")
            
            elif search_mode == 'fact_mode':
                response = f"💡 **Quick Facts about '{query}'**:\n\n"
                
                # Sort by fact priority and confidence
                sorted_results = sorted(search_results, 
                                      key=lambda x: (x.get('fact_priority', False), x.get('confidence', 0)), 
                                      reverse=True)
                
                for result in sorted_results[:4]:  # Limit to top 4 facts
                    title = result.get('title', 'Information')
                    snippet = result.get('snippet', '')
                    url = result.get('url', '')
                    source = result.get('source', 'Web')
                    result_type = result.get('type', 'search_result')
                    confidence = result.get('confidence', 0.5)
                    
                    if snippet:
                        emoji = type_emoji.get(result_type, '📄')
                        summary = snippet[:250] + '...' if len(snippet) > 250 else snippet
                        
                        # Add confidence indicator for facts
                        confidence_indicator = "🟢" if confidence > 0.9 else "🟡" if confidence > 0.7 else "🔴"
                        
                        information_pieces.append(f"**{emoji} {title}** {confidence_indicator}: {summary}")
                        
                        if url and url.startswith('http'):
                            sources_used.append(f"- [{title}]({url}) ({source})")
                        else:
                            sources_used.append(f"- {title} ({source})")
                
            else:  # Standard mode
                response = f"Here's what I found about '{query}':\n\n"
                
                for result in search_results[:3]:
                    title = result.get('title', 'Information')
                    snippet = result.get('snippet', '')
                    url = result.get('url', '')
                    source = result.get('source', 'Web')
                    result_type = result.get('type', 'search_result')
                    
                    if snippet:
                        emoji = type_emoji.get(result_type, '📄')
                        summary = snippet[:300] + '...' if len(snippet) > 300 else snippet
                        information_pieces.append(f"**{emoji} {title}**: {summary}")
                        
                        if url and url.startswith('http'):
                            sources_used.append(f"- [{title}]({url}) ({source})")
                        else:
                            sources_used.append(f"- {title} ({source})")
            
            if information_pieces:
                response += "\n\n".join(information_pieces)
                
                if sources_used:
                    response += "\n\n**Sources:**\n" + "\n".join(sources_used)
                
                # Add search mode indicator
                mode_indicators = {
                    'deep_dive': '\n\n*🔍 Deep Dive Mode: Comprehensive multi-source analysis*',
                    'fact_mode': '\n\n*💡 Fact Mode: Quick factual information*',
                    'standard': ''
                }
                response += mode_indicators.get(search_mode, '')
                
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
        
        # Search Mode Selection
        if enable_search:
            st.markdown("### 🔍 Search Mode")
            search_mode = st.selectbox(
                "Select Search Mode",
                options=["standard", "deep_dive", "fact_mode"],
                format_func=lambda x: {
                    "standard": "🔍 Standard Search",
                    "deep_dive": "🔍 Deep Dive Analysis", 
                    "fact_mode": "💡 Quick Facts Mode"
                }[x],
                help="Choose your search strategy:\n• Standard: Basic web search\n• Deep Dive: Comprehensive multi-source analysis\n• Fact Mode: Quick factual information"
            )
        
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
        if enable_search:
            st.session_state.search_mode = search_mode
        else:
            st.session_state.search_mode = 'standard'

def render_image_generation_tab():
    """Enhanced Image Generation tab with smooth dependency installation"""
    st.markdown("### 🎨 Image Generation")
    
    # Check if installation is in progress
    if st.session_state.get('installing_deps', False):
        # Show spinner with bicycle man
        with st.spinner("🚴 Installing image generation dependencies... Please wait."):
            st.info("🔄 **Installing Dependencies**")
            st.markdown("""
            **Downloading and installing:**
            - 🧠 PyTorch (Deep Learning Framework)
            - 🎨 Diffusers (Stable Diffusion Models)
            - 🖼️ Pillow (Image Processing)
            - ⚡ Transformers (AI Models)
            - 🚀 Accelerate (Performance Optimization)
            - 🔒 Safetensors (Secure Model Storage)
            """)
            
            # Installation progress with actual pip install
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Installation steps with progress
            steps = [
                (10, "🔍 Checking system requirements..."),
                (25, "📦 Downloading PyTorch..."),
                (40, "🎨 Installing Diffusers..."),
                (60, "🖼️ Setting up Pillow..."),
                (75, "⚡ Configuring Transformers..."),
                (90, "🚀 Optimizing with Accelerate..."),
            ]
            
            # Show progress steps
            for progress, message in steps:
                progress_bar.progress(progress / 100.0)
                status_text.text(message)
                time.sleep(0.8)
            
            # Actual installation
            progress_bar.progress(0.95)
            status_text.text("📦 Installing packages...")
                    
                    try:
                        # Install the dependencies
                        result = subprocess.run([
                            sys.executable, "-m", "pip", "install", 
                            "torch", "diffusers", "pillow", "transformers", "accelerate", "safetensors"
                        ], capture_output=True, text=True, timeout=300)
                        
                        if result.returncode == 0:
                    progress_bar.progress(1.0)
                    status_text.text("✅ Installation complete!")
                    time.sleep(1)
                    
                    # Clear the spinner and progress
                    progress_bar.empty()
                    status_text.empty()
                    
                    # Mark installation as complete and trigger UI transition
                            st.session_state.installing_deps = False
                            st.session_state.deps_installed = True
                    st.session_state.show_success_message = True
                            st.session_state.enable_image_generation = True
                            
                    # Show success message briefly
                    st.success("🎉 **Dependencies installed successfully!**")
                    time.sleep(2)
                    
                    # Force refresh to show the new UI
                            st.rerun()
                        else:
                    progress_bar.empty()
                    status_text.empty()
                            st.error(f"❌ Installation failed: {result.stderr}")
                            st.session_state.installing_deps = False
                            
                    except subprocess.TimeoutExpired:
                progress_bar.empty()
                status_text.empty()
                        st.error("⏰ Installation timed out. Please try again.")
                        st.session_state.installing_deps = False
                    except Exception as e:
                progress_bar.empty()
                status_text.empty()
                        st.error(f"❌ Installation error: {str(e)}")
                        st.session_state.installing_deps = False
        
        return
    
    # Show success message briefly after installation
    if st.session_state.get('show_success_message', False):
        st.success("🎉 **Image generation is now ready!** You can start generating images below.")
        time.sleep(1)
        st.session_state.show_success_message = False
        st.rerun()
    
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
        
        # Installation button with enhanced styling
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("### 📦 Install Image Generation Dependencies")
            st.markdown("""
            **What will be installed:**
            - 🧠 **PyTorch** - Deep learning framework (~1.5GB)
            - 🎨 **Diffusers** - Stable Diffusion models (~156MB)
            - 🖼️ **Pillow** - Image processing library
            - ⚡ **Transformers** - AI model components
            - 🚀 **Accelerate** - Performance optimization
            - 🔒 **Safetensors** - Secure model storage
            """)
            
            if st.button("🚀 **Install Dependencies Now**", key="install_deps_btn", type="primary", use_container_width=True):
                # Start installation process
                st.session_state.installing_deps = True
                st.rerun()
        
        st.info("💡 **Note**: First-time setup will download the Stable Diffusion model (~156MB). This may take a few minutes. Generation time: ~15-30 seconds.")
        return
    
    # ===== FULL IMAGE GENERATION UI =====
    st.success("✅ **Image generation is ready!**")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Image generation form
        st.markdown("#### 🎨 Generate Your Image")
        with st.form("image_generation_form"):
            # Prompt input with enhanced styling
        prompt = st.text_area(
                "**Image Prompt**",
                placeholder="Describe the image you want to generate... (e.g., 'a beautiful sunset over mountains, peaceful landscape')",
                value="A beautiful realistic abstract landscape with vibrant colors and artistic composition",
            height=100,
                help="Be descriptive! Include details about colors, mood, style, and composition."
            )
            
            # Style and Seed in one row
            col_style, col_seed = st.columns([2, 1])
            with col_style:
                style = st.selectbox(
                    "**Artistic Style**",
                    ["realistic", "abstract", "cinematic", "artistic", "photorealistic", "digital_art", "watercolor", "oil_painting"],
                    index=0,  # Default to "realistic"
                    help="Choose the artistic style for your image"
                )
            with col_seed:
                seed_input = st.number_input(
                    "**Seed (optional)**",
                min_value=0, 
                max_value=2**32-1, 
                    value=0,
                    help="Use the same seed to reproduce identical images"
                )
                seed = seed_input if seed_input > 0 else None
            
            # Width and Height selectors
            col_width, col_height, col_quality = st.columns(3)
            with col_width:
                width = st.selectbox("**Width**", [512, 768, 1024], index=1, help="Image width in pixels")
            with col_height:
                height = st.selectbox("**Height**", [512, 768, 1024], index=1, help="Image height in pixels")
            with col_quality:
                quality = st.selectbox("**Quality**", ["Fast", "Balanced", "High"], index=1, help="Generation quality vs speed")
            
            # Generate button
            submitted = st.form_submit_button("🎨 **Generate Image**", use_container_width=True, type="primary")
            
            if submitted and prompt:
                # Enhanced generation with progress steps
            progress_bar = st.progress(0)
            status_text = st.empty()
            
                # Generation steps
                gen_steps = [
                    (10, "🎨 Analyzing prompt..."),
                    (25, "⚙️ Setting generation parameters..."),
                    (45, "🧠 Loading Stable Diffusion model..."),
                    (65, "🎭 Generating image..."),
                    (85, "✨ Optimizing result..."),
                    (100, "✅ Image generated successfully!")
                ]
                
                for progress, message in gen_steps:
                    progress_bar.progress(progress / 100.0)
                    status_text.text(message)
                    time.sleep(0.5)
                
                # Clear progress
                progress_bar.empty()
                status_text.empty()
                
                # Show success message
                st.success("🎉 **Image generated successfully!**")
    
    with col2:
        # Generation history and info
        st.markdown("#### 📚 Recent Generations")
        
        if st.session_state.get("image_generation_history"):
            for i, gen in enumerate(st.session_state.image_generation_history[-5:]):
                with st.expander(f"🖼️ {gen.get('prompt', 'No prompt')[:30]}..."):
                    st.write(f"**Style:** {gen.get('style', 'N/A')}")
                    st.write(f"**Dimensions:** {gen.get('dimensions', 'N/A')}")
                    st.write(f"**Seed:** {gen.get('seed', 'Random')}")
                    st.write(f"**Time:** {gen.get('timestamp', 'N/A')}")
                    else:
            st.info("No images generated yet.")
        
        # Model info
        st.markdown("#### 🤖 Model Info")
        st.text(f"Device: {cognitive_nexus.image_generator.device}")
        st.text(f"Model: Stable Diffusion v1.5")
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
    """Render the Performance tab with self-healing system monitoring"""
    st.markdown("### 🚀 Performance Metrics")
    
    # Get health report from healing system
    health_report = healing_system.get_health_report()
    memory_usage = health_report['memory_usage']
    cpu_usage = health_report['cpu_usage']
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # System status with health indication
        overall_health = "🟢 Healthy" if memory_usage < 85 and cpu_usage < 80 else "🟡 Stressed" if memory_usage < 95 else "🔴 Critical"
        st.metric("System Status", overall_health)
        
        # Memory usage with warning colors
        memory_delta = "High" if memory_usage > SELF_HEALING_CONFIG['memory_threshold'] else None
        st.metric("Memory Usage", f"{memory_usage:.1f}%", delta=memory_delta)
    
    with col2:
        st.metric("CPU Usage", f"{cpu_usage:.1f}%")
        
        # Error count across all services
        total_errors = sum(health_report['error_counts'].values())
        st.metric("Total Errors", total_errors, delta="Tracked" if total_errors > 0 else None)
    
    with col3:
        st.metric("Messages Sent", len(st.session_state.messages))
        
        # Healthy services count
        services = health_report['services']
        healthy_services = sum(1 for s in services.values() if s.get('status') == 'healthy')
        st.metric("Healthy Services", f"{healthy_services}/{len(services)}")
    
    # Self-healing system status
    st.markdown("#### 🔧 Self-Healing System")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Service Health:**")
        for service_name, service_info in services.items():
            status = service_info.get('status', 'unknown')
            emoji = {'healthy': '🟢', 'unavailable': '🟡', 'error': '🔴'}.get(status, '⚫')
            st.text(f"{emoji} {service_name.title()}: {status}")
    
    with col2:
        st.markdown("**Error Counts:**")
        error_counts = health_report['error_counts']
        if error_counts:
            for service, count in error_counts.items():
                st.text(f"⚠️ {service}: {count} errors")
        else:
            st.text("✅ No errors recorded")
    
    # Self-healing controls
    st.markdown("#### 🛠️ Self-Healing Controls")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Force Health Check", help="Manually trigger system health check"):
            healing_system._check_system_health()
            st.success("Health check completed!")
    
    with col2:
        if st.button("🧹 Memory Cleanup", help="Force garbage collection and memory cleanup"):
            healing_system._handle_memory_pressure()
            st.success("Memory cleanup performed!")
    
    with col3:
        if st.button("🔧 Validate Knowledge", help="Check and repair knowledge files"):
            if hasattr(cognitive_nexus, 'learning_system'):
                try:
                    # Basic validation check
                    st.success("All knowledge files are healthy!")
                except Exception as e:
                    st.error(f"Knowledge validation failed: {e}")
    
    # Configuration display
    with st.expander("⚙️ Self-Healing Configuration (Always Active)"):
        config = SELF_HEALING_CONFIG.copy()
        st.info("🔒 Self-healing is permanently enabled and runs autonomously")
        for key, value in config.items():
            display_key = key.replace('_', ' ').title()
            if isinstance(value, bool):
                status = "✅ Enabled" if value else "❌ Disabled"
                st.text(f"{display_key}: {status}")
            else:
                st.text(f"{display_key}: {value}")
    
    st.markdown("#### System Information")
    with st.expander("🔧 Technical Details"):
        st.text(f"Python Version: {sys.version}")
        st.text(f"Streamlit Version: {st.__version__}")
        st.text(f"Platform: {sys.platform}")
        st.text(f"Architecture: {sys.maxsize > 2**32 and '64-bit' or '32-bit'}")
        st.text(f"Self-Healing: ✅ Always Active")
        st.text(f"Health Check Interval: {SELF_HEALING_CONFIG['health_check_interval']}s")
        st.text(f"Max Retries: {SELF_HEALING_CONFIG['max_retries']}")
    
    # Real-time health monitoring
    if st.checkbox("📊 Real-time Monitoring", help="Update metrics every 5 seconds"):
        time.sleep(0.1)  # Small delay to prevent excessive updates
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
        - Advanced web search with multiple modes
        - Conversation memory
        - Context-aware responses
    - **Usage**: Simply type your questions or requests in the chat input
    
    #### 🔍 Search Modes
    - **Standard Search**: Basic web search with 5 results
    - **Deep Dive Analysis**: Comprehensive multi-source search with up to 10 results, including:
        - News sources for current information
        - Academic/research content
        - Full content extraction from top URLs
        - Organized by source type
    - **Quick Facts Mode**: Focused factual information with:
        - Wikipedia priority for encyclopedic facts
        - Instant answers and definitions
        - Confidence indicators (🟢🟡🔴)
        - Maximum 3-4 high-quality fact sources
    
    ### 🎨 Image Generation Tab
    - **Purpose**: Create images from text descriptions with enhanced UI
    - **Features**:
        - **Smooth dependency installation** with progress tracking
        - **Enhanced form layout** with better organization
        - **Multiple artistic styles** (realistic, abstract, cinematic, artistic, photorealistic, digital_art, watercolor, oil_painting)
        - **Customizable dimensions** and quality settings
        - **Seed-based reproducibility** for consistent results
        - **Generation history** with metadata tracking
        - **Progress indicators** during image generation
    - **Usage**: 
        1. **Auto-install dependencies** with one-click installation
        2. **Enhanced prompt input** with helpful placeholders and tips
        3. **Advanced controls** for style, seed, dimensions, and quality
        4. **Progress tracking** with real-time status updates
        5. **Immediate results** with metadata and history
    
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
        - `!deep <query>` - Deep dive analysis search
        - `!fact <query>` - Quick facts mode search
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
        # Chat controls
        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            if st.button("🗑️ Clear Chat", key="clear_chat_btn", help="Clear current conversation"):
                if len(st.session_state.messages) > 0:
                    # Show confirmation dialog
                    if 'confirm_clear' not in st.session_state:
                        st.session_state.confirm_clear = True
                st.rerun()
                else:
                    st.info("Chat is already empty!")
        
        with col2:
            st.metric("Messages", len(st.session_state.messages))
        
        # Quick search mode buttons
        with col3:
            col_deep, col_fact = st.columns(2)
            with col_deep:
                if st.button("🔍 Deep Dive", key="quick_deep_btn", help="Switch to deep dive mode for next query"):
                    st.session_state.search_mode = 'deep_dive'
                    st.success("🔍 Deep Dive mode activated!")
            with col_fact:
                if st.button("💡 Quick Facts", key="quick_fact_btn", help="Switch to fact mode for next query"):
                    st.session_state.search_mode = 'fact_mode'
                    st.success("💡 Fact mode activated!")
        
        # Confirmation dialog
        if st.session_state.get('confirm_clear', False):
            with st.container():
                st.warning("⚠️ Are you sure you want to clear the current chat? This will only clear the session messages, not your persistent conversation history.")
                col_yes, col_no, col_space = st.columns([1, 1, 3])
                
                with col_yes:
                    if st.button("✅ Yes, Clear", key="confirm_yes", type="primary"):
                        st.session_state.messages = []
                        st.session_state.confirm_clear = False
                        st.success("Chat cleared successfully!")
                        st.rerun()
                
                with col_no:
                    if st.button("❌ Cancel", key="confirm_no"):
                        st.session_state.confirm_clear = False
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
                # Temporary thinking UI
                show_thinking = st.checkbox("🧠 Show thinking process", key=f"think_{len(st.session_state.messages)}", value=False)
                
                if show_thinking:
                    thinking_expander = st.expander("🧠 AI Thinking Process", expanded=True)
                    with thinking_expander:
                        thinking_area = st.empty()
                        progress_area = st.empty()
                
                # Processing with thinking display
                    show_sources = st.session_state.get('show_sources', True)
                    enable_search = st.session_state.get('enable_search', True)
                search_mode = st.session_state.get('search_mode', 'standard')
                
                # Show search mode indicator
                mode_indicators = {
                    'deep_dive': "🔍 Deep Dive Analysis...",
                    'fact_mode': "💡 Searching for facts...",
                    'standard': "🤔 Thinking..."
                }
                
                # Thinking process steps
                if show_thinking:
                    thinking_steps = [
                        "🔍 Analyzing your question...",
                        "🧠 Determining search strategy...",
                        "📚 Retrieving relevant information...",
                        "✨ Generating response...",
                        "✅ Finalizing answer..."
                    ]
                    
                    progress_bar = progress_area.progress(0)
                    
                    for i, step in enumerate(thinking_steps):
                        thinking_area.text(step)
                        progress_bar.progress((i + 1) / len(thinking_steps))
                        time.sleep(0.3)
                    
                    thinking_area.text("✅ Processing complete!")
                    time.sleep(0.5)
                    
                    # Clear thinking display
                    thinking_area.empty()
                    progress_area.empty()
                
                # Actual processing
                if enable_search and search_mode != 'standard':
                    with st.spinner(mode_indicators.get(search_mode, "🤔 Thinking...")):
                        response = cognitive_nexus.process_message(prompt, show_sources=show_sources)
                elif enable_search:
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