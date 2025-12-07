x#!/usr/bin/env python3
"""
Fix relative URLs in page-data.json by converting them to absolute URLs.

Usage:
    python fix_urls.py [--captures-dir captures] [--angular-dir angular-app]

This resolves relative URLs like "/content/dam/..." to absolute URLs using the source domain.
"""

import os
import sys
import json
import argparse
import re
from urllib.parse import urljoin


def fix_urls_recursive(obj, base_url: str, fixed_count: list):
    """Recursively fix relative URLs in a data structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and is_relative_url(value):
                obj[key] = urljoin(base_url, value)
                fixed_count[0] += 1
            else:
                fix_urls_recursive(value, base_url, fixed_count)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and is_relative_url(item):
                obj[i] = urljoin(base_url, item)
                fixed_count[0] += 1
            else:
                fix_urls_recursive(item, base_url, fixed_count)


def is_relative_url(value: str) -> bool:
    """Check if a string looks like a relative URL."""
    if not value:
        return False
    
    # Patterns that indicate a relative URL
    relative_patterns = [
        r'^/[a-zA-Z]',  # Starts with / followed by letter (e.g., /content/...)
        r'^\.\./',      # Starts with ../
        r'^\.\/',       # Starts with ./
    ]
    
    # Patterns that indicate NOT a URL (to avoid false positives)
    not_url_patterns = [
        r'^\d',         # Starts with number
        r'^#',          # Anchor
        r'^javascript:', # JavaScript
        r'^mailto:',    # Email
        r'^tel:',       # Phone
    ]
    
    for pattern in not_url_patterns:
        if re.match(pattern, value):
            return False
    
    for pattern in relative_patterns:
        if re.match(pattern, value):
            return True
    
    return False


def extract_base_url(metadata_path: str) -> str:
    """Extract base URL from capture metadata."""
    if not os.path.exists(metadata_path):
        return None
    
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    
    url = metadata.get("url", "")
    domain = metadata.get("domain", "")
    
    if domain:
        # Construct base URL from domain
        return f"https://{domain}"
    
    return None


def main():
    parser = argparse.ArgumentParser(description="Fix relative URLs in page data")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing captures")
    parser.add_argument("--angular-dir", default="angular-app", help="Angular project directory")
    parser.add_argument("--base-url", default=None, help="Override base URL (e.g., https://example.com)")
    args = parser.parse_args()
    
    # Load page data
    page_data_path = os.path.join(args.captures_dir, "page-data.json")
    if not os.path.exists(page_data_path):
        print(f"Error: Page data not found at {page_data_path}")
        sys.exit(1)
    
    with open(page_data_path, "r") as f:
        page_data = json.load(f)
    
    # Get base URL
    base_url = args.base_url
    if not base_url:
        metadata_path = os.path.join(args.captures_dir, "metadata.json")
        base_url = extract_base_url(metadata_path)
    
    if not base_url:
        print("Error: Could not determine base URL")
        print("Provide --base-url argument or ensure metadata.json exists")
        sys.exit(1)
    
    print(f"Base URL: {base_url}")
    
    # Fix URLs
    fixed_count = [0]
    fix_urls_recursive(page_data, base_url, fixed_count)
    
    print(f"Fixed {fixed_count[0]} relative URLs")
    
    # Save updated page data
    with open(page_data_path, "w") as f:
        json.dump(page_data, f, indent=2)
    print(f"Updated: {page_data_path}")
    
    # Also update the copy in Angular assets
    angular_page_data = os.path.join(args.angular_dir, "src", "assets", "page-data.json")
    if os.path.exists(os.path.dirname(angular_page_data)):
        with open(angular_page_data, "w") as f:
            json.dump(page_data, f, indent=2)
        print(f"Updated: {angular_page_data}")
    
    # Show some examples of fixed URLs
    print("\nSample fixed URLs:")
    sample_count = 0
    for comp in page_data.get("components", []):
        data = comp.get("data", {})
        for key, value in data.items():
            if isinstance(value, str) and value.startswith(base_url):
                print(f"  {key}: {value[:80]}...")
                sample_count += 1
                if sample_count >= 5:
                    break
        if sample_count >= 5:
            break


if __name__ == "__main__":
    main()