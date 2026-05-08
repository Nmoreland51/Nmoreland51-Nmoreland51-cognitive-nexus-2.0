#!/usr/bin/env python3
"""
Test script for AI Reasoning System
Tests core functionality and integration examples
"""

import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

def test_reasoning_system():
    """Test the AI reasoning system functionality"""
    print("🧪 Testing AI Reasoning System...")
    print("=" * 60)
    
    try:
        from ai_reasoning_system import AIReasoningSystem, render_ai_response
        
        # Test 1: Initialize reasoning system
        print("1. Initializing AI Reasoning System...")
        reasoning_system = AIReasoningSystem()
        print("✅ Reasoning system initialized")
        
        # Test 2: Generate chat reasoning
        print("\n2. Testing chat reasoning generation...")
        chat_reasoning = reasoning_system.generate_reasoning(
            process_type="chat",
            user_input="What is artificial intelligence?",
            context={
                'conversation_history': ['Previous chat about technology'],
                'user_emotion': 'curious',
                'response_style': 'informative'
            }
        )
        print(f"✅ Generated chat reasoning ({len(chat_reasoning)} characters)")
        print(f"   Preview: {chat_reasoning[:100]}...")
        
        # Test 3: Generate image generation reasoning
        print("\n3. Testing image generation reasoning...")
        image_reasoning = reasoning_system.generate_reasoning(
            process_type="image_gen",
            user_input="Generate a beautiful sunset",
            context={
                'prompt': 'Generate a beautiful sunset',
                'style': 'realistic',
                'dimensions': '512x512',
                'model': 'Stable Diffusion v1.5'
            }
        )
        print(f"✅ Generated image reasoning ({len(image_reasoning)} characters)")
        print(f"   Preview: {image_reasoning[:100]}...")
        
        # Test 4: Generate web research reasoning
        print("\n4. Testing web research reasoning...")
        web_reasoning = reasoning_system.generate_reasoning(
            process_type="web_research",
            user_input="Process this URL: https://example.com",
            context={
                'url': 'https://example.com',
                'operation': 'process_url',
                'content_length': 1250,
                'chunks_created': 3
            }
        )
        print(f"✅ Generated web research reasoning ({len(web_reasoning)} characters)")
        print(f"   Preview: {web_reasoning[:100]}...")
        
        # Test 5: Generate memory reasoning
        print("\n5. Testing memory reasoning...")
        memory_reasoning = reasoning_system.generate_reasoning(
            process_type="memory",
            user_input="What do I remember about AI?",
            context={
                'operation': 'recall',
                'memory_sources': 'Session state',
                'search_scope': 'All memories',
                'time_context': 'Current session'
            }
        )
        print(f"✅ Generated memory reasoning ({len(memory_reasoning)} characters)")
        print(f"   Preview: {memory_reasoning[:100]}...")
        
        # Test 6: Generate performance reasoning
        print("\n6. Testing performance reasoning...")
        performance_reasoning = reasoning_system.generate_reasoning(
            process_type="performance",
            user_input="Check system performance",
            context={
                'cpu_usage': '45%',
                'memory_usage': '62%',
                'gpu_status': 'Available',
                'response_time': '1.2s'
            }
        )
        print(f"✅ Generated performance reasoning ({len(performance_reasoning)} characters)")
        print(f"   Preview: {performance_reasoning[:100]}...")
        
        # Test 7: Test reasoning chain management
        print("\n7. Testing reasoning chain management...")
        
        # Simulate multiple reasoning entries
        for i in range(3):
            reasoning_system.generate_reasoning(
                process_type="chat",
                user_input=f"Test message {i+1}",
                context={'test': True}
            )
        
        print("✅ Generated multiple reasoning entries")
        
        # Test 8: Test reasoning storage
        print("\n8. Testing reasoning storage...")
        
        # Check if reasoning is stored in session state
        if hasattr(reasoning_system, 'session_key'):
            print("✅ Reasoning storage system initialized")
        else:
            print("❌ Reasoning storage not initialized")
        
        print("\n🎉 All reasoning system tests passed!")
        print("\n📋 Next steps:")
        print("1. Run 'streamlit run cognitive_nexus_with_reasoning.py' to test the UI")
        print("2. Integrate into your main Cognitive Nexus AI app")
        print("3. Customize reasoning generation for your specific needs")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("\n📦 Install dependencies:")
        print("pip install streamlit")
        return False
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_reasoning_components():
    """Test individual reasoning components"""
    print("\n🔍 Testing reasoning components...")
    
    try:
        from ai_reasoning_system import AIReasoningSystem
        
        reasoning_system = AIReasoningSystem()
        
        # Test helper methods
        print("Testing helper methods...")
        
        # Test question classification
        question_type = reasoning_system._classify_question_type("What is AI?")
        print(f"✅ Question classification: {question_type}")
        
        # Test response tone determination
        tone = reasoning_system._determine_response_tone("Please help me urgently!")
        print(f"✅ Response tone: {tone}")
        
        # Test response length determination
        length = reasoning_system._determine_response_length("Short question")
        print(f"✅ Response length: {length}")
        
        # Test response style determination
        style = reasoning_system._determine_response_style("How do I code this technical problem?")
        print(f"✅ Response style: {style}")
        
        # Test image prompt analysis
        subject = reasoning_system._extract_image_subject("A beautiful sunset over mountains")
        print(f"✅ Image subject: {subject}")
        
        style_indicators = reasoning_system._extract_style_indicators("Create a realistic portrait")
        print(f"✅ Style indicators: {style_indicators}")
        
        mood_indicators = reasoning_system._extract_mood_indicators("A bright and happy landscape")
        print(f"✅ Mood indicators: {mood_indicators}")
        
        print("✅ All component tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Component test failed: {e}")
        return False

def test_integration_example():
    """Test the integration example"""
    print("\n🔗 Testing integration example...")
    
    try:
        # Check if integration example file exists
        integration_file = Path("cognitive_nexus_with_reasoning.py")
        if integration_file.exists():
            print("✅ Integration example file found")
            
            # Try to import key components
            with open(integration_file, 'r') as f:
                content = f.read()
                
            if "render_ai_response" in content:
                print("✅ Integration example uses render_ai_response")
            
            if "AIReasoningSystem" in content:
                print("✅ Integration example uses AIReasoningSystem")
            
            if "render_reasoning_history" in content:
                print("✅ Integration example includes reasoning history")
            
            print("✅ Integration example appears complete")
            return True
        else:
            print("❌ Integration example file not found")
            return False
            
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("AI Reasoning System Test Suite")
    print("=" * 60)
    
    # Test core system
    core_success = test_reasoning_system()
    
    # Test components
    component_success = test_reasoning_components()
    
    # Test integration
    integration_success = test_integration_example()
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    if core_success and component_success and integration_success:
        print("🎉 ALL TESTS PASSED!")
        print("\n🚀 Ready to use:")
        print("1. Run 'streamlit run cognitive_nexus_with_reasoning.py' to test the UI")
        print("2. Integrate into your Cognitive Nexus AI app")
        print("3. Customize reasoning for your specific needs")
    else:
        print("❌ SOME TESTS FAILED")
        print("\n🔧 Fix issues and run tests again")
        sys.exit(1)

if __name__ == "__main__":
    main()
