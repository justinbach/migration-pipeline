#!/usr/bin/env python3
"""
Extract structured content from captured HTML based on component analysis.

Usage:
    python extract.py [--captures-dir captures] [--batch-size 3]

Requires:
    - ANTHROPIC_API_KEY environment variable
    - Previous capture (page.html) and analysis (components.json)

Outputs:
    - captures/page-data.json (structured content for all components)
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic, RateLimitError

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


def extract_component_batch(client: Anthropic, html: str, components: list, batch_num: int, total_batches: int) -> list:
    """
    Extract structured content for a batch of components from HTML.
    
    Returns list of extracted components.
    """
    
    # Build component descriptions for the prompt
    component_list = "\n".join([
        f"- {c['id']} ({c['type']}): {c['description']}"
        for c in components
    ])
    
    prompt = f"""Analyze this HTML and extract structured content for each component listed below.

COMPONENTS TO EXTRACT (batch {batch_num}/{total_batches}):
{component_list}

For each component, extract all relevant content (text, URLs, image sources, etc.) into a structured format appropriate for that component type.

Return JSON in this exact format:
{{
  "components": [
    {{
      "id": "component-1",
      "type": "hero-banner",
      "data": {{
        "headline": "extracted headline text",
        "subhead": "extracted subhead text",
        "cta_primary": {{
          "text": "Button text",
          "url": "https://..."
        }},
        "image_url": "https://...",
        // ... other fields as appropriate
      }}
    }}
  ]
}}

Guidelines:
1. Extract ACTUAL content from the HTML, not placeholder text
2. Preserve the original text exactly (don't paraphrase)
3. Extract full URLs (resolve relative URLs using the base domain if needed)
4. For repeated elements (like feature cards), extract as an array
5. For the comparison table, extract the full data structure including all rows and competitors
6. Include alt text for images when available
7. For components with multiple instances (like CTAs), extract each instance

Be thorough—this data will be used to reconstruct the page."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"HTML CONTENT:\n\n{html[:100000]}"  # Truncate if massive
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
            }
        ],
    )
    
    response_text = response.content[0].text
    
    # Parse JSON from response
    json_str = response_text
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0]
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0]
    
    try:
        extracted = json.loads(json_str.strip())
        return extracted.get("components", [])
    except json.JSONDecodeError as e:
        print(f"  Warning: Could not parse batch response as JSON: {e}")
        print(f"  Raw response preview: {response_text[:200]}...")
        return []


def main():
    parser = argparse.ArgumentParser(description="Extract content from captured HTML")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing capture files")
    parser.add_argument("--batch-size", type=int, default=3, help="Number of components to extract per API call")
    args = parser.parse_args()
    
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    # Verify required files exist
    html_path = os.path.join(args.captures_dir, "page.html")
    components_path = os.path.join(args.captures_dir, "components.json")
    
    if not os.path.exists(html_path):
        print(f"Error: HTML not found at {html_path}")
        print("Run capture.py first.")
        sys.exit(1)
    
    if not os.path.exists(components_path):
        print(f"Error: Component analysis not found at {components_path}")
        print("Run analyze.py first.")
        sys.exit(1)
    
    # Load files
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    print(f"Loaded HTML: {len(html):,} characters")
    
    with open(components_path, "r") as f:
        analysis = json.load(f)
    components = analysis.get("components", [])
    print(f"Components to extract: {len(components)}")
    
    # Initialize client
    client = Anthropic()
    
    # Process in batches
    all_extracted = []
    batch_size = args.batch_size
    total_batches = (len(components) + batch_size - 1) // batch_size
    
    for i in range(0, len(components), batch_size):
        batch = components[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        component_names = [c['type'] for c in batch]
        print(f"\nBatch {batch_num}/{total_batches}: Extracting {', '.join(component_names)}...")
        
        # Retry logic for rate limits
        max_retries = 3
        for attempt in range(max_retries):
            try:
                extracted = extract_component_batch(client, html, batch, batch_num, total_batches)
                
                if extracted:
                    all_extracted.extend(extracted)
                    print(f"  ✓ Extracted {len(extracted)} components")
                else:
                    print(f"  ✗ Failed to extract batch")
                break  # Success, exit retry loop
                
            except RateLimitError as e:
                wait_time = 60 * (attempt + 1)  # 60s, 120s, 180s
                print(f"  ⏳ Rate limited. Waiting {wait_time}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
                if attempt == max_retries - 1:
                    print(f"  ✗ Failed after {max_retries} retries")
        
        # Small delay between batches to avoid rate limits
        if i + batch_size < len(components):
            time.sleep(5)
    
    # Build final output
    output = {
        "components": all_extracted,
        "_metadata": {
            "source_html": "page.html",
            "component_analysis": "components.json",
            "total_components": len(components),
            "extracted_components": len(all_extracted),
            "batch_size": batch_size
        }
    }
    
    # Save results
    output_path = os.path.join(args.captures_dir, "page-data.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n\nExtracted content saved to: {output_path}")
    
    # Print summary
    print(f"\n--- Extraction Summary ---")
    print(f"Total components: {len(components)}")
    print(f"Successfully extracted: {len(all_extracted)}")
    
    if all_extracted:
        print(f"\nComponents extracted:")
        for comp in all_extracted:
            data_keys = list(comp.get("data", {}).keys())
            print(f"  • {comp['type']}: {len(data_keys)} fields")


if __name__ == "__main__":
    main()