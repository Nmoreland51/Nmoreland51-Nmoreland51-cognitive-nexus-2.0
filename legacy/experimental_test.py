import streamlit as st
import requests
import json
import os
import time
import random
from datetime import datetime

# Set page configuration
st.set_page_config(
    page_title="Experimental Cognitive Nexus AI",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

def main():
    st.title("🧪 Experimental Cognitive Nexus AI")
    st.markdown("**Testing basic functionality before running the full app**")
    
    # Test basic functionality
    st.markdown("### 🔍 System Tests")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**Python Test**")
        try:
            import sys
            st.success(f"✅ Python {sys.version.split()[0]}")
        except Exception as e:
            st.error(f"❌ Python Error: {e}")
    
    with col2:
        st.markdown("**Streamlit Test**")
        try:
            st.success(f"✅ Streamlit {st.__version__}")
        except Exception as e:
            st.error(f"❌ Streamlit Error: {e}")
    
    with col3:
        st.markdown("**Requests Test**")
        try:
            import requests
            st.success("✅ Requests Available")
        except Exception as e:
            st.error(f"❌ Requests Error: {e}")
    
    # Test web search functionality
    st.markdown("### 🌐 Web Search Test")
    
    if st.button("Test Web Search"):
        with st.spinner("Testing web search..."):
            try:
                # Simple DuckDuckGo test
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                url = "https://api.duckduckgo.com/?q=test&format=json&no_html=1&skip_disambig=1"
                response = requests.get(url, headers=headers, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    st.success("✅ Web search working!")
                    if data.get('Abstract'):
                        st.info(f"Sample result: {data['Abstract'][:100]}...")
                else:
                    st.warning(f"⚠️ Web search returned status: {response.status_code}")
                    
            except Exception as e:
                st.error(f"❌ Web search error: {e}")
    
    # Test chat functionality
    st.markdown("### 💬 Chat Test")
    
    # Display conversation
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Test the chat functionality..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                # Simple response
                response = f"🧪 Experimental response to: '{prompt}'. This is a test to verify the chat system is working correctly!"
                st.markdown(response)
        
        st.session_state.messages.append({"role": "assistant", "content": response})
    
    # System information
    st.markdown("### 📊 System Information")
    st.json({
        "Python Version": sys.version,
        "Streamlit Version": st.__version__,
        "Current Time": datetime.now().isoformat(),
        "Working Directory": os.getcwd(),
        "Available Modules": ["streamlit", "requests", "json", "os", "time", "random", "datetime"]
    })

if __name__ == "__main__":
    main()

