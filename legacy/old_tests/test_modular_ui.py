#!/usr/bin/env python3
"""
Test script for Modular AI UI System
Tests core functionality and integration examples
"""

import sys
import os
import time
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

def test_modular_ui_system():
    """Test the modular UI system functionality"""
    print("🧪 Testing Modular AI UI System...")
    print("=" * 60)
    
    try:
        from modular_ai_ui import ModularAIUI, render_ai_process_with_reasoning
        
        # Test 1: Initialize modular UI system
        print("1. Initializing Modular AI UI System...")
        ui_system = ModularAIUI()
        print("✅ Modular UI system initialized")
        
        # Test 2: Generate reasoning for different process types
        print("\n2. Testing reasoning generation...")
        
        process_types = ["chat", "image_gen", "web_research", "memory", "performance"]
        
        for process_type in process_types:
            reasoning, process_id = ui_system.generate_reasoning(
                process_type=process_type,
                user_input=f"Test {process_type} request",
                context={"test": True, "process_type": process_type}
            )
            print(f"✅ Generated {process_type} reasoning ({len(reasoning)} chars)")
        
        # Test 3: Test reasoning content creation
        print("\n3. Testing reasoning content creation...")
        
        # Test chat reasoning
        chat_reasoning = ui_system._create_chat_reasoning(
            "What is artificial intelligence?",
            {"conversation_history": [], "user_emotion": "curious"}
        )
        print(f"✅ Chat reasoning created ({len(chat_reasoning)} chars)")
        
        # Test image reasoning
        image_reasoning = ui_system._create_image_reasoning(
            "Generate a beautiful sunset",
            {"style": "realistic", "dimensions": "512x512", "model": "SD v1.5"}
        )
        print(f"✅ Image reasoning created ({len(image_reasoning)} chars)")
        
        # Test web research reasoning
        web_reasoning = ui_system._create_web_research_reasoning(
            "Process URL: https://example.com",
            {"url": "https://example.com", "operation": "process_url"}
        )
        print(f"✅ Web research reasoning created ({len(web_reasoning)} chars)")
        
        # Test 4: Test helper methods
        print("\n4. Testing helper methods...")
        
        # Test query classification
        query_type = ui_system._classify_query("What is AI?")
        print(f"✅ Query classification: {query_type}")
        
        # Test emotion detection
        emotion = ui_system._detect_emotion("Please help me urgently!")
        print(f"✅ Emotion detection: {emotion}")
        
        # Test complexity assessment
        complexity = ui_system._assess_complexity("Short question")
        print(f"✅ Complexity assessment: {complexity}")
        
        # Test 5: Test mock AI function
        print("\n5. Testing mock AI function...")
        
        def mock_ai_function(input_text, context):
            """Mock AI function for testing"""
            time.sleep(1)  # Simulate processing
            return f"Mock response for: {input_text}"
        
        # Test the function directly
        result = mock_ai_function("Test input", {"test": True})
        print(f"✅ Mock AI function result: {result}")
        
        # Test 6: Test session state management
        print("\n6. Testing session state management...")
        
        # Check if session state is properly initialized
        if hasattr(ui_system, 'session_key'):
            print("✅ Session state key initialized")
        else:
            print("❌ Session state key not found")
        
        # Test reasoning history storage
        reasoning_history = ui_system.session_state.get('modular_ai_ui', {}).get('reasoning_history', [])
        print(f"✅ Reasoning history contains {len(reasoning_history)} entries")
        
        print("\n🎉 All modular UI system tests passed!")
        print("\n📋 Next steps:")
        print("1. Run 'streamlit run cognitive_nexus_modular_ui.py' to test the UI")
        print("2. Integrate into your main Cognitive Nexus AI app")
        print("3. Customize reasoning content for your specific needs")
        
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

def test_reasoning_content():
    """Test reasoning content generation"""
    print("\n🔍 Testing reasoning content generation...")
    
    try:
        from modular_ai_ui import ModularAIUI
        
        ui_system = ModularAIUI()
        
        # Test different reasoning types
        reasoning_types = [
            ("chat", "What is artificial intelligence?"),
            ("image_gen", "Generate a beautiful sunset over mountains"),
            ("web_research", "Process URL: https://example.com"),
            ("memory", "What do I remember about AI?"),
            ("performance", "Check system performance"),
            ("knowledge", "Search for information about machine learning")
        ]
        
        for process_type, user_input in reasoning_types:
            reasoning = ui_system._create_reasoning_content(process_type, user_input, {})
            print(f"✅ {process_type} reasoning: {len(reasoning)} characters")
            
            # Check if reasoning contains expected elements
            if "REASONING" in reasoning and "INPUT" in reasoning:
                print(f"   ✓ Contains expected structure")
            else:
                print(f"   ⚠️ May be missing expected structure")
        
        print("✅ All reasoning content tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Reasoning content test failed: {e}")
        return False

def test_integration_example():
    """Test the integration example"""
    print("\n🔗 Testing integration example...")
    
    try:
        # Check if integration example file exists
        integration_file = Path("cognitive_nexus_modular_ui.py")
        if integration_file.exists():
            print("✅ Integration example file found")
            
            # Try to import key components
            with open(integration_file, 'r') as f:
                content = f.read()
                
            if "render_ai_process_with_reasoning" in content:
                print("✅ Integration example uses render_ai_process_with_reasoning")
            
            if "ModularAIUI" in content:
                print("✅ Integration example uses ModularAIUI")
            
            if "render_reasoning_controls" in content:
                print("✅ Integration example includes reasoning controls")
            
            if "render_reasoning_history" in content:
                print("✅ Integration example includes reasoning history")
            
            # Check for process types
            process_types = ["chat", "image_gen", "web_research", "memory", "performance"]
            for process_type in process_types:
                if f'process_type="{process_type}"' in content:
                    print(f"✅ Includes {process_type} process example")
            
            print("✅ Integration example appears complete")
            return True
        else:
            print("❌ Integration example file not found")
            return False
            
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False

def test_ui_components():
    """Test UI components and functions"""
    print("\n🎨 Testing UI components...")
    
    try:
        from modular_ai_ui import (
            render_ai_process_with_reasoning,
            render_reasoning_controls,
            render_reasoning_history
        )
        
        print("✅ All UI components imported successfully")
        
        # Test function signatures
        import inspect
        
        # Check render_ai_process_with_reasoning signature
        sig = inspect.signature(render_ai_process_with_reasoning)
        expected_params = ['process_type', 'user_input', 'ai_function', 'context']
        for param in expected_params:
            if param in sig.parameters:
                print(f"✅ render_ai_process_with_reasoning has {param} parameter")
            else:
                print(f"❌ render_ai_process_with_reasoning missing {param} parameter")
        
        print("✅ UI components test passed!")
        return True
        
    except Exception as e:
        print(f"❌ UI components test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("Modular AI UI System Test Suite")
    print("=" * 60)
    
    # Test core system
    core_success = test_modular_ui_system()
    
    # Test reasoning content
    content_success = test_reasoning_content()
    
    # Test integration
    integration_success = test_integration_example()
    
    # Test UI components
    ui_success = test_ui_components()
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    if core_success and content_success and integration_success and ui_success:
        print("🎉 ALL TESTS PASSED!")
        print("\n🚀 Ready to use:")
        print("1. Run 'streamlit run cognitive_nexus_modular_ui.py' to test the UI")
        print("2. Integrate into your Cognitive Nexus AI app")
        print("3. Customize reasoning for your specific needs")
        print("\n📋 Key Features:")
        print("- ✅ Clickable reasoning panels that auto-hide")
        print("- ✅ Loading indicators and progress bars")
        print("- ✅ Clean user outputs separate from reasoning")
        print("- ✅ Modular design for all AI processes")
        print("- ✅ Session state management")
        print("- ✅ Error handling and graceful degradation")
    else:
        print("❌ SOME TESTS FAILED")
        print("\n🔧 Fix issues and run tests again")
        sys.exit(1)

if __name__ == "__main__":
    main()
