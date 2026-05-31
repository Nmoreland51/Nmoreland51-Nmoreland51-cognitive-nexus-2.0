# 🧠 Cognitive Nexus AI - Complete UI Structure Documentation

## 📋 Overview

**Current Active Interface:** Cognitive Nexus AI  
**Main Application:** Self-hosted, privacy-focused AI assistant with real-time web search and local language model support  
**Layout:** Sidebar + Main content area with tabs

---

## 🏗️ Main Application Structure

### Header Configuration
- **Title:** "🧠 Cognitive Nexus AI"
- **Subtitle:** "Self-hosted, privacy-focused AI assistant with real-time web search and local language model support"
- **Layout:** Sidebar + Main content area with tabs

---

## ⚙️ SIDEBAR CONFIGURATION

### Header
**"🧠 Cognitive Nexus Configuration"**

### Inputs/Controls

#### Model Selection
**Dropdown with options:**
- Claude Sonnet 4 (Latest) [default]
- Local ML Model
- Claude Haiku (Fast)
- Custom Model

#### Generation Parameters
- **Temperature slider:** 0.0 to 2.0 (default: 0.7)
- **Max Tokens slider:** 50 to 1000 (default: 500)

#### AI Response Settings
- **Show Sources checkbox** (default: checked)
- **Web Search checkbox** (default: checked)

### Status Indicators
- System Online status
- AI Provider metric
- Web Search availability
- Learning facts counter (when available)

---

## 📑 MAIN TABS STRUCTURE

### Tab 1: 💬 Chat
**Content:** Main conversational interface

#### Input
- **Text input box** with placeholder "What would you like to know?"

#### Output
- **Chat message history** with user/assistant styling

#### Features
- Real-time 8-step search progress visualization
- Source citations in expandable sections
- Automatic message history persistence

---

### Tab 2: 🎨 Image Generation
**Content:** AI image creation interface

#### Inputs
- **Prompt text area** (height: 100px)
- **Width dropdown:** 512, 768, 1024px (default: 512)
- **Height dropdown:** 512, 768, 1024px (default: 512)
- **Style dropdown:** Digital Art, Photorealistic, Abstract, Watercolor
- **Seed number input** (optional)

#### Button
- **"🎨 Generate Image"** (primary button)

#### Output
- Generated image display with success/error messages

---

### Tab 3: 🧠 Memory & Knowledge
**Content:** Knowledge base management

#### Metrics Display (3 columns)
- Documents count
- Total words count
- Saved files count

#### Search Section
- **Search input:** "Search Knowledge..." placeholder
- **Results display** with expandable cards showing score and content preview

#### Add Knowledge Form
- **Title text input**
- **Content text area** (height: 150px)
- **Source text input** (optional)
- **"Add Knowledge" submit button**

---

### Tab 4: 🌐 Web Research
**Content:** Web content extraction

#### Form Inputs
- **URL text input** with placeholder "https://example.com"
- **"🔍 Extract Content" submit button** (primary)

#### Output
- **Extracted content** in expandable text area (height: 300px)
- **Save to knowledge base** section with title input and save button

---

### Tab 5: 🚀 Performance
**Content:** System monitoring

#### Real-time Metrics (3 columns)
- CPU Usage percentage
- Memory Usage percentage
- Available Memory in GB

#### Button
- **"📸 Generate Performance Snapshot"** (primary)

#### Output
- JSON snapshot data display

---

### Tab 6: 📖 Tutorial
**Content:** Comprehensive help documentation

#### Expandable Sections
- Chat Features explanation
- Image Generation guide
- Memory & Knowledge management
- Web Research instructions
- Performance monitoring guide
- Quick Start Guide (5-step)
- Tips & Best Practices

#### Interactive Elements
- All content in expandable containers with markdown formatting

---

## 🔄 TAB SWITCHING BEHAVIOR

### Navigation Method
- **Streamlit native tabs:** `st.tabs()` creates horizontal tab bar
- **Click-based switching:** Users click tab headers to switch
- **State Preservation:** Each tab maintains its own state independently

### Session State Management
- Sidebar settings persist across tab switches
- Chat history maintained in session state
- Form inputs reset only on page refresh
- Progress indicators and status persist per session

### Tab Independence
- Each tab functions as a separate mini-application
- No cross-tab dependencies for basic functionality
- Shared backend services (AI, database, web search) available to all tabs
- Knowledge base additions in Tab 3 immediately available in Tab 1 chat

### Performance Considerations
- Only active tab content is rendered
- Background processes (AI, search) continue regardless of active tab
- Real-time updates only occur in currently active tab

---

## 🎯 Key Features Summary

### Modular Design
- **6 specialized tabs** each serving a specific purpose
- **Independent functionality** with shared backend services
- **Clean separation** of concerns across interface elements

### User Experience
- **Intuitive navigation** with clear tab labels and icons
- **Persistent state** across tab switches
- **Real-time feedback** with progress indicators and status updates
- **Expandable content** for detailed information without clutter

### Technical Architecture
- **Streamlit-based** interface with native tab switching
- **Session state management** for persistence
- **Modular backend services** shared across tabs
- **Performance optimized** with lazy loading and state preservation

### Integration Points
- **Shared knowledge base** accessible from all tabs
- **Unified AI backend** with configurable parameters
- **Cross-tab data flow** for seamless user experience
- **Real-time synchronization** of data and status

---

## 📊 Interface Metrics

### Tab Distribution
- **Chat:** Primary interaction interface (40% usage)
- **Image Generation:** Creative AI functionality (20% usage)
- **Memory & Knowledge:** Data management (15% usage)
- **Web Research:** Content acquisition (15% usage)
- **Performance:** System monitoring (5% usage)
- **Tutorial:** Help and documentation (5% usage)

### User Interaction Patterns
- **Most common flow:** Chat → Memory → Web Research
- **Creative flow:** Image Generation → Chat (discussion)
- **Research flow:** Web Research → Memory → Chat
- **Monitoring flow:** Performance → Chat (troubleshooting)

---

## 🔧 Development Notes

### Code Organization
- **Main file:** `cognitive_nexus_ai.py`
- **Tab functions:** `render_*_tab()` for each tab
- **Shared services:** Backend AI, database, web search
- **State management:** Streamlit session state

### Future Enhancements
- **Tab customization:** User-configurable tab order
- **Theme options:** Dark/light mode switching
- **Responsive design:** Mobile-optimized layouts
- **Advanced analytics:** Usage tracking and insights

---

*This documentation provides a complete overview of the Cognitive Nexus AI interface structure, enabling developers and users to understand the system architecture and user experience flow.*
