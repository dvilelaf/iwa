#!/usr/bin/env python3
"""Lint JavaScript files for malformed HTML in template strings.

Detects common mistakes like:
- `< option` instead of `<option`
- `</option >` instead of `</option>`
- `< div` instead of `<div`
- etc.
"""

import re
import sys
from pathlib import Path

# Patterns that indicate malformed HTML tags
# Match: < tag or </tag > (spaces inside angle brackets)
MALFORMED_PATTERNS = [
    (r"<\s+(\w+)", "Opening tag with space after '<'"),
    (r"</\s+(\w+)", "Closing tag with space after '</'"),
    (r"<(\w+)\s*>", None),  # Valid - skip
    (r"</(\w+)\s+>", "Closing tag with space before '>'"),
]

# Common HTML tags to check (avoid false positives with comparison operators)
HTML_TAGS = {
    "option", "select", "div", "span", "button", "input", "form",
    "table", "tr", "td", "th", "thead", "tbody", "a", "p", "h1", "h2",
    "h3", "h4", "h5", "h6", "ul", "ol", "li", "label", "img", "svg",
    "path", "polyline", "circle", "rect", "text", "section", "article",
    "header", "footer", "nav", "main", "aside",
}


def check_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Check a single file for malformed HTML patterns.

    Returns list of (line_number, line_content, error_message).
    """
    errors = []
    content = filepath.read_text()
    lines = content.split("\n")

    for line_num, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("//"):
            continue

        # Check for `< tag` pattern (space after <)
        match = re.search(r"<\s+([a-zA-Z]\w*)", line)
        if match:
            tag = match.group(1).lower()
            if tag in HTML_TAGS:
                errors.append((
                    line_num,
                    line.strip()[:80],
                    f"Malformed opening tag: '< {tag}' should be '<{tag}'"
                ))

        # Check for `</tag >` pattern (space before >)
        match = re.search(r"</([a-zA-Z]\w*)\s+>", line)
        if match:
            tag = match.group(1).lower()
            if tag in HTML_TAGS:
                errors.append((
                    line_num,
                    line.strip()[:80],
                    f"Malformed closing tag: '</{tag} >' should be '</{tag}>'"
                ))

        # Check for `</ tag>` pattern (space after </)
        match = re.search(r"</\s+([a-zA-Z]\w*)", line)
        if match:
            tag = match.group(1).lower()
            if tag in HTML_TAGS:
                errors.append((
                    line_num,
                    line.strip()[:80],
                    f"Malformed closing tag: '</ {tag}' should be '</{tag}'"
                ))

    return errors


def main():
    """Run the linter on JavaScript files."""
    # Get JS files to check
    js_files = list(Path("src").rglob("*.js"))

    if not js_files:
        print("No JavaScript files found in src/")
        return 0

    total_errors = 0

    for filepath in js_files:
        errors = check_file(filepath)
        if errors:
            print(f"\n{filepath}:")
            for line_num, line_content, message in errors:
                print(f"  Line {line_num}: {message}")
                print(f"    {line_content}")
                total_errors += 1

    if total_errors > 0:
        print(f"\n❌ Found {total_errors} malformed HTML tag(s)")
        return 1
    else:
        print(f"✅ Checked {len(js_files)} JavaScript file(s) - no malformed HTML tags found")
        return 0


if __name__ == "__main__":
    sys.exit(main())
