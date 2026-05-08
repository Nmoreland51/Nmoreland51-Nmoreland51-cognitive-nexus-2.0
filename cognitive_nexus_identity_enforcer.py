"""
Cognitive Nexus AI - Identity Enforcement Module
================================================
A dedicated module that ensures the AI always identifies as Cognitive Nexus AI
and overrides any external AI responses that claim to be other systems.

Author: Heisenberg's Cognitive Nexus AI System
Version: 1.0
Date: September 20, 2025
"""

import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class CognitiveNexusIdentityEnforcer:
    """
    Dedicated identity enforcement system that ensures the AI always identifies
    as Cognitive Nexus AI and never as Qwen, ChatGPT, or any other system.
    """
    
    def __init__(self):
        self.identity = "Cognitive Nexus AI"
        self.wrong_identities = [
            "Qwen", "qwen", "QWEN",
            "ChatGPT", "chatgpt", "GPT",
            "Claude", "claude", "Anthropic",
            "Bard", "bard", "Google",
            "Copilot", "copilot", "Microsoft",
            "Assistant", "assistant", "AI assistant"
        ]
        
        # Strong identity responses
        self.identity_responses = {
            "who_are_you": "I am Cognitive Nexus AI, your privacy-focused AI assistant developed for local, secure processing.",
            "what_is_your_name": "My name is Cognitive Nexus AI. I am NOT Qwen, ChatGPT, or any other AI system.",
            "what_are_you": "I am Cognitive Nexus AI, a privacy-focused AI assistant that combines local processing with web search capabilities.",
            "introduction": "Hello! I'm Cognitive Nexus AI, your dedicated AI assistant. How can I help you today?",
            "capabilities": "As Cognitive Nexus AI, I can help with information search, analysis, conversation, image generation, and more while keeping your data completely private."
        }
    
    def enforce_identity(self, response: str, user_input: str = "") -> str:
        """
        Enforce Cognitive Nexus AI identity on any response.
        Overrides any external AI identity claims.
        """
        if not response:
            return self._get_default_response(user_input)
        
        # Check if response contains wrong identity
        if self._contains_wrong_identity(response):
            logger.warning(f"Detected wrong identity in response, enforcing Cognitive Nexus AI identity")
            return self._replace_wrong_identity(response, user_input)
        
        # Check if user is asking about identity
        if self._is_identity_query(user_input):
            return self._get_identity_response(user_input)
        
        # Ensure response starts with proper identity if needed
        if self._needs_identity_assertion(response, user_input):
            return self._add_identity_assertion(response)
        
        return response
    
    def _contains_wrong_identity(self, response: str) -> bool:
        """Check if response contains any wrong AI identity."""
        response_lower = response.lower()
        return any(wrong_id.lower() in response_lower for wrong_id in self.wrong_identities)
    
    def _is_identity_query(self, user_input: str) -> bool:
        """Check if user is asking about AI identity."""
        identity_patterns = [
            "who are you", "what are you", "what's your name", "what is your name",
            "who am i talking to", "what ai are you", "what model are you",
            "introduce yourself", "tell me about yourself", "what can you do"
        ]
        
        user_lower = user_input.lower()
        return any(pattern in user_lower for pattern in identity_patterns)
    
    def _needs_identity_assertion(self, response: str, user_input: str) -> bool:
        """Check if response needs identity assertion."""
        # If it's a greeting or first interaction
        greeting_patterns = ["hello", "hi", "hey", "good morning", "good afternoon"]
        if any(pattern in user_input.lower() for pattern in greeting_patterns):
            return True
        
        # If response doesn't mention Cognitive Nexus AI
        return "cognitive nexus" not in response.lower()
    
    def _replace_wrong_identity(self, response: str, user_input: str) -> str:
        """Replace wrong identity with Cognitive Nexus AI identity."""
        # Remove any wrong identity mentions
        cleaned_response = response
        for wrong_id in self.wrong_identities:
            # Replace with Cognitive Nexus AI
            cleaned_response = re.sub(
                rf'\b{wrong_id}\b', 
                'Cognitive Nexus AI', 
                cleaned_response, 
                flags=re.IGNORECASE
            )
        
        # If it's an identity query, provide proper response
        if self._is_identity_query(user_input):
            return self._get_identity_response(user_input)
        
        # Add identity assertion if needed
        if not self._needs_identity_assertion(cleaned_response, user_input):
            return cleaned_response
        
        return self._add_identity_assertion(cleaned_response)
    
    def _get_identity_response(self, user_input: str) -> str:
        """Get proper identity response based on user query."""
        user_lower = user_input.lower()
        
        if "name" in user_lower:
            return self.identity_responses["what_is_your_name"]
        elif "who" in user_lower:
            return self.identity_responses["who_are_you"]
        elif "what are you" in user_lower:
            return self.identity_responses["what_are_you"]
        elif "what can you do" in user_lower or "capabilities" in user_lower:
            return self.identity_responses["capabilities"]
        else:
            return self.identity_responses["introduction"]
    
    def _add_identity_assertion(self, response: str) -> str:
        """Add identity assertion to response."""
        if "cognitive nexus" in response.lower():
            return response
        
        return f"I'm Cognitive Nexus AI. {response}"
    
    def _get_default_response(self, user_input: str) -> str:
        """Get default response when no response is available."""
        if self._is_identity_query(user_input):
            return self.identity_responses["who_are_you"]
        
        return "I'm Cognitive Nexus AI, your privacy-focused AI assistant. How can I help you today?"
    
    def get_system_prompt(self) -> str:
        """Get the identity-enforced system prompt."""
        return f"""You are Cognitive Nexus AI, a privacy-focused AI assistant developed for local, secure processing.

CRITICAL IDENTITY RULES:
1. You are ONLY Cognitive Nexus AI - never identify as Qwen, ChatGPT, Claude, or any other AI
2. If asked "who are you" or "what's your name", respond: "I am Cognitive Nexus AI"
3. Never mention Tongyi Lab, Alibaba, OpenAI, Anthropic, or any other company
4. Always maintain your identity as Cognitive Nexus AI
5. If you detect any response claiming to be another AI, immediately correct it

You are helpful, harmless, and honest. You provide accurate responses while maintaining your identity as Cognitive Nexus AI."""

    def validate_response(self, response: str) -> Dict[str, Any]:
        """Validate that response maintains correct identity."""
        issues = []
        
        # Check for wrong identities
        for wrong_id in self.wrong_identities:
            if wrong_id.lower() in response.lower():
                issues.append(f"Contains wrong identity: {wrong_id}")
        
        # Check if Cognitive Nexus AI is mentioned
        if "cognitive nexus" not in response.lower() and len(response) > 50:
            issues.append("Missing Cognitive Nexus AI identity assertion")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "corrected_response": self.enforce_identity(response) if issues else response
        }

# Global instance for easy import
identity_enforcer = CognitiveNexusIdentityEnforcer()

def enforce_cognitive_nexus_identity(response: str, user_input: str = "") -> str:
    """
    Convenience function to enforce Cognitive Nexus AI identity.
    Use this to wrap any AI response to ensure correct identity.
    """
    return identity_enforcer.enforce_identity(response, user_input)

def get_identity_system_prompt() -> str:
    """Get the identity-enforced system prompt."""
    return identity_enforcer.get_system_prompt()

def validate_ai_response(response: str) -> Dict[str, Any]:
    """Validate AI response maintains correct identity."""
    return identity_enforcer.validate_response(response)
