# 🧠 Temporary Thinking UI - Integration Guide

## 📋 Overview

The Temporary Thinking UI provides a clean, clickable interface that shows AI reasoning **only while processing**, then automatically removes it, leaving only clean user-facing outputs.

**Key Concept:** Reasoning appears temporarily during AI processing, disappears after completion.

## 🏗️ How It Works

```
User Input → 🧠 Checkbox → Reasoning Panel (while processing) → Clean Output (after completion)

Flow:
1. User starts AI process
2. Optional reasoning panel appears (if checkbox clicked)
3. AI processes with reasoning visible
4. Reasoning automatically disappears
5. Clean final output remains
```

## 🚀 Quick Integration

### 1. Import the System

```python
from temporary_think_ui import run_with_temp_reasoning
```

### 2. Wrap Your AI Functions

```python
# Instead of:
result = your_ai_function(input, context)
st.write(result)

# Use:
result = run_with_temp_reasoning(
    process_type="chat",
    user_input=user_input,
    ai_fn=your_ai_function,
    context=context
)
```

### 3. Complete Example

```python
def chat_ai_function(input_text, context, progress_cb=None, log_cb=None):
    """Your AI function with optional callbacks"""
    time.sleep(0.3)
    progress_cb and progress_cb(20, "Understanding intent")
    log_cb and log_cb("Intent: Question about AI")
    
    time.sleep(0.4)
    progress_cb and progress_cb(80, "Generating response")
    log_cb and log_cb("Response strategy: Helpful and informative")
    
    return "Hello! How can I help you today?"

# Use the wrapper
result = run_with_temp_reasoning(
    process_type="chat",
    user_input="What is AI?",
    ai_fn=chat_ai_function,
    context={"conversation_history": []},
    loading_message="Thinking about your question...",
    success_message="Response ready!"
)
```

## 🔧 Process Types

### Supported Process Types

```python
# Chat responses
run_with_temp_reasoning(
    process_type="chat",
    user_input=user_input,
    ai_fn=chat_function,
    context={"conversation_history": history}
)

# Image generation
run_with_temp_reasoning(
    process_type="image_gen",
    user_input=prompt,
    ai_fn=image_generation_function,
    context={"style": "realistic", "dimensions": "512x512"}
)

# Web research
run_with_temp_reasoning(
    process_type="web_research",
    user_input=url,
    ai_fn=web_research_function,
    context={"operation": "process_url"}
)

# Memory operations
run_with_temp_reasoning(
    process_type="memory",
    user_input=query,
    ai_fn=memory_function,
    context={"operation": "search"}
)

# Performance monitoring
run_with_temp_reasoning(
    process_type="performance",
    user_input="analyze",
    ai_fn=performance_function,
    context={"metrics": ["cpu", "memory", "gpu"]}
)
```

## 🎨 UI Features

### Clickable Reasoning Checkbox

```python
# The 🧠 checkbox appears automatically
# Users can click to show/hide reasoning during processing
# Reasoning auto-hides after completion
```

### Progress Indicators

```python
# Progress bars show processing steps
# Status messages update in real-time
# Different progress steps for each process type
```

### Clean Outputs

```python
# User-facing results are clean and actionable
# Internal reasoning is hidden by default
# Reasoning disappears automatically after completion
```

## 🔧 Function Parameters

### AI Function Signature

```python
def your_ai_function(input_text, context, progress_cb=None, log_cb=None):
    """
    Your AI function can optionally accept:
    - input_text: User's input
    - context: Additional context dictionary
    - progress_cb: Callback for progress updates (percentage, message)
    - log_cb: Callback for reasoning log messages
    """
    
    # Use callbacks if provided
    progress_cb and progress_cb(50, "Processing...")
    log_cb and log_cb("Step completed")
    
    return "Your result"
```

### Wrapper Parameters

```python
run_with_temp_reasoning(
    process_type="chat",                    # Process type identifier
    user_input="User input",                # User's request
    ai_fn=your_function,                    # Function to execute
    context={},                             # Additional context
    loading_message="Processing...",        # Loading message
    success_message="Complete!",            # Success message
    show_reasoning_label="🧠 Show reasoning", # Checkbox label
    reasoning_text_fn=None,                 # Custom reasoning generator
    progress_steps=None                     # Custom progress steps
)
```

## 📊 Integration Examples

### Chat Module

```python
if selected_tab == "💬 Chat":
    user_input = st.text_input("Message:")
    
    if st.button("Send") and user_input:
        def chat_ai(input_text, ctx, progress_cb=None, log_cb=None):
            progress_cb and progress_cb(20, "Understanding intent")
            log_cb and log_cb("Intent recognized")
            time.sleep(0.3)
            
            progress_cb and progress_cb(80, "Generating response")
            log_cb and log_cb("Response composed")
            time.sleep(0.3)
            
            return f"Hello! How can I help you today?"
        
        run_with_temp_reasoning(
            process_type="chat",
            user_input=user_input,
            ai_fn=chat_ai,
            context={"conversation_history": []},
            loading_message="Thinking about your message...",
            success_message="Response ready!"
        )
```

### Image Generation

```python
if selected_tab == "🎨 Image Generation":
    prompt = st.text_input("Prompt:", "A beautiful sunset")
    
    if st.button("Generate") and prompt:
        def image_ai(input_text, ctx, progress_cb=None, log_cb=None):
            progress_cb and progress_cb(25, "Analyzing prompt")
            log_cb and log_cb(f"Prompt: {input_text}")
            time.sleep(0.4)
            
            progress_cb and progress_cb(60, "Generating image")
            log_cb and log_cb("Inference running...")
            time.sleep(0.6)
            
            progress_cb and progress_cb(85, "Optimizing result")
            log_cb and log_cb("Quality enhancement applied")
            time.sleep(0.4)
            
            return {
                "title": "Generated Image",
                "prompt": input_text,
                "status": "Successfully generated"
            }
        
        run_with_temp_reasoning(
            process_type="image_gen",
            user_input=prompt,
            ai_fn=image_ai,
            context={"style": "realistic", "dimensions": "512x512"},
            loading_message="Creating your image...",
            success_message="Image generated!"
        )
```

### Web Research

```python
if selected_tab == "🌐 Web Research":
    url = st.text_input("URL:", "https://example.com")
    
    if st.button("Process URL") and url:
        def research_ai(input_text, ctx, progress_cb=None, log_cb=None):
            progress_cb and progress_cb(30, "Fetching content")
            log_cb and log_cb(f"Processing: {ctx.get('url')}")
            time.sleep(0.5)
            
            progress_cb and progress_cb(60, "Generating embeddings")
            log_cb and log_cb("Creating semantic chunks")
            time.sleep(0.6)
            
            progress_cb and progress_cb(85, "Storing knowledge")
            log_cb and log_cb("Knowledge stored in brain")
            time.sleep(0.3)
            
            return "URL processed. Ask questions about the content!"
        
        run_with_temp_reasoning(
            process_type="web_research",
            user_input=f"Process URL: {url}",
            ai_fn=research_ai,
            context={"url": url},
            loading_message="Scraping and processing...",
            success_message="Processing complete!"
        )
```

## 🎯 Key Benefits

### For Users
- **Clean Interface:** No permanent reasoning clutter
- **Optional Transparency:** See AI thinking only when needed
- **Focused Results:** Clean final outputs without distractions
- **Learning Tool:** Understand AI decision-making when desired

### For Developers
- **Easy Integration:** Drop-in wrapper for existing functions
- **Flexible:** Works with any AI function signature
- **Modular:** Same system across all modules
- **Maintainable:** Centralized reasoning display logic

### For System
- **Consistent:** Unified experience across all AI processes
- **Scalable:** Efficient reasoning management
- **Clean:** Automatic cleanup prevents interface bloat
- **Professional:** Polished user experience

## 🔧 Customization

### Custom Progress Steps

```python
# Define custom progress steps for your process
custom_steps = (
    (20, "Step 1..."),
    (50, "Step 2..."),
    (80, "Step 3..."),
)

run_with_temp_reasoning(
    process_type="custom",
    user_input=input_text,
    ai_fn=your_function,
    progress_steps=custom_steps
)
```

### Custom Reasoning Generator

```python
def custom_reasoning(process_type, user_input, context):
    return f"Custom reasoning for {process_type}: {user_input}"

run_with_temp_reasoning(
    process_type="custom",
    user_input=input_text,
    ai_fn=your_function,
    reasoning_text_fn=custom_reasoning
)
```

## 📁 File Structure

```
cognitive_nexus_ai/
├── temporary_think_ui.py                   # Core temporary thinking system
├── cognitive_nexus_temp_thinking.py        # Complete integration example
├── TEMP_THINKING_INTEGRATION_GUIDE.md      # This guide
└── ai_system/
    └── knowledge_bank/
        └── reasoning/                      # Reasoning data storage
```

## 🧪 Testing

### Test the System

```bash
streamlit run cognitive_nexus_temp_thinking.py
```

### Test Individual Components

```python
from temporary_think_ui import run_with_temp_reasoning

def test_function(input_text, context, progress_cb=None, log_cb=None):
    progress_cb and progress_cb(50, "Testing...")
    log_cb and log_cb("Test step completed")
    return "Test result"

result = run_with_temp_reasoning(
    process_type="test",
    user_input="Test input",
    ai_fn=test_function,
    context={}
)
```

## 🚨 Troubleshooting

### Common Issues

**1. Reasoning Not Showing**
```python
# Make sure to click the 🧠 checkbox
# Reasoning only appears if checkbox is checked
```

**2. Function Signature Issues**
```python
# Your function should accept at least (input_text, context)
# Optional callbacks: (input_text, context, progress_cb, log_cb)
```

**3. Import Errors**
```bash
# Ensure temporary_think_ui.py is in the same directory
pip install streamlit
```

### Performance Tips

- **Use callbacks efficiently** - don't call them too frequently
- **Keep reasoning messages concise** - avoid very long log messages
- **Test with different process types** - ensure consistent behavior
- **Monitor memory usage** - reasoning data is temporary but still uses memory

## 🎉 Ready to Use!

The Temporary Thinking UI system provides:

- **Clickable reasoning panels** that appear only during processing
- **Automatic cleanup** after completion
- **Clean final outputs** without reasoning clutter
- **Progress indicators** and status updates
- **Modular design** for easy integration
- **Flexible function signatures** for any AI process

**Start integrating today!** 🚀

The system gives you exactly what you wanted - reasoning that exists only while the AI is processing, visible in a clickable expandable panel, then automatically disappears to leave only the clean final output.
