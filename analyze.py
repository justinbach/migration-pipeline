#!/usr/bin/env python3
"""
Analyze a captured webpage screenshot to identify components.

Usage:
    python analyze.py [--captures-dir captures]

Requires:
    - ANTHROPIC_API_KEY environment variable
    - A previous capture (screenshot.png in captures directory)

Outputs:
    - captures/components.json (identified components with descriptions)
"""

import os
import sys
import json
import base64
import argparse
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


def load_image_as_base64(image_path: str) -> str:
    """Load an image file and return as base64 string."""
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def analyze_screenshot(client: Anthropic, screenshot_path: str, metadata: dict) -> dict:
    """
    Send screenshot to Claude for component analysis.
    
    Returns structured component inventory.
    """
    image_data = load_image_as_base64(screenshot_path)
    
    prompt = """Analyze this webpage screenshot and identify all distinct UI components.

For each component, provide:
1. **type**: A semantic component type name (e.g., "hero-banner", "feature-card", "comparison-table", "testimonial-carousel", "cta-button", "footer", etc.)
2. **description**: Brief description of what this component displays/does
3. **location**: Approximate vertical position (top/upper/middle/lower/bottom) and horizontal position (full-width/left/center/right)
4. **content_summary**: Key content elements (headlines, images, CTAs, data)
5. **visual_notes**: Notable styling (colors, layout pattern, icons)

Group repeated patterns as a single component type with a count.

Return your analysis as JSON in this exact format:
{
    "page_summary": "Brief description of the page's purpose",
    "component_count": <number>,
    "components": [
        {
            "id": "component-1",
            "type": "hero-banner",
            "description": "...",
            "location": {"vertical": "top", "horizontal": "full-width"},
            "content_summary": "...",
            "visual_notes": "...",
            "instances": 1
        }
    ]
}

Be thorough—identify every distinct component, including navigation, footers, and any floating/sticky elements. Marketing pages often have 10-20 distinct component types."""

    print("Sending screenshot to Claude for analysis...")
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
            }
        ],
    )
    
    # Extract the response text
    response_text = response.content[0].text
    
    # Try to parse JSON from the response
    # Claude sometimes wraps JSON in markdown code blocks
    json_str = response_text
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0]
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0]
    
    try:
        analysis = json.loads(json_str.strip())
    except json.JSONDecodeError as e:
        print(f"Warning: Could not parse response as JSON: {e}")
        print("Raw response saved for inspection.")
        analysis = {
            "raw_response": response_text,
            "parse_error": str(e)
        }
    
    return analysis


def main():
    parser = argparse.ArgumentParser(description="Analyze captured webpage for components")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing capture files")
    args = parser.parse_args()
    
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    # Verify capture files exist
    screenshot_path = os.path.join(args.captures_dir, "screenshot.png")
    metadata_path = os.path.join(args.captures_dir, "metadata.json")
    
    if not os.path.exists(screenshot_path):
        print(f"Error: Screenshot not found at {screenshot_path}")
        print("Run capture.py first.")
        sys.exit(1)
    
    # Load metadata
    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        print(f"Analyzing capture of: {metadata.get('title', 'Unknown page')}")
    
    # Initialize Anthropic client
    client = Anthropic()
    
    # Run analysis
    analysis = analyze_screenshot(client, screenshot_path, metadata)
    
    # Save results
    output_path = os.path.join(args.captures_dir, "components.json")
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"\nAnalysis saved to: {output_path}")
    
    # Print summary
    if "components" in analysis:
        print(f"\n--- Analysis Summary ---")
        print(f"Page: {analysis.get('page_summary', 'N/A')}")
        print(f"Components identified: {analysis.get('component_count', len(analysis['components']))}")
        print(f"\nComponent types found:")
        for comp in analysis["components"]:
            instances = comp.get("instances", 1)
            instance_str = f" (×{instances})" if instances > 1 else ""
            print(f"  • {comp['type']}{instance_str}: {comp['description'][:60]}...")
    else:
        print("Analysis did not return structured components. Check components.json for raw output.")


if __name__ == "__main__":
    main()