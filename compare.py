#!/usr/bin/env python3
"""
Compare source and generated screenshots visually.

Usage:
    python compare.py [--captures-dir captures]

Requires:
    - Previous captures (screenshot.png and angular-output.png)
    - pip install pillow scikit-image numpy

Outputs:
    - captures/diff.png (visual diff highlighting differences)
    - captures/comparison-report.json (similarity scores and analysis)
"""

import os
import sys
import json
import argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageChops
    import numpy as np
    HAS_IMAGING = True
except ImportError:
    HAS_IMAGING = False

try:
    from skimage.metrics import structural_similarity as ssim
    from skimage import img_as_float
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False


def check_dependencies():
    """Check if required packages are installed."""
    missing = []
    if not HAS_IMAGING:
        missing.append("pillow")
    if not HAS_SKIMAGE:
        missing.append("scikit-image")
    
    if missing:
        print(f"Error: Missing required packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)} numpy")
        sys.exit(1)


def load_and_normalize_images(source_path: str, generated_path: str) -> tuple:
    """
    Load both images and normalize them for comparison.
    
    Returns (source_img, generated_img, source_array, generated_array)
    """
    source = Image.open(source_path).convert('RGB')
    generated = Image.open(generated_path).convert('RGB')
    
    # Get dimensions
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    
    print(f"Source dimensions: {source_w}x{source_h}")
    print(f"Generated dimensions: {generated_w}x{generated_h}")
    
    # For comparison, we'll use the same width and compare corresponding sections
    # Resize generated to match source width if different
    if generated_w != source_w:
        ratio = source_w / generated_w
        new_height = int(generated_h * ratio)
        generated = generated.resize((source_w, new_height), Image.Resampling.LANCZOS)
        print(f"Resized generated to: {source_w}x{new_height}")
    
    return source, generated


def compute_similarity_scores(source: Image, generated: Image) -> dict:
    """
    Compute various similarity metrics between images.
    
    Returns dict with similarity scores.
    """
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    
    # Use the shorter height for comparison
    compare_height = min(source_h, generated_h)
    
    # Crop both to same height for comparison
    source_crop = source.crop((0, 0, source_w, compare_height))
    generated_crop = generated.crop((0, 0, generated_w, compare_height))
    
    # Convert to numpy arrays
    source_array = np.array(source_crop)
    generated_array = np.array(generated_crop)
    
    # Compute SSIM (Structural Similarity Index)
    source_gray = np.mean(source_array, axis=2)
    generated_gray = np.mean(generated_array, axis=2)
    
    ssim_score, ssim_diff = ssim(source_gray, generated_gray, full=True, data_range=255)
    
    # Compute pixel-wise difference
    pixel_diff = np.abs(source_array.astype(float) - generated_array.astype(float))
    mean_pixel_diff = np.mean(pixel_diff)
    max_pixel_diff = np.max(pixel_diff)
    
    # Percentage of pixels within tolerance
    tolerance = 30  # RGB difference threshold
    pixels_within_tolerance = np.mean(np.all(pixel_diff < tolerance, axis=2)) * 100
    
    return {
        "ssim_score": float(ssim_score),
        "ssim_interpretation": interpret_ssim(ssim_score),
        "mean_pixel_difference": float(mean_pixel_diff),
        "max_pixel_difference": float(max_pixel_diff),
        "pixels_within_tolerance_pct": float(pixels_within_tolerance),
        "tolerance_used": tolerance,
        "compared_height": compare_height,
        "source_height": source_h,
        "generated_height": generated_h,
        "height_difference": abs(source_h - generated_h),
        "height_ratio": generated_h / source_h if source_h > 0 else 0,
        "ssim_diff_map": ssim_diff
    }


def interpret_ssim(score: float) -> str:
    """Interpret SSIM score in human terms."""
    if score >= 0.95:
        return "Excellent - nearly identical"
    elif score >= 0.90:
        return "Very good - minor differences"
    elif score >= 0.80:
        return "Good - noticeable but acceptable differences"
    elif score >= 0.70:
        return "Fair - significant differences"
    elif score >= 0.50:
        return "Poor - major differences"
    else:
        return "Very poor - substantially different"


def create_diff_image(source: Image, generated: Image, scores: dict, output_path: str):
    """
    Create a visual diff image showing:
    - Side by side comparison
    - Highlighted differences
    """
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    
    # Use shorter height
    compare_height = min(source_h, generated_h)
    
    # Crop both
    source_crop = source.crop((0, 0, source_w, compare_height))
    generated_crop = generated.crop((0, 0, source_w, compare_height))
    
    # Create difference image
    diff = ImageChops.difference(source_crop, generated_crop)
    
    # Amplify differences for visibility
    diff_array = np.array(diff)
    diff_amplified = np.clip(diff_array * 3, 0, 255).astype(np.uint8)
    diff_img = Image.fromarray(diff_amplified)
    
    # Create side-by-side comparison
    # Layout: [Source] [Generated] [Diff]
    margin = 20
    label_height = 40
    total_width = (source_w * 3) + (margin * 4)
    total_height = compare_height + label_height + (margin * 2)
    
    comparison = Image.new('RGB', (total_width, total_height), color=(30, 30, 30))
    draw = ImageDraw.Draw(comparison)
    
    # Paste images
    x_offset = margin
    comparison.paste(source_crop, (x_offset, label_height + margin))
    draw.text((x_offset, margin // 2), "SOURCE (Original)", fill=(255, 255, 255))
    
    x_offset += source_w + margin
    comparison.paste(generated_crop, (x_offset, label_height + margin))
    draw.text((x_offset, margin // 2), "GENERATED (Angular)", fill=(255, 255, 255))
    
    x_offset += source_w + margin
    comparison.paste(diff_img, (x_offset, label_height + margin))
    draw.text((x_offset, margin // 2), f"DIFF (SSIM: {scores['ssim_score']:.2%})", fill=(255, 255, 255))
    
    comparison.save(output_path)
    print(f"Diff image saved to: {output_path}")


def create_heatmap(source: Image, generated: Image, output_path: str):
    """Create a heatmap showing where differences are concentrated."""
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    compare_height = min(source_h, generated_h)
    
    source_crop = source.crop((0, 0, source_w, compare_height))
    generated_crop = generated.crop((0, 0, source_w, compare_height))
    
    source_array = np.array(source_crop).astype(float)
    generated_array = np.array(generated_crop).astype(float)
    
    # Compute difference magnitude
    diff = np.sqrt(np.sum((source_array - generated_array) ** 2, axis=2))
    
    # Normalize to 0-255
    diff_normalized = (diff / diff.max() * 255).astype(np.uint8)
    
    # Create heatmap (blue = same, red = different)
    heatmap = np.zeros((compare_height, source_w, 3), dtype=np.uint8)
    heatmap[:, :, 0] = diff_normalized  # Red channel = difference
    heatmap[:, :, 2] = 255 - diff_normalized  # Blue channel = similarity
    
    # Overlay on source image
    source_array_uint8 = np.array(source_crop)
    overlay = (source_array_uint8 * 0.5 + heatmap * 0.5).astype(np.uint8)
    
    Image.fromarray(overlay).save(output_path)
    print(f"Heatmap saved to: {output_path}")


def analyze_sections(source: Image, generated: Image, num_sections: int = 5) -> list:
    """
    Analyze similarity by vertical sections of the page.
    
    Returns list of section scores.
    """
    source_w, source_h = source.size
    generated_w, generated_h = generated.size
    compare_height = min(source_h, generated_h)
    
    section_height = compare_height // num_sections
    sections = []
    
    for i in range(num_sections):
        y_start = i * section_height
        y_end = min((i + 1) * section_height, compare_height)
        
        source_section = source.crop((0, y_start, source_w, y_end))
        generated_section = generated.crop((0, y_start, source_w, y_end))
        
        source_array = np.mean(np.array(source_section), axis=2)
        generated_array = np.mean(np.array(generated_section), axis=2)
        
        section_ssim = ssim(source_array, generated_array, data_range=255)
        
        sections.append({
            "section": i + 1,
            "y_range": f"{y_start}-{y_end}",
            "ssim_score": float(section_ssim),
            "interpretation": interpret_ssim(section_ssim)
        })
    
    return sections


def main():
    parser = argparse.ArgumentParser(description="Compare source and generated screenshots")
    parser.add_argument("--captures-dir", default="captures", help="Directory containing screenshots")
    args = parser.parse_args()
    
    check_dependencies()
    
    source_path = os.path.join(args.captures_dir, "screenshot.png")
    generated_path = os.path.join(args.captures_dir, "angular-output.png")
    
    if not os.path.exists(source_path):
        print(f"Error: Source screenshot not found at {source_path}")
        sys.exit(1)
    
    if not os.path.exists(generated_path):
        print(f"Error: Generated screenshot not found at {generated_path}")
        print("Run: ng serve (in angular-app/) and then capture the output")
        sys.exit(1)
    
    print("Loading images...")
    source, generated = load_and_normalize_images(source_path, generated_path)
    
    print("\nComputing similarity scores...")
    scores = compute_similarity_scores(source, generated)
    
    # Remove the diff map from JSON output (it's a large array)
    ssim_diff_map = scores.pop("ssim_diff_map")
    
    print(f"\n--- Comparison Results ---")
    print(f"SSIM Score: {scores['ssim_score']:.2%} ({scores['ssim_interpretation']})")
    print(f"Pixels within tolerance: {scores['pixels_within_tolerance_pct']:.1f}%")
    print(f"Height ratio: {scores['height_ratio']:.2f} (generated/source)")
    
    print("\nAnalyzing sections...")
    sections = analyze_sections(source, generated)
    
    print("\nSection-by-section analysis:")
    for section in sections:
        print(f"  Section {section['section']} ({section['y_range']}): {section['ssim_score']:.2%} - {section['interpretation']}")
    
    print("\nGenerating diff images...")
    create_diff_image(source, generated, scores, os.path.join(args.captures_dir, "diff.png"))
    create_heatmap(source, generated, os.path.join(args.captures_dir, "heatmap.png"))
    
    # Save report
    report = {
        "overall_scores": scores,
        "section_analysis": sections,
        "files": {
            "source": "screenshot.png",
            "generated": "angular-output.png",
            "diff": "diff.png",
            "heatmap": "heatmap.png"
        },
        "pass_threshold": 0.80,
        "passed": scores["ssim_score"] >= 0.80
    }
    
    report_path = os.path.join(args.captures_dir, "comparison-report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_path}")
    
    # Summary
    print(f"\n{'='*50}")
    if report["passed"]:
        print(f"✓ PASSED - Similarity score {scores['ssim_score']:.2%} meets threshold {report['pass_threshold']:.0%}")
    else:
        print(f"✗ FAILED - Similarity score {scores['ssim_score']:.2%} below threshold {report['pass_threshold']:.0%}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()