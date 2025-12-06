#!/usr/bin/env python3
"""
Capture a webpage screenshot and HTML for analysis.

Usage:
    python capture.py <url>
    
Example:
    python capture.py "https://example.com/some-page"

Outputs:
    - captures/screenshot.png (full-page screenshot)
    - captures/page.html (raw HTML)
    - captures/metadata.json (capture metadata)
"""

import sys
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


def capture_page(url: str, output_dir: str = "captures") -> dict:
    """
    Capture screenshot and HTML from a URL.
    
    Returns metadata about the capture.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch()
        
        # Create a page with a realistic viewport and user agent
        page = browser.new_page(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        print(f"Navigating to {url}...")
        # Use domcontentloaded instead of networkidle—marketing pages with 
        # tracking pixels often never fully settle
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # Scroll down the page to trigger lazy-loaded images
        print("Scrolling to load lazy content...")
        page.evaluate("""async () => {
            const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
            const scrollHeight = document.body.scrollHeight;
            const viewportHeight = window.innerHeight;
            
            for (let y = 0; y < scrollHeight; y += viewportHeight) {
                window.scrollTo(0, y);
                await delay(300);
            }
            // Scroll back to top for the screenshot
            window.scrollTo(0, 0);
            await delay(500);
        }""")
        
        # Give the page time to render after scrolling
        page.wait_for_timeout(3000)
        
        # Get page title
        title = page.title()
        print(f"Page title: {title}")
        
        # Capture full-page screenshot
        screenshot_path = os.path.join(output_dir, "screenshot.png")
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"Screenshot saved: {screenshot_path}")
        
        # Capture HTML
        html_content = page.content()
        html_path = os.path.join(output_dir, "page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"HTML saved: {html_path}")
        
        # Get some basic page metrics
        metrics = page.evaluate("""() => {
            return {
                scrollHeight: document.body.scrollHeight,
                scrollWidth: document.body.scrollWidth,
                numElements: document.querySelectorAll('*').length,
                numImages: document.querySelectorAll('img').length,
                numLinks: document.querySelectorAll('a').length,
                numButtons: document.querySelectorAll('button').length,
                numForms: document.querySelectorAll('form').length,
                numSections: document.querySelectorAll('section').length,
            }
        }""")
        
        browser.close()
    
    # Build metadata
    metadata = {
        "url": url,
        "domain": urlparse(url).netloc,
        "title": title,
        "captured_at": datetime.now().isoformat(),
        "viewport": {"width": 1440, "height": 900},
        "metrics": metrics,
        "files": {
            "screenshot": "screenshot.png",
            "html": "page.html"
        }
    }
    
    # Save metadata
    metadata_path = os.path.join(output_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"Metadata saved: {metadata_path}")
    
    return metadata


def main():
    if len(sys.argv) < 2:
        print("Usage: python capture.py <url>")
        print("Example: python capture.py 'https://example.com/page'")
        sys.exit(1)
    
    url = sys.argv[1]
    
    # Basic URL validation
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        print(f"Error: Invalid URL '{url}'")
        print("Make sure to include the scheme (https://)")
        sys.exit(1)
    
    metadata = capture_page(url)
    
    print("\n--- Capture Summary ---")
    print(f"Title: {metadata['title']}")
    print(f"Elements: {metadata['metrics']['numElements']}")
    print(f"Images: {metadata['metrics']['numImages']}")
    print(f"Links: {metadata['metrics']['numLinks']}")
    print(f"Page height: {metadata['metrics']['scrollHeight']}px")
    print(f"\nFiles saved to: captures/")


if __name__ == "__main__":
    main()