#!/usr/bin/env python3
"""
Test script for Web Research Module
Tests the core functionality without Streamlit UI
"""

import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

from web_research_module import WebResearchModule

def test_web_research_module():
    """Test the web research module functionality"""
    print("🧪 Testing Web Research Module...")
    print("=" * 50)
    
    # Initialize module
    print("1. Initializing Web Research Module...")
    web_research = WebResearchModule("test_knowledge_base")
    print("✅ Module initialized")
    
    # Test URL processing
    print("\n2. Testing URL content extraction...")
    test_url = "https://en.wikipedia.org/wiki/Artificial_intelligence"
    
    try:
        content_data = web_research.extract_content_from_url(test_url)
        if content_data['status'] == 'success':
            print(f"✅ Successfully extracted content from {test_url}")
            print(f"   Title: {content_data['title']}")
            print(f"   Word count: {content_data['word_count']:,}")
        else:
            print(f"❌ Failed to extract content: {content_data.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"❌ Error during content extraction: {e}")
    
    # Test text chunking
    print("\n3. Testing text chunking...")
    sample_text = "This is a sample text. " * 200  # Create long text
    chunks = web_research.chunk_text(sample_text, target_size=50, overlap=10)
    print(f"✅ Created {len(chunks)} chunks from {len(sample_text.split())} words")
    print(f"   Average chunk size: {sum(chunk['word_count'] for chunk in chunks) // len(chunks)} words")
    
    # Test embedding generation
    print("\n4. Testing embedding generation...")
    test_text = "This is a test sentence for embedding generation."
    embedding = web_research.generate_embedding(test_text)
    print(f"✅ Generated embedding with {len(embedding)} dimensions")
    print(f"   Sample values: {embedding[:5]}")
    
    # Test semantic search
    print("\n5. Testing semantic search...")
    query = "What is artificial intelligence?"
    results = web_research.semantic_search(query, top_k=3)
    print(f"✅ Semantic search returned {len(results)} results")
    if results:
        print(f"   Top similarity score: {results[0]['similarity']:.3f}")
    
    # Test response generation
    print("\n6. Testing response generation...")
    response = web_research.generate_response(query, results)
    print(f"✅ Generated response ({len(response)} characters)")
    print(f"   Preview: {response[:100]}...")
    
    # Test summary
    print("\n7. Testing summary generation...")
    summary = web_research.get_processing_summary()
    print(f"✅ Summary generated:")
    print(f"   URLs: {summary['total_urls']}")
    print(f"   Chunks: {summary['total_chunks']}")
    print(f"   Words: {summary['total_words']:,}")
    
    print("\n🎉 All tests completed!")
    print("\n📋 Next steps:")
    print("1. Run 'streamlit run web_research_module.py' to test the UI")
    print("2. Integrate into your main Cognitive Nexus AI app")
    print("3. Replace placeholder implementations with real models")
    
    return True

if __name__ == "__main__":
    try:
        test_web_research_module()
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        sys.exit(1)