#!/usr/bin/env python3
"""
Simple icon creator for Cognitive Nexus AI
Creates a basic icon file for the executable
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon():
    """Create a simple icon for the executable"""
    try:
        # Create a 256x256 image with a blue background
        size = 256
        img = Image.new('RGBA', (size, size), (0, 100, 200, 255))
        draw = ImageDraw.Draw(img)
        
        # Draw a simple brain/AI symbol
        # Outer circle
        draw.ellipse([20, 20, size-20, size-20], fill=(255, 255, 255, 255), outline=(0, 50, 100, 255), width=4)
        
        # Inner brain-like shape
        brain_points = [
            (size//2, 40),
            (60, 80),
            (50, 120),
            (70, 160),
            (size//2, 180),
            (size-70, 160),
            (size-50, 120),
            (size-60, 80),
            (size//2, 40)
        ]
        draw.polygon(brain_points, fill=(200, 230, 255, 255), outline=(0, 50, 100, 255), width=2)
        
        # Add some neural network dots
        for i in range(5):
            for j in range(5):
                x = 80 + i * 20
                y = 100 + j * 15
                if (i + j) % 2 == 0:
                    draw.ellipse([x-3, y-3, x+3, y+3], fill=(0, 100, 200, 255))
        
        # Save as ICO file
        img.save('icon.ico', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
        print("✅ Icon created successfully: icon.ico")
        return True
        
    except ImportError:
        print("⚠️  PIL not available, creating a simple text-based icon")
        # Create a simple text file as placeholder
        with open('icon.ico', 'w') as f:
            f.write("# Icon placeholder - replace with actual .ico file")
        return False
    except Exception as e:
        print(f"❌ Error creating icon: {e}")
        return False

if __name__ == "__main__":
    create_icon()
