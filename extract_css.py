#!/usr/bin/env python3
"""
Extract CSS from captured HTML source.

This extracts:
1. All <style> blocks
2. All linked stylesheet URLs
3. Inline styles and the classes they're associated with

Usage:
    python extract_css.py [--captures-dir captures]

Outputs:
    - captures/extracted-styles.css (all CSS combined)
    - captures/css-analysis.json (metadata about extracted styles)
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def extract_style_blocks(html: str) -> list:
    """Extract all <style> block contents."""
    pattern = re.compile(r'<style[^>]*>(.*?)</style>', re.DOTALL | re.IGNORECASE)
    return pattern.findall(html)


def extract_stylesheet_links(html: str) -> list:
    """Extract all linked stylesheet URLs."""
    pattern = re.compile(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
    links = pattern.findall(html)
    
    # Also try alternate order (href before rel)
    pattern2 = re.compile(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\']', re.IGNORECASE)
    links.extend(pattern2.findall(html))
    
    return list(set(links))


def extract_inline_styles(html: str) -> dict:
    """Extract inline styles and associate with elements."""
    pattern = re.compile(r'<(\w+)[^>]*class=["\']([^"\']*)["\'][^>]*style=["\']([^"\']*)["\']', re.IGNORECASE)
    
    inline_styles = {}
    for match in pattern.finditer(html):
        tag, classes, style = match.groups()
        for cls in classes.split():
            if cls not in inline_styles:
                inline_styles[cls] = []
            inline_styles[cls].append({
                'tag': tag,
                'style': style
            })
    
    return inline_styles


def extract_all_classes(html: str) -> set:
    """Extract all CSS class names used in the HTML."""
    pattern = re.compile(r'class=["\']([^"\']*)["\']', re.IGNORECASE)
    
    all_classes = set()
    for match in pattern.finditer(html):
        classes = match.group(1).split()
        all_classes.update(classes)
    
    return all_classes


def fetch_external_stylesheet(url: str, base_url: str) -> str:
    """Fetch an external stylesheet."""
    if not HAS_REQUESTS:
        print(f"  Skipping external stylesheet (requests not installed): {url}")
        return ""
    
    full_url = url if url.startswith('http') else urljoin(base_url, url)
    
    try:
        print(f"  Fetching: {full_url[:80]}...")
        response = requests.get(full_url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        response.raise_for_status()
        return f"/* From: {full_url} */\n{response.text}\n"
    except Exception as e:
        print(f"  Failed to fetch {full_url}: {e}")
        return ""


def clean_css(css: str) -> str:
    """Clean up CSS - remove source maps, fix common issues."""
    # Remove source map comments
    css = re.sub(r'/\*#\s*sourceMappingURL=.*?\*/', '', css)
    
    # Remove multiple consecutive newlines
    css = re.sub(r'\n{3,}', '\n\n', css)
    
    return css.strip()


def main():
    parser = argparse.ArgumentParser(description="Extract CSS from source HTML")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing captures")
    parser.add_argument("--fetch-external", action="store_true", help="Fetch external stylesheets")
    args = parser.parse_args()
    
    html_path = os.path.join(args.captures_dir, "page.html")
    metadata_path = os.path.join(args.captures_dir, "metadata.json")
    
    if not os.path.exists(html_path):
        print(f"Error: HTML not found at {html_path}")
        sys.exit(1)
    
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    
    # Get base URL from metadata
    base_url = ""
    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
            base_url = f"https://{metadata.get('domain', '')}"
    
    print(f"Extracting CSS from {len(html):,} characters of HTML...")
    print(f"Base URL: {base_url}")
    
    # Extract embedded styles
    style_blocks = extract_style_blocks(html)
    print(f"Found {len(style_blocks)} embedded <style> blocks")
    
    # Extract stylesheet links
    stylesheet_links = extract_stylesheet_links(html)
    print(f"Found {len(stylesheet_links)} linked stylesheets")
    
    # Extract inline styles
    inline_styles = extract_inline_styles(html)
    print(f"Found {len(inline_styles)} classes with inline styles")
    
    # Extract all class names
    all_classes = extract_all_classes(html)
    print(f"Found {len(all_classes)} unique CSS classes")
    
    # Combine all CSS
    combined_css = []
    
    # Add embedded styles
    for i, block in enumerate(style_blocks):
        combined_css.append(f"/* === Embedded Style Block {i+1} === */")
        combined_css.append(clean_css(block))
    
    # Fetch external stylesheets if requested
    if args.fetch_external and stylesheet_links:
        print("\nFetching external stylesheets...")
        for link in stylesheet_links:
            css = fetch_external_stylesheet(link, base_url)
            if css:
                combined_css.append(css)
    
    # Convert inline styles to CSS rules
    if inline_styles:
        combined_css.append("/* === Inline Styles Converted to Classes === */")
        for cls, styles in inline_styles.items():
            # Take the first style as representative
            if styles:
                combined_css.append(f".{cls} {{ {styles[0]['style']} }}")
    
    # Write combined CSS
    css_output_path = os.path.join(args.captures_dir, "extracted-styles.css")
    with open(css_output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(combined_css))
    print(f"\nCSS written to: {css_output_path}")
    print(f"Total CSS size: {len(''.join(combined_css)):,} characters")
    
    # Write analysis
    analysis = {
        "embedded_style_blocks": len(style_blocks),
        "external_stylesheets": stylesheet_links,
        "inline_style_classes": list(inline_styles.keys())[:50],  # First 50
        "total_classes": len(all_classes),
        "sample_classes": sorted(list(all_classes))[:100],  # First 100 alphabetically
        "css_size_bytes": len("\n\n".join(combined_css))
    }
    
    analysis_path = os.path.join(args.captures_dir, "css-analysis.json")
    with open(analysis_path, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"Analysis written to: {analysis_path}")


if __name__ == "__main__":
    main()