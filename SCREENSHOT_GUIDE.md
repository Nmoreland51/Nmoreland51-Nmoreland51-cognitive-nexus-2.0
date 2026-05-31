# Screenshot Guide for Cognitive Nexus

## Overview
This guide helps create professional screenshots for demos, documentation, and marketing materials.

## Recommended Screenshots

### 1. Main Interface
- **Purpose**: Show the clean, professional UI
- **Setup**:
  1. Enable "Demo mode" in sidebar
  2. Keep "Advanced mode" OFF for clean view
  3. Have sample chat conversation loaded
- **Capture**: Full browser window showing tabs
- **File**: `screenshot_main_interface.png`

### 2. Reality-First Research
- **Purpose**: Demonstrate research capabilities
- **Setup**:
  1. Go to "Reality-First Research" tab
  2. Enable demo mode to load sample research
  3. Show research results with verdict
- **Capture**: Research tab with sample report
- **File**: `screenshot_research_demo.png`

### 3. Web Research
- **Purpose**: Show web search integration
- **Setup**:
  1. Go to "Web Research" tab
  2. Enter a sample query (e.g., "latest AI developments")
  3. Show search results
- **Capture**: Search interface with results
- **File**: `screenshot_web_search.png`

### 4. Settings Panel
- **Purpose**: Show configuration options
- **Setup**:
  1. Go to "Settings" tab
  2. Show persona configuration
- **Capture**: Settings interface
- **File**: `screenshot_settings.png`

### 5. Logs/Status (Clean View)
- **Purpose**: Show system health monitoring
- **Setup**:
  1. Go to "Logs / Status" tab
  2. Keep "Advanced mode" OFF
  3. Show provider health cards
- **Capture**: Status dashboard
- **File**: `screenshot_status_clean.png`

### 6. Advanced Mode Details
- **Purpose**: Show developer capabilities
- **Setup**:
  1. Enable "Advanced mode" in sidebar
  2. Go to "Logs / Status" tab
  3. Expand some raw data sections
- **Capture**: Advanced diagnostics view
- **File**: `screenshot_advanced_mode.png`

## Screenshot Best Practices

### Browser Setup
- **Resolution**: 1920x1080 or higher
- **Zoom**: 100%
- **Theme**: Light mode (default)
- **Browser**: Chrome/Edge with minimal UI

### Composition
- **Full Window**: Capture entire browser window
- **Centered**: Center the app in viewport
- **No Distractions**: Hide browser bookmarks/toolbars if possible
- **Consistent**: Use same window size for all screenshots

### Timing
- **Wait for Load**: Ensure all content is loaded
- **Stable State**: No loading spinners or animations
- **Demo Data**: Use demo mode for consistent sample data

### Editing
- **Crop**: Remove browser chrome if needed
- **Annotate**: Add arrows or highlights for key features
- **Compress**: Optimize file size while maintaining quality
- **Format**: PNG for lossless quality

## Tools

### Built-in Tools
- **Windows**: Snip & Sketch (Win + Shift + S)
- **macOS**: Cmd + Shift + 4
- **Browser**: Right-click → "Take screenshot"

### Advanced Tools
- **ShareX**: Free screenshot tool with advanced features
- **Lightshot**: Quick annotation and sharing
- **Snagit**: Professional screenshot and editing

## File Organization

Store screenshots in `docs/screenshots/` or `marketing/screenshots/`:

```
screenshots/
├── main_interface.png
├── research_demo.png
├── web_search.png
├── settings.png
├── status_clean.png
├── advanced_mode.png
└── README.md
```

## Usage in Documentation

### README.md
```markdown
![Cognitive Nexus Interface](screenshots/main_interface.png)
*Clean, professional interface with reality-first research capabilities*
```

### Demo Script
Use screenshots in sequence for presentations:
1. Main interface
2. Research demo
3. Web search
4. Settings
5. Status monitoring

## Automation

For consistent screenshots, consider:
- **Browser Extensions**: Screenshot automation
- **Scripts**: Puppeteer or Selenium for automated captures
- **CI/CD**: Generate screenshots in automated builds

## Tips for Professional Results

1. **Consistent Styling**: Same browser, same settings
2. **High Quality**: High DPI, no compression artifacts
3. **Clear Focus**: Highlight key features with annotations
4. **Context**: Show real functionality, not just UI
5. **Updates**: Regenerate when UI changes significantly</content>
<parameter name="filePath">c:\Users\Nmore\Downloads\Nmoreland51-cognitive-nexus-main\Nmoreland51-cognitive-nexus-main\SCREENSHOT_GUIDE.md