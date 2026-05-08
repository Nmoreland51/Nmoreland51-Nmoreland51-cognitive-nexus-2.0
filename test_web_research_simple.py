#!/usr/bin/env python3
"""
Simple test script for the Enhanced Web Research functionality
Tests only the functions that don't require network access
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import only the validation function
from cognitive_nexus_advanced import validate_url

def test_url_validation():
    """Test URL validation functionality"""
    print("Testing URL validation...")
    
    test_cases = [
        ("example.com", True, "https://example.com"),
        ("https://example.com", True, "https://example.com"),
        ("http://example.com", True, "http://example.com"),
        ("invalid-url", False, "Invalid domain name"),
        ("https://httpbin.org/html", True, "https://httpbin.org/html"),
        ("not-a-url", False, "Invalid domain name"),
        ("", False, "Invalid URL format"),
        ("ftp://example.com", True, "ftp://example.com"),
        ("https://subdomain.example.com/path", True, "https://subdomain.example.com/path"),
    ]
    
    passed = 0
    total = len(test_cases)
    
    for url, expected_valid, expected_result in test_cases:
        is_valid, result = validate_url(url)
        
        if is_valid == expected_valid:
            if expected_valid and result == expected_result:
                print(f"  ✅ {url} -> Valid: {is_valid}, Result: {result}")
                passed += 1
            elif not expected_valid and expected_result in result:
                print(f"  ✅ {url} -> Valid: {is_valid}, Result: {result}")
                passed += 1
            else:
                print(f"  ❌ {url} -> Expected: {expected_result}, Got: {result}")
        else:
            print(f"  ❌ {url} -> Expected valid: {expected_valid}, Got: {is_valid}")
    
    print(f"\nURL Validation Test Results: {passed}/{total} passed")
    return passed == total

def test_imports():
    """Test that all required modules can be imported"""
    print("\nTesting imports...")
    
    try:
        import requests
        print("  ✅ requests imported successfully")
    except ImportError as e:
        print(f"  ❌ requests import failed: {e}")
        return False
    
    try:
        from bs4 import BeautifulSoup
        print("  ✅ BeautifulSoup imported successfully")
    except ImportError as e:
        print(f"  ❌ BeautifulSoup import failed: {e}")
        return False
    
    try:
        import lxml
        print("  ✅ lxml imported successfully")
    except ImportError as e:
        print(f"  ❌ lxml import failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("Enhanced Web Research - Simple Test Suite")
    print("=" * 45)
    
    try:
        # Test imports
        imports_ok = test_imports()
        
        # Test URL validation
        validation_ok = test_url_validation()
        
        if imports_ok and validation_ok:
            print("\n✅ All tests passed! The web research functionality is ready to use.")
            print("\nTo test the full functionality:")
            print("1. Run: python -m streamlit run cognitive_nexus_advanced.py")
            print("2. Navigate to the Web Research tab")
            print("3. Try extracting content from: https://example.com")
        else:
            print("\n❌ Some tests failed. Please check the errors above.")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
