#!/usr/bin/env python3
"""
Generate Angular components using original HTML structure and CSS classes.

Instead of generating new CSS, this approach:
1. Uses the extracted source CSS as global styles
2. Tells Claude to preserve original HTML structure and class names
3. Only adapts the HTML to Angular syntax (data binding, control flow)

Usage:
    python generate_transplant.py [--captures-dir captures] [--output-dir angular-app]
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

load_dotenv(Path(__file__).parent / ".env")


def load_image_as_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_component_html_from_source(html: str, component_data: dict) -> str:
    """
    Extract the relevant HTML section from source for a component.
    Uses content matching to find the right region.
    """
    # Get searchable text from component data
    search_terms = []
    
    def extract_text(obj):
        if isinstance(obj, str) and len(obj) > 15 and len(obj) < 200:
            clean = obj.strip()
            if clean and not clean.startswith('http') and not clean.startswith('/'):
                search_terms.append(clean[:60])
        elif isinstance(obj, dict):
            for v in obj.values():
                extract_text(v)
        elif isinstance(obj, list):
            for item in obj:
                extract_text(item)
    
    extract_text(component_data)
    
    if not search_terms:
        return ""
    
    # Find the best matching section/div
    # Look for semantic containers
    patterns = [
        r'<section[^>]*>.*?</section>',
        r'<div[^>]*class="[^"]*container[^"]*"[^>]*>.*?</div>',
        r'<div[^>]*class="[^"]*section[^"]*"[^>]*>.*?</div>',
        r'<div[^>]*class="[^"]*component[^"]*"[^>]*>.*?</div>',
    ]
    
    best_match = ""
    best_score = 0
    
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.DOTALL | re.IGNORECASE):
            region = match.group(0)
            if len(region) > 50000:  # Skip huge regions
                continue
            score = sum(1 for term in search_terms if term in region)
            if score > best_score:
                best_score = score
                best_match = region[:15000]  # Limit size
    
    return best_match


def kebab_case(name: str) -> str:
    return name.replace('_', '-')


def pascal_case(name: str) -> str:
    return ''.join(word.capitalize() for word in name.replace('-', '_').split('_'))


def generate_transplant_component(
    client: Anthropic,
    component: dict,
    source_html_region: str,
    screenshot_b64: str
) -> dict:
    """
    Generate Angular component that preserves original HTML structure.
    """
    component_type = component['type']
    component_data = component.get('data', {})
    kebab_name = kebab_case(component_type)
    pascal_name = pascal_case(component_type) + 'Component'
    
    prompt = f"""Convert this HTML section into an Angular component.

CRITICAL: Preserve the EXACT HTML structure and CSS class names from the source.
The original CSS is already loaded globally - your job is to keep the same classes so the styles work.

COMPONENT: {component_type}
SELECTOR: app-{kebab_name}
CLASS: {pascal_name}

DATA TO BIND:
```json
{json.dumps(component_data, indent=2)}
```

SOURCE HTML TO CONVERT:
```html
{source_html_region if source_html_region else "Source HTML not available - reconstruct from screenshot"}
```

CONVERSION RULES:
1. KEEP all original CSS class names exactly as they are
2. KEEP the same HTML element structure (divs, sections, spans, etc.)
3. REPLACE static text with Angular bindings: {{{{ data.fieldName }}}}
4. REPLACE static href/src with bindings: [href]="data.url" [src]="data.image"
5. ADD @if (data) wrapper around the whole template
6. ADD @if (data.field) before optional sections
7. ADD @for (item of data.items; track $index) for repeated elements
8. DO NOT add any new CSS classes
9. DO NOT change the HTML structure
10. DO NOT use *ngIf or *ngFor - use @if and @for

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
}}
```

The SCSS file should be nearly empty - just import or leave blank since styles are global:
```scss
/* Styles are in global extracted-styles.css */
```

Return JSON:
{{
  "ts": "// Complete TypeScript",
  "html": "<!-- Complete HTML preserving original classes -->",
  "scss": "/* Empty or minimal - global styles handle it */"
}}"""

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
            return None
        except Exception as e:
            print(f"    Error: {e}")
            return None
    
    return None


def write_component(output_dir: str, component_type: str, code: dict):
    """Write component files."""
    kebab_name = kebab_case(component_type)
    component_dir = os.path.join(output_dir, "src", "app", "components", kebab_name)
    os.makedirs(component_dir, exist_ok=True)
    
    with open(os.path.join(component_dir, f"{kebab_name}.component.ts"), "w") as f:
        f.write(code.get("ts", ""))
    
    with open(os.path.join(component_dir, f"{kebab_name}.component.html"), "w") as f:
        f.write(code.get("html", ""))
    
    with open(os.path.join(component_dir, f"{kebab_name}.component.scss"), "w") as f:
        f.write(code.get("scss", ""))


def setup_global_styles(captures_dir: str, output_dir: str):
    """Copy extracted CSS to Angular global styles."""
    src_css = os.path.join(captures_dir, "extracted-styles.css")
    
    if not os.path.exists(src_css):
        print("Warning: extracted-styles.css not found. Run extract_css.py first.")
        return
    
    # Read extracted CSS
    with open(src_css, "r", encoding="utf-8") as f:
        css = f.read()
    
    # Write to Angular's global styles
    styles_path = os.path.join(output_dir, "src", "styles.scss")
    
    with open(styles_path, "w", encoding="utf-8") as f:
        f.write("/* Extracted styles from source page */\n\n")
        f.write(css)
    
    print(f"Global styles written to: {styles_path}")
    print(f"Size: {len(css):,} characters")


def main():
    parser = argparse.ArgumentParser(description="Generate Angular components using source HTML/CSS")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing captures")
    parser.add_argument("--output-dir", default="angular-app", help="Angular project directory")
    parser.add_argument("--components", nargs="*", help="Specific components to regenerate")
    args = parser.parse_args()
    
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)
    
    # Load files
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
    
    if args.components:
        components = [c for c in components if c["type"] in args.components]
    
    print(f"Source HTML: {len(source_html):,} characters")
    print(f"Components to generate: {len(components)}")
    
    # Setup global styles first
    print("\nSetting up global styles...")
    setup_global_styles(args.captures_dir, args.output_dir)
    
    # Initialize client
    client = Anthropic()
    
    # Generate components
    print("\nGenerating components...")
    successful = 0
    failed = 0
    
    for i, component in enumerate(components):
        component_type = component["type"]
        print(f"\n[{i+1}/{len(components)}] {component_type}")
        
        # Extract source HTML for this component
        source_region = extract_component_html_from_source(
            source_html,
            component.get("data", {})
        )
        
        if source_region:
            print(f"  Found {len(source_region):,} chars of source HTML")
        else:
            print(f"  No source HTML found, using screenshot only")
        
        # Generate
        code = generate_transplant_component(
            client,
            component,
            source_region,
            screenshot_b64
        )
        
        if code:
            write_component(args.output_dir, component_type, code)
            print(f"  ✓ Generated")
            successful += 1
        else:
            print(f"  ✗ Failed")
            failed += 1
        
        time.sleep(2)  # Rate limit buffer
    
    print(f"\n{'='*50}")
    print(f"Complete: {successful} succeeded, {failed} failed")
    print(f"\nNext steps:")
    print(f"  cd {args.output_dir}")
    print(f"  ng build")
    print(f"  ng serve")


if __name__ == "__main__":
    main()