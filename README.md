# Web Migration Pipeline

A tool for analyzing web pages and preparing them for CMS migration using AI-powered component detection.

## Overview

This pipeline:
1. **Captures** a source webpage (screenshot + HTML)
2. **Analyzes** the page to identify distinct components using vision AI
3. **Maps** components to a target component taxonomy
4. **Extracts** content and transforms it to the target schema
5. **Generates** output in the target format
6. **Validates** the output against the source

## Setup

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install anthropic playwright python-dotenv

# Install browser for Playwright
playwright install chromium

# Create .env file with your API key
echo 'ANTHROPIC_API_KEY=your-key-here' > .env
```

## Usage

### Step 1: Capture a page

```bash
python capture.py "<target-url>"
```

**Note:** Include the full URL with any query parameters—some sites route differently based on campaign params or other query string values.

This creates a `captures/` directory with:
- `screenshot.png` - Full-page screenshot
- `page.html` - Raw HTML
- `metadata.json` - Capture metadata and basic metrics

### Step 2: Analyze components

```bash
python analyze.py
```

(Coming next)

## Project Structure

```
migration-pipeline/
├── capture.py          # Page capture script
├── analyze.py          # Component analysis (coming)
├── extract.py          # Content extraction (coming)
├── generate.py         # Output generation (coming)
├── validate.py         # Visual comparison (coming)
├── components/         # Target component definitions
├── captures/           # Captured page data
└── output/             # Generated output
```

## Design Principles

- **Site-agnostic**: Works with any URL, no hardcoded site-specific logic
- **Transparent**: Every AI decision is logged with reasoning
- **Iterative**: Human-in-the-loop for new component types
- **Validated**: Visual comparison catches regressions