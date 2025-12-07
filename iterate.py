#!/usr/bin/env python3
"""
Iteratively improve components based on visual comparison feedback.

Usage:
    python iterate.py [--captures-dir captures] [--angular-dir angular-app] [--max-iterations 3]

This script:
1. Captures the current Angular output
2. Compares it to the source
3. Identifies the worst-performing sections
4. Asks Claude to improve those components
5. Repeats until threshold is met or max iterations reached

Requires:
    - ANTHROPIC_API_KEY environment variable
    - Angular app running on localhost:4200
    - Previous captures (screenshot.png, page-data.json)
"""

import os
import sys
import json
import time
import base64
import argparse
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic, RateLimitError
from PIL import Image
import numpy as np
from skimage.metrics import structural_similarity as ssim

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


def capture_angular_output(captures_dir: str) -> str:
    """Capture current Angular app screenshot."""
    from playwright.sync_api import sync_playwright
    
    output_path = os.path.join(captures_dir, "angular-output.png")
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://localhost:4200", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.screenshot(path=output_path, full_page=True)
        browser.close()
    
    return output_path


def load_image_as_base64(image_path: str) -> str:
    """Load image and return as base64."""
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def compute_section_scores(source_path: str, generated_path: str, num_sections: int = 10) -> list:
    """Compute SSIM scores for each section of the page."""
    source = Image.open(source_path).convert('RGB')
    generated = Image.open(generated_path).convert('RGB')
    
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    
    # Resize if needed
    if generated_w != source_w:
        ratio = source_w / generated_w
        new_height = int(generated_h * ratio)
        generated = generated.resize((source_w, new_height), Image.Resampling.LANCZOS)
        generated_h = new_height
    
    compare_height = min(source_h, generated_h)
    section_height = compare_height // num_sections
    
    sections = []
    for i in range(num_sections):
        y_start = i * section_height
        y_end = min((i + 1) * section_height, compare_height)
        
        source_section = np.array(source.crop((0, y_start, source_w, y_end)))
        generated_section = np.array(generated.crop((0, y_start, source_w, y_end)))
        
        source_gray = np.mean(source_section, axis=2)
        generated_gray = np.mean(generated_section, axis=2)
        
        score = ssim(source_gray, generated_gray, data_range=255)
        
        sections.append({
            "index": i,
            "y_start": y_start,
            "y_end": y_end,
            "ssim": score
        })
    
    return sections


def extract_section_images(source_path: str, generated_path: str, y_start: int, y_end: int, output_dir: str) -> tuple:
    """Extract and save section images for comparison."""
    source = Image.open(source_path).convert('RGB')
    generated = Image.open(generated_path).convert('RGB')
    
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    
    # Scale y coordinates for generated image if heights differ
    gen_scale = generated_h / source_h
    gen_y_start = int(y_start * gen_scale)
    gen_y_end = int(y_end * gen_scale)
    
    source_section = source.crop((0, y_start, source_w, min(y_end, source_h)))
    generated_section = generated.crop((0, gen_y_start, generated_w, min(gen_y_end, generated_h)))
    
    source_section_path = os.path.join(output_dir, "section_source.png")
    generated_section_path = os.path.join(output_dir, "section_generated.png")
    
    source_section.save(source_section_path)
    generated_section.save(generated_section_path)
    
    return source_section_path, generated_section_path


def identify_component_for_section(section_y_start: int, section_y_end: int, page_data: dict) -> dict:
    """
    Try to identify which component corresponds to a section.
    This is approximate since we don't have exact component boundaries.
    """
    components = page_data.get("components", [])
    
    # For now, map sections to components by order
    # In a more sophisticated version, we'd use DOM analysis to get actual positions
    num_components = len(components)
    
    # Estimate which component this section falls into
    # This is a rough heuristic
    section_mid = (section_y_start + section_y_end) / 2
    
    # Assume page is ~5000px and components are roughly evenly distributed
    estimated_component_height = 5000 / num_components
    component_index = min(int(section_mid / estimated_component_height), num_components - 1)
    
    return components[component_index] if component_index < num_components else None


def improve_component(client: Anthropic, component: dict, source_img_b64: str, generated_img_b64: str, 
                      current_html: str, current_scss: str, current_ts: str) -> dict:
    """
    Ask Claude to improve a component based on visual comparison.
    
    Returns dict with improved 'html', 'scss', 'ts' code.
    """
    component_type = component.get("type", "unknown")
    component_data = component.get("data", {})
    
    prompt = f"""You are improving an Angular component to better match a source design.

COMPONENT TYPE: {component_type}

COMPONENT DATA:
{json.dumps(component_data, indent=2)}

CURRENT TYPESCRIPT:
```typescript
{current_ts}
```

CURRENT HTML:
```html
{current_html}
```

CURRENT SCSS:
```scss
{current_scss}
```

I'm showing you two images:
1. FIRST IMAGE: The SOURCE design (what we're trying to match)
2. SECOND IMAGE: The CURRENT output (what our component currently renders)

Please analyze the differences and provide improved code that better matches the source design. Focus on:
- Layout and spacing
- Colors and backgrounds
- Typography (sizes, weights, line heights)
- Component structure
- Missing elements
- Responsive behavior

Return JSON in this exact format:
{{
  "analysis": "Brief description of what's different and what you're fixing",
  "ts": "// Complete improved TypeScript code",
  "html": "<!-- Complete improved HTML template -->",
  "scss": "/* Complete improved SCSS styles */"
}}

Make the output match the source as closely as possible while keeping the code clean and maintainable."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "SOURCE DESIGN (target to match):"
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": source_img_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": "CURRENT OUTPUT (what we have now):"
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": generated_img_b64
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
            json_str = json_str.split("```")[1].split("```")[0]
        
        return json.loads(json_str.strip())
    
    except Exception as e:
        print(f"    Error improving component: {e}")
        return None


def read_component_files(angular_dir: str, component_type: str) -> tuple:
    """Read current component files."""
    kebab_name = component_type.replace("_", "-")
    component_dir = os.path.join(angular_dir, "src", "app", "components", kebab_name)
    
    ts_path = os.path.join(component_dir, f"{kebab_name}.component.ts")
    html_path = os.path.join(component_dir, f"{kebab_name}.component.html")
    scss_path = os.path.join(component_dir, f"{kebab_name}.component.scss")
    
    ts_content = ""
    html_content = ""
    scss_content = ""
    
    if os.path.exists(ts_path):
        with open(ts_path, "r") as f:
            ts_content = f.read()
    
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            html_content = f.read()
    
    if os.path.exists(scss_path):
        with open(scss_path, "r") as f:
            scss_content = f.read()
    
    return ts_content, html_content, scss_content


def write_component_files(angular_dir: str, component_type: str, ts: str, html: str, scss: str):
    """Write improved component files."""
    kebab_name = component_type.replace("_", "-")
    component_dir = os.path.join(angular_dir, "src", "app", "components", kebab_name)
    
    os.makedirs(component_dir, exist_ok=True)
    
    with open(os.path.join(component_dir, f"{kebab_name}.component.ts"), "w") as f:
        f.write(ts)
    
    with open(os.path.join(component_dir, f"{kebab_name}.component.html"), "w") as f:
        f.write(html)
    
    with open(os.path.join(component_dir, f"{kebab_name}.component.scss"), "w") as f:
        f.write(scss)


def compute_overall_ssim(source_path: str, generated_path: str) -> float:
    """Compute overall SSIM score."""
    source = Image.open(source_path).convert('RGB')
    generated = Image.open(generated_path).convert('RGB')
    
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    
    if generated_w != source_w:
        ratio = source_w / generated_w
        new_height = int(generated_h * ratio)
        generated = generated.resize((source_w, new_height), Image.Resampling.LANCZOS)
        generated_h = new_height
    
    compare_height = min(source_h, generated_h)
    
    source_crop = np.array(source.crop((0, 0, source_w, compare_height)))
    generated_crop = np.array(generated.crop((0, 0, source_w, compare_height)))
    
    source_gray = np.mean(source_crop, axis=2)
    generated_gray = np.mean(generated_crop, axis=2)
    
    return ssim(source_gray, generated_gray, data_range=255)


def main():
    parser = argparse.ArgumentParser(description="Iteratively improve components")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing captures")
    parser.add_argument("--angular-dir", default="angular-app", help="Angular project directory")
    parser.add_argument("--max-iterations", type=int, default=3, help="Maximum improvement iterations")
    parser.add_argument("--target-ssim", type=float, default=0.80, help="Target SSIM score")
    parser.add_argument("--components-per-iteration", type=int, default=3, help="Components to improve per iteration")
    args = parser.parse_args()
    
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    # Check for required files
    source_path = os.path.join(args.captures_dir, "screenshot.png")
    page_data_path = os.path.join(args.captures_dir, "page-data.json")
    
    if not os.path.exists(source_path):
        print(f"Error: Source screenshot not found at {source_path}")
        sys.exit(1)
    
    if not os.path.exists(page_data_path):
        print(f"Error: Page data not found at {page_data_path}")
        sys.exit(1)
    
    with open(page_data_path, "r") as f:
        page_data = json.load(f)
    
    client = Anthropic()
    
    print(f"Starting iterative improvement (max {args.max_iterations} iterations)")
    print(f"Target SSIM: {args.target_ssim:.0%}")
    print("=" * 60)
    
    for iteration in range(1, args.max_iterations + 1):
        print(f"\n[Iteration {iteration}/{args.max_iterations}]")
        
        # Capture current state
        print("  Capturing Angular output...")
        generated_path = capture_angular_output(args.captures_dir)
        
        # Compute overall score
        overall_ssim = compute_overall_ssim(source_path, generated_path)
        print(f"  Current SSIM: {overall_ssim:.2%}")
        
        if overall_ssim >= args.target_ssim:
            print(f"\n✓ Target SSIM {args.target_ssim:.0%} achieved!")
            break
        
        # Find worst sections
        print("  Analyzing sections...")
        sections = compute_section_scores(source_path, generated_path, num_sections=10)
        sections_sorted = sorted(sections, key=lambda x: x["ssim"])
        worst_sections = sections_sorted[:args.components_per_iteration]
        
        print(f"  Worst sections: {[f'{s['index']}({s['ssim']:.0%})' for s in worst_sections]}")
        
        # Improve components for worst sections
        improved_components = set()
        
        for section in worst_sections:
            # Identify component
            component = identify_component_for_section(
                section["y_start"], 
                section["y_end"], 
                page_data
            )
            
            if not component or component["type"] in improved_components:
                continue
            
            component_type = component["type"]
            improved_components.add(component_type)
            
            print(f"\n  Improving: {component_type}")
            
            # Extract section images
            source_section, generated_section = extract_section_images(
                source_path, generated_path,
                section["y_start"], section["y_end"],
                args.captures_dir
            )
            
            # Load current code
            current_ts, current_html, current_scss = read_component_files(
                args.angular_dir, component_type
            )
            
            if not current_ts:
                print(f"    Skipping - component files not found")
                continue
            
            # Get improvement
            source_img_b64 = load_image_as_base64(source_section)
            generated_img_b64 = load_image_as_base64(generated_section)
            
            improved = improve_component(
                client, component,
                source_img_b64, generated_img_b64,
                current_html, current_scss, current_ts
            )
            
            if improved:
                print(f"    Analysis: {improved.get('analysis', 'N/A')[:80]}...")
                
                # Write improved files
                write_component_files(
                    args.angular_dir, component_type,
                    improved.get("ts", current_ts),
                    improved.get("html", current_html),
                    improved.get("scss", current_scss)
                )
                print(f"    ✓ Updated component files")
            else:
                print(f"    ✗ Failed to improve")
            
            # Rate limit delay
            time.sleep(3)
        
        # Wait for Angular to rebuild
        print("\n  Waiting for Angular rebuild...")
        time.sleep(5)
    
    # Final score
    print("\n" + "=" * 60)
    generated_path = capture_angular_output(args.captures_dir)
    final_ssim = compute_overall_ssim(source_path, generated_path)
    print(f"Final SSIM: {final_ssim:.2%}")
    
    if final_ssim >= args.target_ssim:
        print(f"✓ SUCCESS - Target {args.target_ssim:.0%} achieved")
    else:
        print(f"✗ Target {args.target_ssim:.0%} not reached after {args.max_iterations} iterations")
        print(f"  Consider: more iterations, manual refinement, or adjusting expectations")


if __name__ == "__main__":
    main()