# 🎨 Image Generation Feature Guide

## Overview

The Cognitive Nexus AI now includes a fully functional **Image Generation** tab that allows users to generate images from text prompts using local Stable Diffusion models. This feature provides privacy-focused image generation without sending data to external services.

## ✨ Features

### 🖼️ Image Generation
- **Text-to-Image**: Generate images from detailed text prompts
- **Multiple Styles**: 8 different artistic styles (realistic, artistic, cartoon, abstract, etc.)
- **Customizable Dimensions**: 512x512, 768x768, or 1024x1024 pixels
- **Seed Control**: Reproducible images using seed values
- **Advanced Settings**: Quality steps and guidance scale controls

### 📚 Image Management
- **Automatic Storage**: All generated images saved to `/ai_system/knowledge_bank/images/`
- **Metadata Tracking**: Complete generation details stored as JSON
- **Generation History**: View and browse past generations
- **Gallery View**: Visual gallery of recent images

### 🔧 Technical Features
- **Local Processing**: No data sent to external services
- **GPU Acceleration**: Automatic CUDA detection and optimization
- **Memory Optimization**: Efficient memory usage for large models
- **Error Handling**: Comprehensive error logging and user feedback

## 🚀 Quick Start

### 1. Install Dependencies

Run the installation script:
```bash
install_image_generation.bat
```

Or install manually:
```bash
pip install torch diffusers pillow transformers accelerate safetensors
```

### 2. Launch the Advanced Version

```bash
python -m streamlit run cognitive_nexus_advanced.py --server.port 8504
```

Or use the launcher:
```bash
run_advanced_cognitive_nexus.bat
```

### 3. Enable Image Generation

1. Open the sidebar (⚙️ Settings)
2. Enable "🎨 Image Generation"
3. Navigate to the "🎨 Image Generation" tab

## 📖 Usage Guide

### Basic Image Generation

1. **Enter a Prompt**: Describe the image you want to generate
   - Be descriptive and specific
   - Include details about colors, mood, style, and composition
   - Example: "a beautiful sunset over mountains, peaceful landscape, warm colors"

2. **Choose Style**: Select from 8 available styles:
   - **Realistic**: Photorealistic, high quality, detailed
   - **Artistic**: Artistic style, creative, expressive
   - **Cartoon**: Cartoon style, animated, colorful
   - **Abstract**: Abstract art, creative, artistic
   - **Photographic**: Professional photography, high resolution
   - **Digital Art**: Digital art, concept art, detailed
   - **Watercolor**: Watercolor painting, soft colors
   - **Oil Painting**: Oil painting, classical art style

3. **Set Dimensions**: Choose image size (512x512, 768x768, or 1024x1024)

4. **Optional Seed**: Enter a number for reproducible results

5. **Click Generate**: Wait 30-60 seconds for generation

### Advanced Settings

Click "⚙️ Advanced Settings" to access:
- **Quality Steps**: 10-50 (higher = better quality but slower)
- **Guidance Scale**: 1.0-20.0 (how closely to follow the prompt)

### Viewing Results

- **Generated Image**: Displayed immediately after generation
- **Metadata**: Click "📋 Generation Details" to see full generation info
- **History**: Browse recent generations in the sidebar
- **Gallery**: Visual gallery of past images

## 🛠️ Technical Details

### Model Information
- **Model**: Stable Diffusion v1.5 (runwayml/stable-diffusion-v1-5)
- **Size**: ~4GB download on first use
- **Device**: Automatic CUDA/CPU detection
- **Optimizations**: Memory-efficient attention, VAE slicing

### File Structure
```
ai_system/knowledge_bank/images/
├── generated_20250916_123456_abc123.png    # Generated image
├── generated_20250916_123456_abc123.json   # Metadata
└── ...                                     # More generations
```

### Metadata Format
```json
{
  "prompt": "original user prompt",
  "enhanced_prompt": "prompt with style enhancements",
  "style": "realistic",
  "width": 768,
  "height": 768,
  "seed": 12345,
  "timestamp": "2025-09-16T12:34:56",
  "filename": "generated_20250916_123456_abc123.png",
  "filepath": "/path/to/image.png"
}
```

## 🔧 Troubleshooting

### Common Issues

**1. "Image generation is not available"**
- Solution: Install dependencies using `install_image_generation.bat`
- Check: Ensure all packages are installed correctly

**2. "Failed to load image generation model"**
- Cause: Insufficient memory or corrupted model download
- Solution: Restart the application, ensure 8GB+ RAM available

**3. "CUDA out of memory"**
- Cause: GPU memory insufficient
- Solution: Reduce image dimensions or use CPU mode

**4. Slow generation**
- Normal: First generation takes longer (model loading)
- Optimization: Use GPU if available, reduce quality steps

### System Requirements

**Minimum:**
- RAM: 8GB
- Storage: 10GB free space
- CPU: Multi-core processor

**Recommended:**
- RAM: 16GB+
- GPU: NVIDIA with 6GB+ VRAM
- Storage: SSD with 20GB+ free space

## 📊 Performance Tips

### For Faster Generation
1. Use GPU acceleration (automatic if available)
2. Reduce quality steps (20 is good balance)
3. Use smaller dimensions for testing
4. Keep model loaded in memory

### For Better Quality
1. Use higher quality steps (30-50)
2. Increase guidance scale (8-12)
3. Use larger dimensions (1024x1024)
4. Write detailed, specific prompts

## 🔒 Privacy & Security

- **Local Processing**: All generation happens on your device
- **No Data Sharing**: Prompts and images never leave your computer
- **Local Storage**: Images stored only on your system
- **No Internet Required**: Works completely offline after model download

## 🆕 Future Enhancements

Planned features:
- **Batch Generation**: Generate multiple images at once
- **Image Editing**: Inpainting and outpainting capabilities
- **Style Transfer**: Apply styles from reference images
- **Custom Models**: Support for custom Stable Diffusion models
- **API Integration**: Optional cloud API fallback

## 📞 Support

If you encounter issues:
1. Check the logs in `/ai_system/logs/reports.log`
2. Verify system requirements
3. Try restarting the application
4. Check available disk space and memory

---

**🎨 Happy Creating!** The Image Generation feature brings the power of AI art creation directly to your Cognitive Nexus AI experience.
