#!/usr/bin/env python3
"""
Generate an Angular app with components based on extracted page data.

Usage:
    python generate.py [--captures-dir captures] [--output-dir angular-app]

Requires:
    - Node.js and Angular CLI installed
    - Previous extraction (page-data.json)

Outputs:
    - angular-app/ directory with complete Angular project
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")


def run_command(cmd: list, cwd: str = None) -> bool:
    """Run a shell command and return success status."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  Error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"  Exception: {e}")
        return False


def generate_component_code(client: Anthropic, component: dict) -> dict:
    """
    Use Claude to generate Angular component code based on extracted data.
    
    Returns dict with 'ts', 'html', 'scss' keys.
    """
    component_type = component['type']
    component_data = component.get('data', {})
    
    prompt = f"""Generate an Angular standalone component for a "{component_type}" component.

DATA STRUCTURE this component will receive as input:
{json.dumps(component_data, indent=2)}

Requirements:
1. Create a standalone Angular component (standalone: true)
2. Use @Input() to receive a 'data' object matching the structure above
3. Generate semantic HTML that renders all the data
4. Include SCSS styles that approximate a professional marketing page:
   - Use flexbox/grid for layout
   - Include reasonable spacing, typography, colors
   - Make it responsive
5. Handle missing/optional data gracefully with *ngIf
6. Use Angular best practices (trackBy for ngFor, etc.)

Return JSON in this exact format:
{{
  "component_name": "HeroBannerComponent",
  "selector": "app-hero-banner", 
  "ts": "// Full TypeScript component code here",
  "html": "<!-- Full HTML template here -->",
  "scss": "/* Full SCSS styles here */"
}}

Generate production-quality code that could actually render this component."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": prompt
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
        return json.loads(json_str.strip())
    except json.JSONDecodeError as e:
        print(f"    Warning: Could not parse component code: {e}")
        return None


def kebab_case(name: str) -> str:
    """Convert component type to kebab-case."""
    return name.replace('_', '-')


def pascal_case(name: str) -> str:
    """Convert component type to PascalCase."""
    return ''.join(word.capitalize() for word in name.replace('-', '_').split('_'))


def create_angular_project(output_dir: str) -> bool:
    """Create new Angular project using CLI."""
    if os.path.exists(output_dir):
        print(f"  Directory {output_dir} already exists, skipping ng new")
        return True
    
    print(f"  Creating Angular project in {output_dir}...")
    print(f"  (This may take a minute...)")
    cmd = [
        "ng", "new", output_dir,
        "--standalone",
        "--style=scss",
        "--routing=false",
        "--skip-git",
        "--skip-tests",
        "--inline-style=false",
        "--inline-template=false"
    ]
    
    # Run synchronously and wait for completion
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  Error: {result.stderr}")
            return False
        
        # Verify the project was created
        tsconfig_path = os.path.join(output_dir, "tsconfig.json")
        if not os.path.exists(tsconfig_path):
            print(f"  Error: Project created but tsconfig.json not found")
            return False
        
        print(f"  ✓ Angular project created")
        return True
    except subprocess.TimeoutExpired:
        print(f"  Error: Angular CLI timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"  Exception: {e}")
        return False


def write_component_files(output_dir: str, component_type: str, code: dict):
    """Write component files to the Angular project."""
    kebab_name = kebab_case(component_type)
    component_dir = os.path.join(output_dir, "src", "app", "components", kebab_name)
    os.makedirs(component_dir, exist_ok=True)
    
    # Write TypeScript
    ts_path = os.path.join(component_dir, f"{kebab_name}.component.ts")
    with open(ts_path, "w") as f:
        f.write(code.get("ts", ""))
    
    # Write HTML
    html_path = os.path.join(component_dir, f"{kebab_name}.component.html")
    with open(html_path, "w") as f:
        f.write(code.get("html", ""))
    
    # Write SCSS
    scss_path = os.path.join(component_dir, f"{kebab_name}.component.scss")
    with open(scss_path, "w") as f:
        f.write(code.get("scss", ""))


def generate_app_component(components: list, output_dir: str):
    """Generate the main app component that renders all page components."""
    
    # Build imports and component references
    imports = []
    component_tags = []
    
    for comp in components:
        kebab_name = kebab_case(comp['type'])
        pascal_name = pascal_case(comp['type']) + 'Component'
        imports.append(f"import {{ {pascal_name} }} from './components/{kebab_name}/{kebab_name}.component';")
        component_tags.append(f'  <app-{kebab_name} [data]="getComponentData(\'{comp["id"]}\')"></app-{kebab_name}>')
    
    # App component TypeScript
    app_ts = f'''import {{ Component }} from '@angular/core';
import {{ CommonModule }} from '@angular/common';
{chr(10).join(imports)}
import pageData from '../assets/page-data.json';

@Component({{
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    {', '.join([pascal_case(c['type']) + 'Component' for c in components])}
  ],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
}})
export class AppComponent {{
  pageData = pageData;

  getComponentData(id: string): any {{
    const component = this.pageData.components.find((c: any) => c.id === id);
    return component?.data || {{}};
  }}
}}
'''
    
    # App component HTML
    app_html = f'''<div class="page-container">
{chr(10).join(component_tags)}
</div>
'''
    
    # App component SCSS
    app_scss = '''/* Main page container */
.page-container {
  max-width: 100%;
  margin: 0 auto;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
}

/* Reset some defaults */
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  padding: 0;
}
'''
    
    # Write files
    app_dir = os.path.join(output_dir, "src", "app")
    
    with open(os.path.join(app_dir, "app.component.ts"), "w") as f:
        f.write(app_ts)
    
    with open(os.path.join(app_dir, "app.component.html"), "w") as f:
        f.write(app_html)
    
    with open(os.path.join(app_dir, "app.component.scss"), "w") as f:
        f.write(app_scss)


def copy_page_data(captures_dir: str, output_dir: str):
    """Copy page-data.json to Angular assets."""
    src = os.path.join(captures_dir, "page-data.json")
    dst_dir = os.path.join(output_dir, "src", "assets")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "page-data.json")
    
    with open(src, "r") as f:
        data = json.load(f)
    
    with open(dst, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"  Copied page-data.json to {dst}")


def update_tsconfig_for_json(output_dir: str):
    """Update tsconfig to allow JSON imports."""
    tsconfig_path = os.path.join(output_dir, "tsconfig.json")
    
    print(f"  Reading {tsconfig_path}...")
    
    try:
        with open(tsconfig_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if not content.strip():
            print(f"  Error: tsconfig.json is empty")
            return False
            
        tsconfig = json.loads(content)
    except Exception as e:
        print(f"  Error reading tsconfig.json: {e}")
        return False
    
    tsconfig["compilerOptions"]["resolveJsonModule"] = True
    tsconfig["compilerOptions"]["allowSyntheticDefaultImports"] = True
    
    with open(tsconfig_path, "w", encoding="utf-8") as f:
        json.dump(tsconfig, f, indent=2)
    
    print("  ✓ Updated tsconfig.json for JSON imports")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate Angular app from extracted data")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing extracted data")
    parser.add_argument("--output-dir", default="angular-app", help="Output directory for Angular project")
    args = parser.parse_args()
    
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    # Load extracted data
    page_data_path = os.path.join(args.captures_dir, "page-data.json")
    if not os.path.exists(page_data_path):
        print(f"Error: Extracted data not found at {page_data_path}")
        print("Run extract.py first.")
        sys.exit(1)
    
    with open(page_data_path, "r") as f:
        page_data = json.load(f)
    
    components = page_data.get("components", [])
    print(f"Loaded {len(components)} components to generate")
    
    # Create Angular project
    print("\n[1/4] Creating Angular project...")
    if not create_angular_project(args.output_dir):
        print("Failed to create Angular project")
        sys.exit(1)
    
    # Update tsconfig
    print("\n[2/4] Configuring project...")
    update_tsconfig_for_json(args.output_dir)
    copy_page_data(args.captures_dir, args.output_dir)
    
    # Generate components
    print("\n[3/4] Generating components...")
    client = Anthropic()
    
    generated_components = []
    for i, component in enumerate(components):
        print(f"  [{i+1}/{len(components)}] Generating {component['type']}...")
        
        code = generate_component_code(client, component)
        if code:
            write_component_files(args.output_dir, component['type'], code)
            generated_components.append(component)
            print(f"    ✓ Generated {component['type']}")
        else:
            print(f"    ✗ Failed to generate {component['type']}")
        
        # Small delay to avoid rate limits
        import time
        time.sleep(2)
    
    # Generate app component
    print("\n[4/4] Generating app component...")
    generate_app_component(generated_components, args.output_dir)
    print("  ✓ Generated app.component")
    
    print(f"\n--- Generation Complete ---")
    print(f"Angular project created at: {args.output_dir}/")
    print(f"Components generated: {len(generated_components)}/{len(components)}")
    print(f"\nTo run the app:")
    print(f"  cd {args.output_dir}")
    print(f"  npm install")
    print(f"  ng serve")
    print(f"\nThen open http://localhost:4200")


if __name__ == "__main__":
    main()