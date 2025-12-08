#!/usr/bin/env python3
"""
Generate Angular components using source HTML/CSS as reference.

This is a smarter approach than generate.py - instead of asking Claude to
guess at styling, we give it the actual source markup and styles to work from.

Usage:
    python generate_v2.py [--captures-dir captures] [--output-dir angular-app]

Requires:
    - ANTHROPIC_API_KEY environment variable
    - Previous captures (screenshot.png, page.html, page-data.json)
"""

import os
import sys
import json
import time
import base64
import argparse
import re
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic, RateLimitError

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


def load_image_as_base64(image_path: str) -> str:
    """Load image and return as base64."""
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_styles_from_html(html: str) -> str:
    """Extract all inline and embedded styles from HTML."""
    styles = []
    
    # Extract <style> blocks
    style_pattern = re.compile(r'<style[^>]*>(.*?)</style>', re.DOTALL | re.IGNORECASE)
    for match in style_pattern.finditer(html):
        styles.append(match.group(1))
    
    # Extract inline styles (for reference)
    inline_pattern = re.compile(r'style="([^"]*)"', re.IGNORECASE)
    inline_styles = inline_pattern.findall(html)
    if inline_styles:
        styles.append(f"/* Inline styles found: {len(inline_styles)} elements */")
        # Just sample a few
        for style in inline_styles[:10]:
            styles.append(f"/* inline: {style[:100]} */")
    
    return "\n\n".join(styles)


def extract_component_html_region(html: str, component_type: str, component_data: dict) -> str:
    """
    Try to extract the relevant HTML region for a component.
    This is heuristic-based and won't be perfect.
    """
    # Use content from component_data to find the region
    search_terms = []
    
    # Extract text content to search for
    def extract_strings(obj, strings):
        if isinstance(obj, str) and len(obj) > 10 and len(obj) < 200:
            # Clean and add searchable strings
            clean = obj.strip()[:50]
            if clean and not clean.startswith('http') and not clean.startswith('/'):
                strings.append(clean)
        elif isinstance(obj, dict):
            for v in obj.values():
                extract_strings(v, strings)
        elif isinstance(obj, list):
            for item in obj:
                extract_strings(item, strings)
    
    extract_strings(component_data, search_terms)
    
    if not search_terms:
        return ""
    
    # Find regions containing these terms
    best_region = ""
    best_score = 0
    
    # Try to find a containing element
    # This is a simplified approach - look for sections/divs containing our content
    section_pattern = re.compile(r'<(section|div|article)[^>]*class="[^"]*"[^>]*>.*?</\1>', re.DOTALL | re.IGNORECASE)
    
    for match in section_pattern.finditer(html):
        region = match.group(0)
        score = sum(1 for term in search_terms if term in region)
        if score > best_score:
            best_score = score
            best_region = region[:5000]  # Limit size
    
    return best_region


def kebab_case(name: str) -> str:
    """Convert to kebab-case."""
    return name.replace('_', '-')


def pascal_case(name: str) -> str:
    """Convert to PascalCase."""
    return ''.join(word.capitalize() for word in name.replace('-', '_').split('_'))


def generate_component_with_reference(
    client: Anthropic, 
    component: dict,
    screenshot_b64: str,
    source_html_region: str,
    source_styles: str
) -> dict:
    """
    Generate Angular component with full context from source.
    """
    component_type = component['type']
    component_data = component.get('data', {})
    kebab_name = kebab_case(component_type)
    pascal_name = pascal_case(component_type) + 'Component'
    
    prompt = f"""Generate an Angular component that recreates this section from a marketing page.

COMPONENT TYPE: {component_type}
ANGULAR SELECTOR: app-{kebab_name}
COMPONENT CLASS: {pascal_name}

DATA TO RENDER:
```json
{json.dumps(component_data, indent=2)}
```

SOURCE HTML (from original page - use as structural reference):
```html
{source_html_region[:8000] if source_html_region else "Not available - infer from screenshot"}
```

SOURCE CSS (from original page - use as styling reference):
```css
{source_styles[:10000]}
```

I'm also showing you a SCREENSHOT of the original page. Find the section corresponding to "{component_type}" and match its appearance as closely as possible.

CRITICAL ANGULAR SYNTAX RULES - FOLLOW EXACTLY:
1. Use ONLY the new Angular control flow syntax:
   - Use @if (condition) {{ }} - NOT *ngIf
   - Use @for (item of items; track $index) {{ }} - NOT *ngFor
   - Use @else {{ }} after @if blocks when needed
2. NEVER use Math, parseInt, parseFloat, or any global in templates - create component methods instead
3. The @Input() data property must be typed as: @Input() data: any = null;
4. Inside @if (data) blocks, you can access data.property directly without optional chaining
5. For @for loops, always use "track $index" or "track item.id"
6. Every opening {{ must have a matching closing }}
7. Do NOT mix *ngIf/*ngFor with @if/@for - use ONLY @if/@for

COMPONENT STRUCTURE:
```typescript
import {{ Component, Input }} from '@angular/core';

@Component({{
  selector: 'app-{kebab_name}',
  standalone: true,
  imports: [],
  templateUrl: './{kebab_name}.component.html',
  styleUrls: ['./{kebab_name}.component.scss']
}})
export class {pascal_name} {{
  @Input() data: any = null;
  
  // Add helper methods here for any logic needed in template
}}
```

Return JSON in this exact format:
{{
  "ts": "// Complete TypeScript - must compile without errors",
  "html": "<!-- Complete HTML template using ONLY @if/@for syntax -->",
  "scss": "/* Complete SCSS styles */"
}}

Match the visual design from the screenshot as closely as possible."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            response_text = response.content[0].text
            
            # Parse JSON
            json_str = response_text
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                # Find the JSON block
                parts = json_str.split("```")
                for part in parts:
                    if part.strip().startswith("{"):
                        json_str = part
                        break
            
            return json.loads(json_str.strip())
            
        except RateLimitError:
            wait_time = 60 * (attempt + 1)
            print(f"    Rate limited, waiting {wait_time}s...")
            time.sleep(wait_time)
        except json.JSONDecodeError as e:
            print(f"    JSON parse error: {e}")
            print(f"    Response preview: {response_text[:500]}...")
            return None
        except Exception as e:
            print(f"    Error: {e}")
            return None
    
    return None


def write_component_files(output_dir: str, component_type: str, code: dict):
    """Write component files to Angular project."""
    kebab_name = kebab_case(component_type)
    component_dir = os.path.join(output_dir, "src", "app", "components", kebab_name)
    os.makedirs(component_dir, exist_ok=True)
    
    ts_path = os.path.join(component_dir, f"{kebab_name}.component.ts")
    html_path = os.path.join(component_dir, f"{kebab_name}.component.html")
    scss_path = os.path.join(component_dir, f"{kebab_name}.component.scss")
    
    with open(ts_path, "w") as f:
        f.write(code.get("ts", ""))
    
    with open(html_path, "w") as f:
        f.write(code.get("html", ""))
    
    with open(scss_path, "w") as f:
        f.write(code.get("scss", ""))


def main():
    parser = argparse.ArgumentParser(description="Generate Angular components with source reference")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing captures")
    parser.add_argument("--output-dir", default="angular-app", help="Angular project directory")
    parser.add_argument("--components", nargs="*", help="Specific components to regenerate (default: all)")
    args = parser.parse_args()
    
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    # Load required files
    screenshot_path = os.path.join(args.captures_dir, "screenshot.png")
    html_path = os.path.join(args.captures_dir, "page.html")
    page_data_path = os.path.join(args.captures_dir, "page-data.json")
    
    for path, name in [(screenshot_path, "screenshot"), (html_path, "HTML"), (page_data_path, "page data")]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)
    
    print("Loading source files...")
    screenshot_b64 = load_image_as_base64(screenshot_path)
    
    with open(html_path, "r", encoding="utf-8") as f:
        source_html = f.read()
    
    with open(page_data_path, "r") as f:
        page_data = json.load(f)
    
    components = page_data.get("components", [])
    
    # Filter components if specified
    if args.components:
        components = [c for c in components if c["type"] in args.components]
    
    print(f"Source HTML: {len(source_html):,} characters")
    print(f"Components to generate: {len(components)}")
    
    # Extract styles once
    print("Extracting source styles...")
    source_styles = extract_styles_from_html(source_html)
    print(f"Extracted {len(source_styles):,} characters of CSS")
    
    # Initialize client
    client = Anthropic()
    
    # Generate each component
    print("\nGenerating components...")
    successful = 0
    failed = 0
    
    for i, component in enumerate(components):
        component_type = component["type"]
        print(f"\n[{i+1}/{len(components)}] {component_type}")
        
        # Extract relevant HTML region for this component
        html_region = extract_component_html_region(
            source_html, 
            component_type, 
            component.get("data", {})
        )
        if html_region:
            print(f"  Found {len(html_region):,} chars of source HTML")
        else:
            print(f"  No source HTML region found, using screenshot only")
        
        # Generate
        code = generate_component_with_reference(
            client,
            component,
            screenshot_b64,
            html_region,
            source_styles
        )
        
        if code:
            write_component_files(args.output_dir, component_type, code)
            print(f"  ✓ Generated")
            successful += 1
        else:
            print(f"  ✗ Failed")
            failed += 1
        
        # Rate limit delay
        time.sleep(3)
    
    print(f"\n{'='*50}")
    print(f"Generation complete: {successful} succeeded, {failed} failed")
    print(f"\nTo see results:")
    print(f"  cd {args.output_dir} && ng serve")
    print(f"\nThen run: python compare.py")


if __name__ == "__main__":
    main()