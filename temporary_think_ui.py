"""
Temporary Thinking UI for Cognitive Nexus
========================================

A reusable wrapper that shows clickable reasoning panels only while AI processes run,
then automatically removes them, leaving only clean user-facing outputs.

Key Features:
- Reasoning panel appears only during processing (if user clicks to show)
- Automatically disappears after completion
- Clean final output without reasoning clutter
- Works across all AI modules (chat, image gen, web research, memory)
- Progress bars and status updates during processing
- Modular design for easy integration

Author: Cognitive Nexus AI System
Version: 1.0
"""

import streamlit as st
import time
import json
import uuid
from typing import Callable, Dict, Any, Optional, Tuple
from datetime import datetime

def _default_reasoning(process_type: str, user_input: str, context: Optional[Dict[str, Any]]) -> str:
    """Generate default reasoning content for any process type"""
    ctx_size = len(context or {})
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    return (
        f"🧠 {process_type.upper()} REASONING - {timestamp}\n"
        f"📥 Input: {user_input}\n"
        f"🔍 Context items: {ctx_size}\n"
        f"⚡ Processing steps:\n"
        f"  1) Analyze request and intent\n"
        f"  2) Retrieve/prepare context\n"
        f"  3) Plan response/parameters\n"
        f"  4) Execute main process\n"
        f"  5) Quality assurance + finalize\n"
        f"  6) Deliver clean output\n"
    )

def run_with_temp_reasoning(
    process_type: str,
    user_input: str,
    ai_fn: Callable[..., Any],
    context: Optional[Dict[str, Any]] = None,
    loading_message: str = "Processing...",
    success_message: str = "Done!",
    show_reasoning_label: str = "🧠 Show reasoning while processing",
    reasoning_text_fn: Optional[Callable[[str, str, Optional[Dict[str, Any]]], str]] = None,
    progress_steps: Optional[Tuple[Tuple[int, str], ...]] = None,
) -> Any:
    """
    Wraps any AI process with an optional, temporary reasoning panel that:
    - appears only while the process runs (if user clicks to show)
    - disappears automatically after completion
    - leaves only the clean, user-facing output

    Args:
        process_type: Type of process (chat, image_gen, web_research, memory, performance)
        user_input: User's input/request
        ai_fn: AI function to execute (may accept: user_input, context, progress_cb, log_cb)
        context: Additional context for the AI function
        loading_message: Message to show while processing
        success_message: Message to show when complete
        show_reasoning_label: Label for the reasoning toggle checkbox
        reasoning_text_fn: Custom function to generate reasoning text
        progress_steps: Custom progress steps [(percentage, message), ...]

    Returns:
        Result from ai_fn or None if error
    """
    context = context or {}
    key_suffix = str(uuid.uuid4()).replace("-", "")[:8]

    # Containers that we will fully clear at the end
    chrome_box = st.empty()     # holds the reasoning toggle + expander while running
    status_box = st.empty()     # holds the status/info while running
    prog_box = st.empty()       # holds the progress bar
    output_box = st.empty()     # final output target

    # UI chrome (toggle + expander live only during processing)
    with chrome_box.container():
        cols = st.columns([1, 9])
        with cols[0]:
            want_reason = st.checkbox(show_reasoning_label, key=f"think_toggle_{key_suffix}", value=False)
        expander = None
        if want_reason:
            expander = st.expander("🧠 AI Thinking...", expanded=True)
            with expander:
                think_area = st.empty()

    with status_box:
        st.info(f"🤖 {loading_message}")

    # Progress setup
    with prog_box:
        pbar = st.progress(0, text="Initializing...")

    # Default progress steps if not provided
    if not progress_steps:
        if process_type == "chat":
            progress_steps = (
                (15, "Understanding intent..."),
                (35, "Retrieving context..."),
                (60, "Generating response..."),
                (85, "Refining output..."),
            )
        elif process_type == "image_gen":
            progress_steps = (
                (20, "Analyzing prompt..."),
                (40, "Setting parameters..."),
                (65, "Generating image..."),
                (85, "Optimizing result..."),
            )
        elif process_type == "web_research":
            progress_steps = (
                (25, "Fetching content..."),
                (45, "Processing text..."),
                (70, "Generating embeddings..."),
                (85, "Storing knowledge..."),
            )
        elif process_type == "memory":
            progress_steps = (
                (30, "Searching memory..."),
                (55, "Analyzing context..."),
                (80, "Compiling results..."),
            )
        elif process_type == "performance":
            progress_steps = (
                (35, "Collecting metrics..."),
                (65, "Analyzing performance..."),
                (85, "Generating recommendations..."),
            )
        else:
            progress_steps = (
                (25, "Processing..."),
                (50, "Analyzing..."),
                (75, "Finalizing..."),
            )

    # Reasoning text
    base_reason = (reasoning_text_fn or _default_reasoning)(process_type, user_input, context)
    live_reason_lines = [base_reason]

    def progress_cb(pct: int, msg: str):
        """Progress callback for AI function"""
        pbar.progress(max(0, min(pct, 100)) / 100.0, text=msg)

    def log_cb(msg: str):
        """Log callback for AI function - adds reasoning lines"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        live_reason_lines.append(f"  [{timestamp}] {msg}")
        if want_reason and expander is not None:
            with expander:
                # Show the most recent ~30 lines
                think_text = "\n".join(live_reason_lines[-30:])
                st.text(think_text)

    # Animate default progress steps (non-blocking hinting)
    for pct, msg in progress_steps:
        progress_cb(pct, msg)
        if want_reason and expander is not None:
            log_cb(msg)
        time.sleep(0.12)  # Brief pause to show progress

    # Execute the AI function
    try:
        # Try to pass callbacks if supported
        try:
            result = ai_fn(user_input, context, progress_cb, log_cb)
        except TypeError:
            # Fallback to simple signature
            result = ai_fn(user_input, context)

        # Finish progress
        progress_cb(100, success_message)
        status_box.success(f"✅ {success_message}")

        # Brief pause to let user see completion
        time.sleep(0.5)

        # IMPORTANT: Remove the entire reasoning chrome so only final output remains
        chrome_box.empty()
        prog_box.empty()

        # Show clean, user-facing result
        if isinstance(result, (str, int, float, bool)):
            output_box.write(result)
        elif isinstance(result, dict):
            # Try to render structured content nicely
            try:
                if all(isinstance(v, (str, int, float, bool)) for v in result.values()):
                    # Simple dict - show as formatted text
                    formatted = "\n".join([f"**{k}:** {v}" for k, v in result.items()])
                    output_box.markdown(formatted)
                else:
                    output_box.json(result)
            except Exception:
                output_box.write(result)
        else:
            output_box.write(result)

        return result

    except Exception as e:
        # Handle errors gracefully
        chrome_box.empty()
        prog_box.empty()
        status_box.error(f"❌ Error in {process_type}: {e}")
        output_box.error("Process failed. Please try again.")
        return None


# Example usage functions for different AI processes
def example_chat_ai(input_text: str, ctx: Dict[str, Any], progress_cb=None, log_cb=None):
    """Example chat AI function with reasoning callbacks"""
    time.sleep(0.3)
    progress_cb and progress_cb(20, "Understanding intent")
    log_cb and log_cb("Intent: Question about AI concepts")
    
    time.sleep(0.3)
    progress_cb and progress_cb(50, "Retrieving context")
    log_cb and log_cb("Context: Previous conversation about technology")
    
    time.sleep(0.3)
    progress_cb and progress_cb(80, "Generating response")
    log_cb and log_cb("Response strategy: Helpful and informative")
    
    return f"Hello! 😊 I understand you're asking about: '{input_text}'. How can I help you today?"

def example_image_ai(input_text: str, ctx: Dict[str, Any], progress_cb=None, log_cb=None):
    """Example image generation AI function"""
    progress_cb and progress_cb(25, "Analyzing prompt")
    log_cb and log_cb(f"Prompt analysis: '{input_text}'")
    time.sleep(0.4)
    
    progress_cb and progress_cb(60, "Generating image")
    log_cb and log_cb("Style: Realistic, Dimensions: 512x512")
    time.sleep(0.6)
    
    progress_cb and progress_cb(85, "Optimizing result")
    log_cb and log_cb("Quality optimization complete")
    time.sleep(0.4)
    
    return {
        "title": "Generated Image",
        "prompt": input_text,
        "style": ctx.get("style", "realistic"),
        "dimensions": ctx.get("dimensions", "512x512"),
        "status": "Successfully generated and saved to gallery"
    }

def example_research_ai(input_text: str, ctx: Dict[str, Any], progress_cb=None, log_cb=None):
    """Example web research AI function"""
    progress_cb and progress_cb(30, "Fetching content")
    log_cb and log_cb(f"Processing URL: {ctx.get('url', 'N/A')}")
    time.sleep(0.5)
    
    progress_cb and progress_cb(45, "Extracting text")
    log_cb and log_cb("Content extracted: 1,247 words")
    time.sleep(0.3)
    
    progress_cb and progress_cb(70, "Generating embeddings")
    log_cb and log_cb("Created 3 semantic chunks with embeddings")
    time.sleep(0.6)
    
    progress_cb and progress_cb(85, "Storing knowledge")
    log_cb and log_cb("Knowledge stored in unified brain")
    time.sleep(0.3)
    
    return "✅ URL processed successfully! I've stored the content in my knowledge base. Ask me any questions about it whenever you want insights."

def example_memory_ai(input_text: str, ctx: Dict[str, Any], progress_cb=None, log_cb=None):
    """Example memory AI function"""
    progress_cb and progress_cb(40, "Searching memory")
    log_cb and log_cb("Scanning conversation history")
    time.sleep(0.4)
    
    progress_cb and progress_cb(70, "Analyzing patterns")
    log_cb and log_cb("Key topics: AI, technology, productivity")
    time.sleep(0.4)
    
    return "🧠 **Memory Analysis Results:**\n- **Total conversations:** 12\n- **Key topics:** AI & Technology, Productivity, Design\n- **Memory health:** Excellent\n- **Most discussed:** AI concepts and applications"

def example_performance_ai(input_text: str, ctx: Dict[str, Any], progress_cb=None, log_cb=None):
    """Example performance AI function"""
    progress_cb and progress_cb(35, "Collecting metrics")
    log_cb and log_cb("CPU: 45%, Memory: 62%, GPU: Available")
    time.sleep(0.4)
    
    progress_cb and progress_cb(65, "Analyzing performance")
    log_cb and log_cb("All systems operating within normal parameters")
    time.sleep(0.4)
    
    progress_cb and progress_cb(85, "Generating recommendations")
    log_cb and log_cb("No immediate optimizations needed")
    time.sleep(0.3)
    
    return "🚀 **Performance Status:** Optimal\n- **CPU Usage:** 45% (Good)\n- **Memory Usage:** 62% (Good)\n- **Response Time:** 1.2s (Excellent)\n- **Recommendation:** System performing well, no actions needed"


# Demo/Test function
if __name__ == "__main__":
    st.set_page_config(page_title="Temporary Thinking UI Demo", layout="wide")
    
    st.title("🧠 Temporary Thinking UI - Demo")
    
    st.markdown("""
    This demo shows the temporary reasoning system in action:
    1. Click the reasoning checkbox to see AI thinking during processing
    2. Watch the progress and reasoning updates
    3. See how the reasoning disappears after completion
    4. Only the clean final output remains
    """)
    
    process_type = st.selectbox("Process Type", 
                               ["chat", "image_gen", "web_research", "memory", "performance"])
    
    user_input = st.text_input("User Input", "What is artificial intelligence?")
    
    context = st.text_area("Context (JSON)", '{"conversation_history": [], "style": "realistic"}')
    
    if st.button("🚀 Run AI Process"):
        try:
            context_dict = json.loads(context) if context else {}
            
            # Select appropriate AI function
            ai_functions = {
                "chat": example_chat_ai,
                "image_gen": example_image_ai,
                "web_research": example_research_ai,
                "memory": example_memory_ai,
                "performance": example_performance_ai
            }
            
            ai_fn = ai_functions.get(process_type, example_chat_ai)
            
            # Use the temporary reasoning wrapper
            result = run_with_temp_reasoning(
                process_type=process_type,
                user_input=user_input,
                ai_fn=ai_fn,
                context=context_dict,
                loading_message=f"Running {process_type}...",
                success_message=f"{process_type.title()} complete!"
            )
            
            if result:
                st.success("✅ Process completed successfully!")
            
        except json.JSONDecodeError:
            st.error("Invalid JSON in context field")
        except Exception as e:
            st.error(f"Error: {e}")
    
    st.divider()
    
    st.markdown("""
    ### 🔧 Integration Instructions
    
    **To use in your Cognitive Nexus app:**
    
    1. **Import the wrapper:**
       ```python
       from temporary_think_ui import run_with_temp_reasoning
       ```
    
    2. **Wrap your AI functions:**
       ```python
       result = run_with_temp_reasoning(
           process_type="chat",
           user_input=user_input,
           ai_fn=your_ai_function,
           context=context
       )
       ```
    
    3. **Your AI function can optionally use callbacks:**
       ```python
       def your_ai_function(input_text, context, progress_cb=None, log_cb=None):
           progress_cb and progress_cb(50, "Processing...")
           log_cb and log_cb("Step completed")
           return "Your result"
       ```
    
    **Key Features:**
    - ✅ Reasoning panel appears only during processing
    - ✅ Automatically disappears after completion
    - ✅ Clean final output without reasoning clutter
    - ✅ Progress bars and status updates
    - ✅ Works with any AI function signature
    - ✅ Modular design for easy integration
    """)
