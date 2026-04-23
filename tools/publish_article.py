#!/usr/bin/env python3
"""
Automate article publication workflow.

When an article (e.g. L6) is published, this script updates:
1. Internal wiki links in the article (add prefixes)
2. French glossary (merge new terms)
3. English glossary (merge new terms)
4. Backlinks in existing articles ("à venir" → wiki links)
5. INDEX.md (status → ✅ Publié)
6. MOC_Articles_Blog.md (status + URL)

Usage:
    python tools/publish_article.py L6           # Dry-run (all steps)
    python tools/publish_article.py L6 --apply   # Apply all changes
    python tools/publish_article.py L6 --apply --phase prep  # Move + split only
    python tools/publish_article.py L6 --apply --phase fr    # FR steps only
    python tools/publish_article.py L6 --apply --phase en    # EN steps only
    python tools/publish_article.py --generate-index  # Generate publishable INDEX
    python tools/publish_article.py --fix-glossary-titles          # Dry-run
    python tools/publish_article.py --fix-glossary-titles --apply  # Apply fixes
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

ARTICLES_DIR = Path(
    "D:/Romain/Articles/Publications/roomi-fields.com/Articles/"
)
ARTICLES_EN_DIR = ARTICLES_DIR / "_en"
BLOG_DIR = Path(
    "D:/Romain/Articles/Projets/Ontologie musicale/40_OUTPUT/Blog/"
)
INDEX_PATH = BLOG_DIR / "INDEX.md"
MOC_PATH = Path(
    "D:/Romain/Articles/Projets/Ontologie musicale/40_OUTPUT/"
    "MOC_Articles_Blog.md"
)

GLOSSARY_FR_PATH = ARTICLES_DIR / "Glossaire.md"
GLOSSARY_EN_PATH = ARTICLES_EN_DIR / "Glossaire.md"
TIKZ_ASSETS_DIR = Path(
    "D:/Romain/Articles/_Assets/Illustrations/tikz"
)

def build_link_renames() -> dict:
    """Build the link rename mapping dynamically from existing article files.

    Scans Articles/ for files named PREFIX_Title.md (e.g. L5_SOS.md)
    and creates mapping: "Title" → "PREFIX_Title"
    so that [[Title]] can be replaced by [[PREFIX_Title]].
    """
    renames = {}
    if not ARTICLES_DIR.exists():
        return renames
    for f in ARTICLES_DIR.iterdir():
        if not f.is_file() or f.suffix != ".md" or f.name == "Glossaire.md":
            continue
        stem = f.stem  # e.g. "L5_Les trois sémantiques..."
        # Match PREFIX_Title pattern (e.g. I1_xxx, L5_xxx, M2_xxx)
        m = re.match(r"^([A-Z]\d+)_(.+)$", stem)
        if m:
            short_title = m.group(2)  # "Les trois sémantiques..."
            renames[short_title] = stem  # → "L5_Les trois sémantiques..."
    return renames


LINK_RENAMES = build_link_renames()

# Colors for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ─── Parsers ─────────────────────────────────────────────────────────────────


def parse_frontmatter(article_path: Path) -> dict:
    """Parse YAML frontmatter from an article (simple split on ---)."""
    text = article_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    for line in parts[1].strip().splitlines():
        if ":" in line and not line.startswith("  "):
            key, _, value = line.partition(":")
            value = value.strip().strip('"').strip("'")
            fm[key.strip()] = value
    return fm


def find_article_by_prefix(prefix: str) -> tuple:
    """Find FR and EN article files by prefix (e.g. 'L6').

    Searches Articles/ first, then falls back to Blog/.
    Returns (fr_path, en_path) or (None, None) if not found.
    """
    fr_path = None
    en_path = None

    # Search Articles/ first
    for f in ARTICLES_DIR.iterdir():
        if f.is_file() and f.name.startswith(prefix + "_") and f.suffix == ".md":
            fr_path = f
            break

    # Fallback: search Blog/
    if not fr_path:
        for f in BLOG_DIR.iterdir():
            if f.is_file() and f.name.startswith(prefix + "_") and f.suffix == ".md":
                fr_path = f
                break

    if fr_path:
        if fr_path.parent == ARTICLES_DIR:
            en_candidate = ARTICLES_EN_DIR / fr_path.name
        else:
            en_candidate = BLOG_DIR / "_en" / fr_path.name
        if en_candidate.exists():
            en_path = en_candidate

    return fr_path, en_path


def parse_glossary(article_path: Path) -> list:
    """Parse the ## Glossaire / ## Glossary section of an article.

    Returns list of dicts: [{"term": str, "definition": str}, ...]
    """
    text = article_path.read_text(encoding="utf-8")
    terms = []

    # Find glossary section
    glossary_match = re.search(
        r"^## (?:Glossaire|Glossary)\s*$", text, re.MULTILINE
    )
    if not glossary_match:
        return terms

    # Get content from glossary header to next section (## or ---)
    rest = text[glossary_match.end() :]
    section_end = re.search(r"^(?:---|## )", rest, re.MULTILINE)
    if section_end:
        glossary_text = rest[: section_end.start()]
    else:
        glossary_text = rest

    # Parse entries: - **Term** : definition  OR  - **Term**: definition
    for m in re.finditer(
        r"^-\s+\*\*(.+?)\*\*\s*:\s*(.+?)(?=\n-\s+\*\*|\n\n|\Z)",
        glossary_text,
        re.MULTILINE | re.DOTALL,
    ):
        term = m.group(1).strip()
        definition = m.group(2).strip()
        # Clean up multi-line definitions
        definition = re.sub(r"\n\s*", " ", definition)
        terms.append({"term": term, "definition": definition})

    return terms


def get_all_published_articles() -> list:
    """Get all published .md article files (FR and EN), excluding Glossaire."""
    articles = []
    for d in [ARTICLES_DIR, ARTICLES_EN_DIR]:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if (
                f.is_file()
                and f.suffix == ".md"
                and f.name != "Glossaire.md"
            ):
                articles.append(f)
    return articles


# ─── Updaters ────────────────────────────────────────────────────────────────


def get_published_ids() -> set:
    """Return set of article IDs that exist in Articles/ (i.e. are published)."""
    ids = set()
    if not ARTICLES_DIR.exists():
        return ids
    for f in ARTICLES_DIR.iterdir():
        if f.is_file() and f.suffix == ".md" and f.name != "Glossaire.md":
            m = re.match(r"^([A-Z]\d+)_", f.stem)
            if m:
                ids.add(m.group(1))
    return ids


def sanitize_forward_links(
    article_path: Path, published_ids: set, dry_run: bool
) -> list:
    """Replace wiki links to unpublished articles with '(à venir)' text.

    Catches patterns like:
      *Prochain article : [[L7_...|Title]]...*
      *Next article: [[L7_...|Title]]...*
    and reverts them to:
      *Prochain article : Title (à venir)...*
    """
    text = article_path.read_text(encoding="utf-8")
    changes = []
    new_text = text

    # Detect language
    is_en = "_en" in str(article_path.parent)

    # Find all wiki links [[PREFIX_...|display]] or [[PREFIX_...]]
    for m in re.finditer(
        r"\[\[([A-Z]\d+)_([^\]|]+)(?:\|([^\]]+))?\]\]", new_text
    ):
        link_id = m.group(1)
        if link_id not in published_ids:
            full_match = m.group(0)
            display = m.group(3) or m.group(2)

            # Check if this is in a "Prochain article" / "Next article" line
            # Get the line containing this match
            line_start = new_text.rfind("\n", 0, m.start()) + 1
            line_end = new_text.find("\n", m.end())
            if line_end == -1:
                line_end = len(new_text)
            line = new_text[line_start:line_end]

            if is_en:
                coming = "(coming soon)"
            else:
                coming = "(à venir)"

            if re.search(
                r"prochain article|next article|article suivant",
                line,
                re.IGNORECASE,
            ):
                # Replace the wiki link with "Title (à venir)"
                replacement = f"{display} {coming}"
                changes.append(f"  {full_match} → {replacement}")
                new_text = new_text.replace(full_match, replacement, 1)
            else:
                # In body text: just remove the wiki link syntax, keep display
                changes.append(
                    f"  {full_match} → {display} "
                    f"[link removed: {link_id} not published]"
                )

    if changes and not dry_run:
        article_path.write_text(new_text, encoding="utf-8")

    return changes


PRESERVE_FIELDS = ("slug", "wordpress_url", "wordpress_id")


def _ask_confirm(message: str, title: str = "Publication — Confirmer") -> bool:
    """Show a Yes/No dialog (Windows MessageBox) or console fallback."""
    try:
        import ctypes
        MB_YESNO = 0x04
        MB_ICONQUESTION = 0x20
        IDYES = 6
        result = ctypes.windll.user32.MessageBoxW(
            0, message, title, MB_YESNO | MB_ICONQUESTION
        )
        return result == IDYES
    except (ImportError, AttributeError):
        # Fallback for WSL / Linux
        print(message)
        answer = input("(o/N) ").strip().lower()
        return answer in ("o", "oui", "y", "yes")


def _merge_frontmatter_fields(article_path: Path, fields: dict):
    """Ensure frontmatter fields exist with a non-empty value.

    For each key in `fields`: if the key is missing or empty in the
    article, write the value from `fields`. Existing non-empty values
    in the article take priority.
    """
    text = article_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return

    parts = text.split("---", 2)
    if len(parts) < 3:
        return

    fm_text = parts[1]
    existing_fm = parse_frontmatter(article_path)
    changed = False

    for key, value in fields.items():
        if not value:
            continue
        existing_val = existing_fm.get(key, "").strip()
        if existing_val:
            # Article already has a non-empty value — keep it
            continue
        # Key missing or empty — inject preserved value
        pat = re.compile(rf"^{re.escape(key)}\s*:.*$", re.MULTILINE)
        if pat.search(fm_text):
            # Key exists but empty — replace the line
            fm_text = pat.sub(f"{key}: {value}", fm_text)
        else:
            # Key missing — add it
            fm_text = fm_text.rstrip() + f"\n{key}: {value}\n"
        changed = True

    if changed:
        new_text = f"---{fm_text}---{parts[2]}"
        article_path.write_text(new_text, encoding="utf-8")


def _move_one(src: Path, dest_dir: Path, dry_run: bool) -> tuple[Path, list]:
    """Move one article file, handling overwrite with field preservation.

    Returns (new_path, changes). If user cancels, new_path == src.
    """
    dest = dest_dir / src.name
    changes = []

    if not dest.exists():
        changes.append(f"  [move] {src.name}")
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        return dest, changes

    # Destination exists — collect fields from BOTH versions (best of each)
    dest_fm = parse_frontmatter(dest)
    src_fm = parse_frontmatter(src)
    preserve = {}
    for k in PRESERVE_FIELDS:
        # Prefer non-empty value from either version
        val = dest_fm.get(k, "").strip() or src_fm.get(k, "").strip()
        if val:
            preserve[k] = val

    if dry_run:
        changes.append(
            f"  {YELLOW}⚠ {dest.name} existe déjà — sera écrasé{RESET}"
        )
        if preserve:
            changes.append(
                f"    Préservé : {', '.join(f'{k}={v}' for k, v in preserve.items())}"
            )
        return dest, changes

    # Confirmation dialog
    msg = f"{dest.name} existe déjà dans {dest_dir.name}/\n\n"
    if preserve:
        msg += "Champs WordPress préservés :\n"
        for k, v in preserve.items():
            msg += f"  • {k}: {v}\n"
        msg += "\nÉcraser avec la version de Blog/ ?"
    else:
        msg += "Écraser avec la version de Blog/ ?"

    if not _ask_confirm(msg):
        changes.append(f"  {RED}Annulé par l'utilisateur{RESET}")
        return src, changes

    shutil.move(str(src), str(dest))
    if preserve:
        _merge_frontmatter_fields(dest, preserve)
        changes.append(
            f"  [overwrite] {src.name} (préservé : {', '.join(preserve.keys())})"
        )
    else:
        changes.append(f"  [overwrite] {src.name}")

    return dest, changes


def move_article(
    fr_path: Path, en_path: Path | None, dry_run: bool
) -> tuple[Path, Path | None, list]:
    """Move article from Blog/ to Articles/. Returns (new_fr, new_en, changes)."""
    changes = []

    if fr_path.parent == ARTICLES_DIR:
        # Check if a newer version exists in Blog/
        blog_version = BLOG_DIR / fr_path.name
        if not blog_version.exists():
            changes.append("  (article already in Articles/)")
            return fr_path, en_path, changes
        # Blog/ has a newer version — use it as source
        fr_path, fr_changes = _move_one(blog_version, ARTICLES_DIR, dry_run)
        changes.extend(fr_changes)
        if fr_path == blog_version:  # user cancelled
            fr_path = ARTICLES_DIR / blog_version.name  # keep existing
            return fr_path, en_path, changes
        # Also check EN in Blog/
        blog_en = BLOG_DIR / "_en" / fr_path.name
        if blog_en.exists():
            new_en, en_changes = _move_one(blog_en, ARTICLES_EN_DIR, dry_run)
            changes.extend(en_changes)
            en_path = new_en if new_en != blog_en else en_path
        return fr_path, en_path, changes

    fr_path, fr_changes = _move_one(fr_path, ARTICLES_DIR, dry_run)
    changes.extend(fr_changes)

    # If user cancelled FR move, stop here
    if fr_path.parent != ARTICLES_DIR:
        return fr_path, en_path, changes

    new_en = en_path
    if en_path and en_path.parent != ARTICLES_EN_DIR:
        new_en, en_changes = _move_one(en_path, ARTICLES_EN_DIR, dry_run)
        changes.extend(en_changes)

    return fr_path, new_en, changes


def split_title_colon(article_path: Path, dry_run: bool) -> list:
    """Split '# Title : Subtitle' into '# Title' + '## Subtitle'."""
    text = article_path.read_text(encoding="utf-8")
    changes = []

    # Match first H1 with " : " (espace-colon-espace)
    m = re.search(r"^(# .+?)\s*:\s*(.+)$", text, re.MULTILINE)
    if m:
        old = m.group(0)
        title = m.group(1).rstrip()
        subtitle = m.group(2).strip()
        # Capitalize subtitle
        subtitle = subtitle[0].upper() + subtitle[1:] if subtitle else subtitle
        new = f"{title}\n\n## {subtitle}"
        changes.append(f"  '{old}' → '{title}' + '## {subtitle}'")
        text = text.replace(old, new, 1)
        if not dry_run:
            article_path.write_text(text, encoding="utf-8")

    return changes


def fix_glossary_display_names(
    glossary_path: Path, dry_run: bool
) -> list:
    """Fix wiki link display names in glossary to show just the prefix (e.g. L9)."""
    if not glossary_path.exists():
        return [f"  {RED}Glossary not found: {glossary_path}{RESET}"]

    text = glossary_path.read_text(encoding="utf-8")
    changes = []

    def fix_link(m):
        stem = m.group(1)
        current_display = m.group(2)  # None if bare [[stem]]

        prefix_match = re.match(r"^([A-Z]\d+)_", stem)
        if not prefix_match:
            return m.group(0)

        prefix = prefix_match.group(1)

        # Already correct: display is just the prefix
        if current_display == prefix:
            return m.group(0)

        new_link = f"[[{stem}|{prefix}]]"
        changes.append(
            f"  {m.group(0)[:60]} → [[...|{prefix}]]"
        )
        return new_link

    new_text = re.sub(
        r"\[\[([A-Z]\d+_[^\]|]+?)(?:\|([^\]]+))?\]\]",
        fix_link,
        text,
    )

    if changes and not dry_run:
        glossary_path.write_text(new_text, encoding="utf-8")

    return changes


def update_article_links(
    article_path: Path, link_renames: dict, dry_run: bool
) -> list:
    """Replace wiki links without prefixes by prefixed versions.

    E.g. [[Les trois sémantiques...|...]] → [[L5_Les trois sémantiques...|...]]

    Returns list of changes made.
    """
    text = article_path.read_text(encoding="utf-8")
    changes = []

    new_text = text
    for old_name, new_name in link_renames.items():
        # Skip if old_name == new_name (already prefixed)
        if old_name == new_name:
            continue

        # Match [[old_name]] or [[old_name|display]]
        # But NOT [[PREFIX_old_name...]] (already has prefix)
        pattern = re.compile(
            r"\[\["
            + re.escape(old_name)
            + r"(\|[^\]]+)?\]\]"
        )

        for m in pattern.finditer(new_text):
            full_match = m.group(0)
            display_part = m.group(1) or ""
            replacement = f"[[{new_name}{display_part}]]"
            if full_match != replacement:
                changes.append(
                    f"  {full_match} → {replacement}"
                )

        new_text = pattern.sub(
            lambda m: f"[[{new_name}{m.group(1) or ''}]]", new_text
        )

    if changes and not dry_run:
        article_path.write_text(new_text, encoding="utf-8")

    return changes


def ensure_index_link(article_path: Path, dry_run: bool) -> list:
    """Ensure article ends with a link back to the INDEX.

    Adds '[[INDEX|← Retour à l'index]]' (FR) or '[[INDEX|← Back to index]]' (EN)
    at the end if not already present.
    Returns list of changes.
    """
    text = article_path.read_text(encoding="utf-8")
    changes = []

    is_en = "_en" in str(article_path.parent)
    if is_en:
        link_text = "[[INDEX|← Back to index]]"
    else:
        link_text = "[[INDEX|← Retour à l'index]]"

    # Check if link already exists
    if "[[INDEX|" in text:
        return changes

    # Add link at the end
    text = text.rstrip() + f"\n\n---\n\n{link_text}\n"
    changes.append(f"  + {link_text}")

    if not dry_run:
        article_path.write_text(text, encoding="utf-8")

    return changes


def convert_tikz_blocks(article_path: Path, dry_run: bool) -> list:
    """Convert ```tikz code blocks to PNG images.

    Extracts TikZ blocks, compiles via pdflatex, converts to PNG
    via pdftoppm, saves to _Assets/Illustrations/tikz/, and replaces
    each block with an Obsidian image embed ![[filename.png]].

    Returns list of changes.
    """
    text = article_path.read_text(encoding="utf-8")
    changes = []

    # Extract article ID for naming
    m = re.match(r"^([A-Z]\d+)_", article_path.stem)
    if not m:
        return changes
    article_id = m.group(1)

    # Find all TikZ fenced code blocks (3+ backticks)
    pattern = re.compile(r"(`{3,})tikz\s*\n([\s\S]*?)\1")
    matches = list(pattern.finditer(text))

    if not matches:
        return changes

    # Check tool availability
    if not dry_run:
        if not shutil.which("pdflatex"):
            return [f"  {RED}pdflatex non trouvé — TikZ ignoré{RESET}"]
        if not shutil.which("pdftoppm"):
            return [f"  {RED}pdftoppm non trouvé — TikZ ignoré{RESET}"]
        TIKZ_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Process each block (collect replacements, apply in reverse order)
    replacements = []
    for fig_num, match in enumerate(matches, 1):
        tikz_code = match.group(2).strip()
        png_name = f"{article_id}_fig{fig_num}.png"
        png_path = TIKZ_ASSETS_DIR / png_name

        if dry_run:
            changes.append(f"  fig{fig_num} → {png_name}")
            replacements.append(
                (match.start(), match.end(), f"![[{png_name}]]")
            )
            continue

        success = _compile_tikz(tikz_code, png_path)
        if success:
            changes.append(f"  fig{fig_num} → {png_name}")
            replacements.append(
                (match.start(), match.end(), f"![[{png_name}]]")
            )
        else:
            changes.append(
                f"  {RED}fig{fig_num}: erreur compilation{RESET}"
            )

    # Apply replacements in reverse order to preserve positions
    if not dry_run and replacements:
        for start, end, replacement in reversed(replacements):
            text = text[:start] + replacement + text[end:]
        article_path.write_text(text, encoding="utf-8")

    return changes


def _compile_tikz(tikz_code: str, output_png: Path) -> bool:
    """Compile TikZ code to PNG via pdflatex + pdftoppm.

    Returns True on success, False on failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / "figure.tex"
        pdf_path = Path(tmpdir) / "figure.pdf"

        # Wrap in standalone documentclass if needed
        if "\\documentclass" not in tikz_code:
            full_tex = (
                "\\documentclass[border=10pt]{standalone}\n" + tikz_code
            )
        else:
            full_tex = tikz_code

        tex_path.write_text(full_tex, encoding="utf-8")

        # Compile to PDF
        try:
            subprocess.run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-output-directory",
                    str(tmpdir),
                    str(tex_path),
                ],
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False

        if not pdf_path.exists():
            return False

        # Convert PDF to PNG at 300 DPI
        png_prefix = Path(tmpdir) / "output"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    "300",
                    "-singlefile",
                    str(pdf_path),
                    str(png_prefix),
                ],
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False

        png_generated = Path(tmpdir) / "output.png"
        if not png_generated.exists():
            return False

        # Copy to final destination
        shutil.copy2(str(png_generated), str(output_png))
        return True


def _section_letter(term: str) -> str:
    """Determine the alphabetical section letter for a glossary term."""
    ch = term[0].upper()
    if ch.isascii() and ch.isalpha():
        return ch
    if ch == "Σ":
        return "S"
    if ch == "`":
        for c in term:
            if c.isalpha():
                return c.upper()
    return "A"


def regenerate_glossary(
    glossary_path: Path,
    articles_dir: Path,
    is_en: bool,
    dry_run: bool = True,
) -> list:
    """Regenerate the entire glossary from all published articles.

    Scans all articles, collects glossary terms, and rebuilds the glossary
    body while preserving the existing frontmatter and intro.
    Terms appearing in multiple articles get multiple → Voir/See links.
    Returns list of changes.
    """
    see_prefix = "See" if is_en else "Voir"

    # Collect all terms from all articles
    # terms_map: {term_lower: {term, definition, sources: [article_id]}}
    terms_map = {}
    article_terms_map = {}  # {article_id: [term_names]}

    for f in sorted(articles_dir.iterdir()):
        if not f.is_file() or f.suffix != ".md" or f.name == "Glossaire.md":
            continue
        # Skip Obsidian duplicates ("File 1.md", "File 2.md")
        if re.search(r" \d+$", f.stem):
            continue
        m = re.match(r"^([A-Z]\d+)_", f.stem)
        if not m:
            continue
        article_id = m.group(1)
        article_stem = f.stem

        terms = parse_glossary(f)
        if not terms:
            continue

        article_terms_map[article_id] = []
        for entry in terms:
            term = entry["term"]
            definition = entry["definition"]
            key = term.lower()

            if key not in terms_map:
                terms_map[key] = {
                    "term": term,
                    "definition": definition,
                    "sources": [],
                }
            # Add this article as source (avoid duplicates)
            link = f"[[{article_stem}|{article_id}]]"
            if link not in terms_map[key]["sources"]:
                terms_map[key]["sources"].append(link)
            article_terms_map[article_id].append(term)

    # Read existing glossary to preserve frontmatter + intro
    if not glossary_path.exists():
        return [f"  {RED}Glossary not found: {glossary_path}{RESET}"]

    text = glossary_path.read_text(encoding="utf-8")

    # Extract frontmatter
    fm_match = re.match(r"^---\n([\s\S]*?)\n---", text)
    if fm_match:
        frontmatter = f"---\n{fm_match.group(1)}\n---"
        rest = text[fm_match.end():]
    else:
        frontmatter = ""
        rest = text

    # Extract intro (everything before first ## A-Z section)
    intro_match = re.search(r"^## [A-Z]\s*$", rest, re.MULTILINE)
    if intro_match:
        intro = rest[:intro_match.start()]
    else:
        intro = "\n"

    # Build glossary body sorted alphabetically
    sections = {}
    for key in sorted(terms_map.keys()):
        entry = terms_map[key]
        letter = _section_letter(entry["term"])
        if letter not in sections:
            sections[letter] = []
        see_links = ", ".join(entry["sources"])
        sections[letter].append(
            f"**{entry['term']}**\n"
            f"{entry['definition']}\n"
            f"→ {see_prefix} {see_links}"
        )

    body_lines = []
    for letter in sorted(sections.keys()):
        body_lines.append(f"## {letter}")
        body_lines.append("")
        for entry_text in sections[letter]:
            body_lines.append(entry_text)
            body_lines.append("")
        body_lines.append("---")
        body_lines.append("")

    new_body = "\n".join(body_lines)
    new_text = f"{frontmatter}{intro}{new_body}"

    # Count changes
    old_term_count = len(re.findall(r"^\*\*", text, re.MULTILINE))
    new_term_count = len(terms_map)
    changes = [f"  {new_term_count} termes, {len(article_terms_map)} articles"]

    if not dry_run:
        glossary_path.write_text(new_text, encoding="utf-8")

    return changes


def update_backlinks(
    articles_dir: Path,
    article_id: str,
    article_filename: str,
    title_fr: str,
    title_en: str,
    dry_run: bool = True,
) -> list:
    """Search published articles for "à venir"/"coming soon" references.

    Uses two strategies:
    1. Match by exact title (title_fr / title_en)
    2. Scan all "à venir"/"coming soon" lines and suggest matches

    Replaces them with active wiki links.
    Returns list of changes.
    """
    changes = []
    article_stem = article_filename.replace(".md", "")

    dirs_to_scan = [articles_dir]
    en_dir = articles_dir / "_en"
    if en_dir.exists():
        dirs_to_scan.append(en_dir)

    for scan_dir in dirs_to_scan:
        is_en = "_en" in str(scan_dir)
        for f in sorted(scan_dir.iterdir()):
            if not f.is_file() or f.suffix != ".md" or f.name == "Glossaire.md":
                continue
            # Don't modify the article being published
            if f.name.startswith(article_id + "_"):
                continue

            text = f.read_text(encoding="utf-8")
            new_text = text
            file_changes = []

            if is_en:
                # English: *Next article: TITLE (coming soon)...*
                # Use generic capture: any text before (coming soon)
                pattern = re.compile(
                    r"(\*Next article\s*:\s*)"
                    r"(.+?)"
                    r"\s*\(coming soon\)"
                    r"(.*?)\*",
                    re.IGNORECASE,
                )
                for m in pattern.finditer(new_text):
                    captured_title = m.group(2).strip()
                    old = m.group(0)
                    suffix = m.group(3).strip()
                    if suffix and suffix.startswith("—"):
                        suffix = " " + suffix
                    elif suffix:
                        suffix = " — " + suffix
                    new = (
                        f"*Next article: "
                        f"[[{article_stem}|{captured_title}]]"
                        f"{suffix}*"
                    )
                    file_changes.append(f"  {old}\n    → {new}")
                    new_text = new_text.replace(old, new)

                # Bullet: - **Next article**: TITLE (coming soon)...
                pattern2 = re.compile(
                    r"(-\s+\*\*Next article\*\*\s*:\s*)"
                    r"(.+?)"
                    r"\s*\(coming soon\)"
                    r"(.*?)$",
                    re.MULTILINE | re.IGNORECASE,
                )
                for m in pattern2.finditer(new_text):
                    captured_title = m.group(2).strip()
                    old = m.group(0)
                    suffix = m.group(3).strip()
                    if suffix and suffix.startswith("—"):
                        suffix = " " + suffix
                    elif suffix:
                        suffix = " — " + suffix
                    new = (
                        f"-   **Next article**: "
                        f"[[{article_stem}|{captured_title}]]"
                        f"{suffix}"
                    )
                    file_changes.append(f"  {old}\n    → {new}")
                    new_text = new_text.replace(old, new)
            else:
                # French: *Prochain article : TITLE (à venir)...*
                pattern = re.compile(
                    r"(\*Prochain article\s*:\s*)"
                    r"(.+?)"
                    r"\s*\(à venir\)"
                    r"(.*?)\*",
                    re.IGNORECASE,
                )
                for m in pattern.finditer(new_text):
                    captured_title = m.group(2).strip()
                    old = m.group(0)
                    suffix = m.group(3).strip()
                    if suffix and suffix.startswith("—"):
                        suffix = " " + suffix
                    elif suffix:
                        suffix = " — " + suffix
                    new = (
                        f"*Prochain article : "
                        f"[[{article_stem}|{captured_title}]]"
                        f"{suffix}*"
                    )
                    file_changes.append(f"  {old}\n    → {new}")
                    new_text = new_text.replace(old, new)

                # Bullet: - **Article suivant** : TITLE (à venir)...
                pattern2 = re.compile(
                    r"(-\s+\*\*Article suivant\*\*\s*:\s*)"
                    r"(.+?)"
                    r"\s*\(à venir\)"
                    r"(.*?)$",
                    re.MULTILINE | re.IGNORECASE,
                )
                for m in pattern2.finditer(new_text):
                    captured_title = m.group(2).strip()
                    old = m.group(0)
                    suffix = m.group(3).strip()
                    if suffix and suffix.startswith("—"):
                        suffix = " " + suffix
                    elif suffix:
                        suffix = " — " + suffix
                    new = (
                        f"- **Article suivant** : "
                        f"[[{article_stem}|{captured_title}]]"
                        f"{suffix}"
                    )
                    file_changes.append(f"  {old}\n    → {new}")
                    new_text = new_text.replace(old, new)

            if file_changes:
                rel = f"{'_en/' if is_en else ''}{f.name}"
                changes.append(f"  [{rel}]:")
                changes.extend(file_changes)
                if not dry_run:
                    f.write_text(new_text, encoding="utf-8")

    return changes


def update_index(index_path: Path, article_id: str, dry_run: bool) -> list:
    """Update INDEX.md: change article status to ✅ Publié.

    Returns list of changes.
    """
    if not index_path.exists():
        return [f"  {RED}INDEX.md not found: {index_path}{RESET}"]

    text = index_path.read_text(encoding="utf-8")
    changes = []

    # Find line with | ID | and replace any non-published status
    pattern = re.compile(
        rf"^(\|\s*{re.escape(article_id)}\s*\|[^\n]*)"
        rf"(En préparation|📝 Draft|📝 Brouillon)"
        rf"([^\n]*\|)$",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if m:
        old_line = m.group(0)
        new_line = (old_line
                    .replace("En préparation", "✅ Publié")
                    .replace("📝 Draft", "✅ Publié")
                    .replace("📝 Brouillon", "✅ Publié"))
        changes.append(f"  {article_id}: → ✅ Publié")
        text = text.replace(old_line, new_line)

        if not dry_run:
            index_path.write_text(text, encoding="utf-8")
    else:
        changes.append(
            f"  {article_id}: pas de ligne à mettre à jour"
        )

    return changes


def update_moc(
    moc_path: Path,
    article_id: str,
    article_filename: str,
    title_fr: str,
    slug_fr: str,
    slug_en: str,
    dry_run: bool,
) -> list:
    """Update MOC_Articles_Blog.md:
    - Change status to ✅ Publié
    - Add URL row to "URLs publiées" table
    - Update "Prochaines publications suggérées"
    - Update date

    Returns list of changes.
    """
    if not moc_path.exists():
        return [f"  {RED}MOC not found: {moc_path}{RESET}"]

    text = moc_path.read_text(encoding="utf-8")
    changes = []

    # 1. Find article in MOC or insert it
    series_letter = article_id[0]  # e.g. "I" from "I4"

    # Check if article exists in MOC
    has_article = re.search(
        rf"\*\*{re.escape(article_id)}\*\*", text
    )

    if not has_article:
        # Insert article row into the correct series table
        # Strip prefix from title (e.g. "I4) Introduction au MIDI" → "Introduction au MIDI")
        clean_title = re.sub(rf"^{re.escape(article_id)}\)\s*", "", title_fr)
        new_row = (
            f"| **{article_id}** | {clean_title} "
            f"| `{article_filename}` | ✅ Publié |"
        )

        # Find the series section and its table
        series_pattern = re.compile(
            rf"^## Série {re.escape(series_letter)} —.*$",
            re.MULTILINE,
        )
        series_match = series_pattern.search(text)
        if series_match:
            # Find the end of the table (blank line or --- after table rows)
            rest = text[series_match.end():]
            table_rows = list(
                re.finditer(r"^\|[^\n]+\|$", rest, re.MULTILINE)
            )
            if table_rows:
                insert_pos = series_match.end() + table_rows[-1].end()
                text = text[:insert_pos] + "\n" + new_row + text[insert_pos:]
                changes.append(f"  Ajouté {article_id} dans Série {series_letter}")
            else:
                changes.append(f"  {RED}Table non trouvée pour Série {series_letter}{RESET}")
        else:
            changes.append(f"  {RED}Série {series_letter} non trouvée dans MOC{RESET}")
    else:
        # Article exists — update status
        pattern = re.compile(
            rf"^(\|[^\n]*\*\*{re.escape(article_id)}\*\*[^\n]*)"
            rf"(📝 Brouillon|📝 Draft|En préparation)"
            rf"([^\n]*\|)$",
            re.MULTILINE,
        )
        m = pattern.search(text)
        if m:
            old_line = m.group(0)
            old_status = m.group(2)
            new_line = old_line.replace(old_status, "✅ Publié")
            changes.append(f"  Status: {old_status} → ✅ Publié")
            text = text.replace(old_line, new_line)
        else:
            changes.append(f"  {article_id}: déjà publié ou statut inconnu")

    # 2. Add URL row if slugs provided
    if slug_fr or slug_en:
        url_section = re.search(
            r"^## URLs publiées", text, re.MULTILINE
        )
        if url_section:
            # Find last row in URL table
            rest = text[url_section.end() :]
            table_rows = list(re.finditer(r"^\|[^\n]+\|$", rest, re.MULTILINE))
            if table_rows:
                last_row = table_rows[-1]
                insert_pos = url_section.end() + last_row.end()
                new_row = (
                    f"\n| {article_id} | `{slug_fr}` | `{slug_en}` |"
                )
                text = text[:insert_pos] + new_row + text[insert_pos:]
                changes.append(
                    f"  URL: Added {article_id} → {slug_fr}"
                )

    # 3. Update "Prochaines publications suggérées"
    # Remove the line mentioning this article
    pattern_next = re.compile(
        rf"^\d+\.\s+\*\*{re.escape(article_id)}\b.*$",
        re.MULTILINE,
    )
    m_next = pattern_next.search(text)
    if m_next:
        old_line = m_next.group(0)
        text = text.replace(old_line + "\n", "")
        changes.append(
            f"  Removed '{article_id}' from suggested publications"
        )

        # Renumber remaining items
        next_section = re.search(
            r"^## Prochaines publications suggérées",
            text,
            re.MULTILINE,
        )
        if next_section:
            rest = text[next_section.end() :]
            end_section = re.search(r"^---", rest, re.MULTILINE)
            if end_section:
                section_text = rest[: end_section.start()]
                remaining = rest[end_section.start() :]
            else:
                section_text = rest
                remaining = ""

            # Renumber
            counter = 1
            lines = []
            for line in section_text.splitlines():
                m_num = re.match(r"^\d+\.\s+", line)
                if m_num:
                    line = re.sub(r"^\d+\.", f"{counter}.", line)
                    counter += 1
                lines.append(line)
            text = (
                text[: next_section.end()]
                + "\n".join(lines)
                + remaining
            )

    # 4. Update date
    today = date.today().isoformat()
    text = re.sub(
        r"\*Dernière mise à jour : \d{4}-\d{2}-\d{2}\*",
        f"*Dernière mise à jour : {today}*",
        text,
    )
    changes.append(f"  Date: → {today}")

    if not dry_run:
        moc_path.write_text(text, encoding="utf-8")

    return changes


# ─── Generate INDEX ──────────────────────────────────────────────────────────


def generate_index_article(moc_path: Path, output_fr: Path, output_en: Path):
    """Generate rich, publishable INDEX articles from MOC + article data.

    - Only published articles (✅ Publié) are listed with links
    - Reads excerpt from each article's frontmatter for context
    - Provides narrative structure explaining the series architecture
    - Unpublished articles are NOT listed
    """
    if not moc_path.exists():
        print(f"{RED}MOC not found: {moc_path}{RESET}")
        return

    moc_text = moc_path.read_text(encoding="utf-8")

    # Parse URLs table from MOC
    urls = {}
    url_section = re.search(r"^## URLs publiées", moc_text, re.MULTILINE)
    if url_section:
        rest = moc_text[url_section.end() :]
        for m in re.finditer(
            r"^\|\s*(\w+)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|$",
            rest,
            re.MULTILINE,
        ):
            urls[m.group(1)] = {
                "fr": m.group(2),
                "en": m.group(3),
            }

    # Parse articles from MOC tables
    articles_by_series = {}
    current_series = None
    for line in moc_text.splitlines():
        series_match = re.match(r"^## Série (\w+) — (.+)$", line)
        if series_match:
            current_series = series_match.group(1)
            articles_by_series[current_series] = {
                "name": series_match.group(2),
                "articles": [],
            }
            continue

        if current_series and line.startswith("| **"):
            row_match = re.match(
                r"\|\s*\*\*(\w+)\*\*\s*\|\s*(.+?)\s*\|"
                r"\s*`(.+?)`\s*\|\s*(.+?)\s*\|",
                line,
            )
            if row_match:
                aid = row_match.group(1)
                title = row_match.group(2)
                filename = row_match.group(3)
                status = row_match.group(4).strip()
                articles_by_series[current_series]["articles"].append(
                    {
                        "id": aid,
                        "title": title,
                        "filename": filename,
                        "status": status,
                        "urls": urls.get(aid),
                    }
                )

    # Read excerpts, EN titles, and fallback URLs from article files
    excerpts_fr = {}
    excerpts_en = {}
    titles_en = {}
    titles_fr_override = {}
    for series_data in articles_by_series.values():
        for art in series_data["articles"]:
            if "✅" not in art["status"]:
                continue
            # FR
            fr_file = ARTICLES_DIR / art["filename"]
            if fr_file.exists():
                fm = parse_frontmatter(fr_file)
                if fm.get("title"):
                    titles_fr_override[art["id"]] = fm["title"]
                if fm.get("excerpt"):
                    excerpts_fr[art["id"]] = fm["excerpt"]
                elif fm.get("subtitle"):
                    excerpts_fr[art["id"]] = fm["subtitle"]
                # Fallback: read H1 and first paragraph if no frontmatter
                if art["id"] not in excerpts_fr:
                    text = fr_file.read_text(encoding="utf-8")
                    # Find the blockquote after H1 (intro paragraph)
                    bq = re.search(r"^> (.+)$", text, re.MULTILINE)
                    if bq:
                        excerpts_fr[art["id"]] = bq.group(1).strip()
                # Fallback URL from frontmatter if missing from MOC
                if not art.get("urls") and fm.get("wordpress_url"):
                    wp_url = fm["wordpress_url"]
                    slug = wp_url.rstrip("/").split("/")[-1]
                    art["urls"] = {
                        "fr": f"/articles/{slug}/",
                        "en": f"/en/articles/{slug}/",
                    }
                elif not art.get("urls") and fm.get("slug"):
                    art["urls"] = {
                        "fr": f"/articles/{fm['slug']}/",
                        "en": f"/en/articles/{fm['slug']}/",
                    }
            # EN
            en_file = ARTICLES_EN_DIR / art["filename"]
            if en_file.exists():
                fm_en = parse_frontmatter(en_file)
                if fm_en.get("title"):
                    titles_en[art["id"]] = fm_en["title"]
                if fm_en.get("excerpt"):
                    excerpts_en[art["id"]] = fm_en["excerpt"]
                elif fm_en.get("subtitle"):
                    excerpts_en[art["id"]] = fm_en["subtitle"]
                # Fallback: blockquote
                if art["id"] not in excerpts_en:
                    text_en = en_file.read_text(encoding="utf-8")
                    bq = re.search(r"^> (.+)$", text_en, re.MULTILINE)
                    if bq:
                        excerpts_en[art["id"]] = bq.group(1).strip()
                # Override EN URL from EN frontmatter if available
                if art.get("urls") and fm_en.get("wordpress_url"):
                    wp_url_en = fm_en["wordpress_url"]
                    art["urls"]["en"] = "/" + wp_url_en.split(
                        "roomi-fields.com/"
                    )[-1]
                elif art.get("urls") and fm_en.get("slug"):
                    art["urls"]["en"] = (
                        f"/en/articles/{fm_en['slug']}/"
                    )

    # Fallback: use FR excerpt/title for EN when EN article doesn't exist
    for series_data in articles_by_series.values():
        for art in series_data["articles"]:
            aid = art["id"]
            if "✅" not in art["status"]:
                continue
            if aid not in excerpts_en and aid in excerpts_fr:
                excerpts_en[aid] = excerpts_fr[aid]
            if aid not in titles_en and aid in titles_fr_override:
                titles_en[aid] = titles_fr_override[aid]

    # ─── Series descriptions (editorial context) ─────────────────────
    series_intros_fr = {
        "I": (
            "Avant de plonger dans la théorie, posons le décor. "
            "Pourquoi ce projet existe, quels sont ses outils, "
            "et quel problème il cherche à résoudre."
        ),
        "L": (
            "Le socle théorique du projet. "
            "De la hiérarchie de Chomsky aux sémantiques formelles, "
            "ces articles construisent pas à pas les fondations "
            "nécessaires pour comprendre comment fonctionne un langage."
        ),
        "M": (
            "Le pont entre théorie des langages et musique. "
            "Formats, paradigmes, structures hiérarchiques : "
            "comment les concepts formels s'appliquent au son."
        ),
        "B": (
            "Plongée dans les mécanismes du langage BP3 : "
            "probabilités, alphabets, règles de dérivation."
        ),
        "C": (
            "Justification des décisions techniques du projet BP2SC. "
            "Pourquoi ces choix et pas d'autres."
        ),
        "R": (
            "Articles de recherche et formalismes approfondis."
        ),
    }

    series_intros_en = {
        "I": (
            "Before diving into theory, let's set the scene. "
            "Why this project exists, what tools it uses, "
            "and what problem it aims to solve."
        ),
        "L": (
            "The theoretical foundation of the project. "
            "From the Chomsky hierarchy to formal semantics, "
            "these articles build step by step the foundations "
            "needed to understand how a language works."
        ),
        "M": (
            "The bridge between language theory and music. "
            "Formats, paradigms, hierarchical structures: "
            "how formal concepts apply to sound."
        ),
        "B": (
            "A deep dive into BP3 language mechanics: "
            "probabilities, alphabets, derivation rules."
        ),
        "C": (
            "Justification of BP2SC's technical decisions. "
            "Why these choices and not others."
        ),
        "R": (
            "Research articles and in-depth formalisms."
        ),
    }

    series_names_en = {
        "I": "Introduction",
        "L": "Formal Languages",
        "M": "Music",
        "B": "BP3",
        "C": "Design Decisions",
        "R": "Research",
    }

    today = date.today().isoformat()

    # Count published
    total_published = sum(
        1
        for sd in articles_by_series.values()
        for a in sd["articles"]
        if "✅" in a["status"]
    )

    # ─── Preserve existing frontmatter + intro from INDEX files ─────
    def _extract_header(filepath):
        """Extract frontmatter + intro (everything before first ## Série/Series)."""
        if not filepath.exists():
            return ""
        text = filepath.read_text(encoding="utf-8")
        m = re.search(r"^## (?:Série|Series) ", text, re.MULTILINE)
        if m:
            return text[:m.start()]
        return text

    fr_header = _extract_header(output_fr)
    en_header = _extract_header(output_en)

    fr_lines = []
    en_lines = []

    for series_key, series_data in articles_by_series.items():
        published = [
            a
            for a in series_data["articles"]
            if "✅" in a["status"]
        ]
        if not published:
            continue

        # Section header with series label
        fr_lines.append(
            f"## Série {series_key} — {series_data['name']}"
        )
        fr_lines.append("")

        en_name = series_names_en.get(series_key, series_data["name"])
        en_lines.append(f"## Series {series_key} — {en_name}")
        en_lines.append("")

        # Series intro
        intro_fr = series_intros_fr.get(series_key, "")
        intro_en = series_intros_en.get(series_key, "")
        if intro_fr:
            fr_lines.append(intro_fr)
            fr_lines.append("")
        if intro_en:
            en_lines.append(intro_en)
            en_lines.append("")

        # Articles as compact list using wiki links:
        # - **[[STEM|ID) Title]]** : excerpt
        for art in published:
            excerpt = excerpts_fr.get(art["id"], "")
            excerpt_en = excerpts_en.get(art["id"], "")
            fr_title = titles_fr_override.get(
                art["id"], art["title"]
            )
            en_title = titles_en.get(art["id"], art["title"])
            aid = art["id"]
            stem = art["filename"].replace(".md", "")

            # Strip prefix if title already contains it
            prefix_pat = re.compile(rf"^{re.escape(aid)}[)—]\s*")
            fr_title = prefix_pat.sub("", fr_title)
            en_title = prefix_pat.sub("", en_title)

            # FR line — wiki link
            fr_link = f"**[[{stem}|{aid}) {fr_title}]]**"
            if excerpt:
                fr_lines.append(f"- {fr_link} : {excerpt}")
            else:
                fr_lines.append(f"- {fr_link}")

            # EN line — wiki link
            en_link = f"**[[{stem}|{aid}) {en_title}]]**"
            if excerpt_en:
                en_lines.append(f"- {en_link} : {excerpt_en}")
            else:
                en_lines.append(f"- {en_link}")

        fr_lines.extend(["", "---", ""])
        en_lines.extend(["", "---", ""])

    # Reading paths
    # ─── Preserve existing footer from INDEX files ─────────────────
    def _extract_footer(filepath):
        """Extract footer (everything after last --- following article list)."""
        if not filepath.exists():
            return ""
        text = filepath.read_text(encoding="utf-8")
        # Find last "## Série/Series" section, then find content after
        # the last "---" that follows the article sections
        # Look for known footer sections
        for pattern in [
            r"^## Parcours de lecture",
            r"^## Reading Paths",
            r"^## Ressources",
            r"^## Additional Resources",
            r"^\*\d+ articles",
        ]:
            m = re.search(pattern, text, re.MULTILINE)
            if m:
                return text[m.start():]
        return ""

    fr_footer = _extract_footer(output_fr)
    en_footer = _extract_footer(output_en)

    # Update date and article count in footers
    if fr_footer:
        fr_footer = re.sub(
            r"\*\d+ articles publiés — Dernière mise à jour : \d{4}-\d{2}-\d{2}\*",
            f"*{total_published} articles publiés — Dernière mise à jour : {today}*",
            fr_footer,
        )
    if en_footer:
        en_footer = re.sub(
            r"\*\d+ articles published — Last updated: \d{4}-\d{2}-\d{2}\*",
            f"*{total_published} articles published — Last updated: {today}*",
            en_footer,
        )

    # Assemble: header + series sections + footer
    fr_content = fr_header + "\n".join(fr_lines) + "\n"
    en_content = en_header + "\n".join(en_lines) + "\n"

    if fr_footer:
        fr_content += fr_footer
    if en_footer:
        en_content += en_footer

    output_fr.parent.mkdir(parents=True, exist_ok=True)
    output_en.parent.mkdir(parents=True, exist_ok=True)

    output_fr.write_text(fr_content, encoding="utf-8")
    output_en.write_text(en_content, encoding="utf-8")

    # Output suppressed — caller (step 7) prints the summary


# ─── CLI ─────────────────────────────────────────────────────────────────────


def extract_short_title(filename: str, prefix: str) -> str:
    """Extract the short title from a filename.

    E.g. 'L6_SOS.md' → 'SOS'
         'L6_SOS pour les nuls.md' → 'SOS pour les nuls'
    """
    stem = filename.replace(".md", "")
    # Remove prefix like 'L6_'
    if stem.startswith(prefix + "_"):
        return stem[len(prefix) + 1 :]
    return stem


def _step_summary(label: str, changes: list, verbose: bool):
    """Print step result: detailed if verbose, one-line summary otherwise."""
    if not changes:
        print(f"  {label}: -")
        return
    if verbose:
        for c in changes:
            print(c)
    else:
        print(f"  {label}: {len(changes)} changement(s)")


def run_publish(article_id: str, apply: bool, phase: str = "all",
                verbose: bool = False):
    """Run publication steps for an article.

    Args:
        article_id: Article prefix (e.g. L6, M1)
        apply: If True, write changes; if False, dry-run
        phase: Which steps to run:
            - "all": all steps (default, backward compatible)
            - "prep": move Blog/ → Articles/ + split title colon
            - "fr": FR links, glossary, backlinks, INDEX, MOC
            - "en": EN links, glossary, regenerate INDEX
        verbose: If True, print each individual change
    """
    dry_run = not apply

    # Find articles
    fr_path, en_path = find_article_by_prefix(article_id)
    if not fr_path:
        print(f"{RED}Article not found: {article_id}_*.md{RESET}")
        sys.exit(1)

    if phase == "all":
        mode = f"{RED}APPLY{RESET}" if apply else f"{YELLOW}DRY-RUN{RESET}"
        en_label = en_path.name if en_path else f"{YELLOW}non trouvé{RESET}"
        print(f"Publishing {article_id} [{mode}]")
        print(f"  FR: {fr_path.name} | EN: {en_label}")

    # Extract titles
    fr_fm = parse_frontmatter(fr_path)
    title_fr = fr_fm.get("title", extract_short_title(fr_path.name, article_id))
    slug_fr = fr_fm.get("slug", "")

    if en_path:
        en_fm = parse_frontmatter(en_path)
        title_en = en_fm.get("title", title_fr)
        slug_en = en_fm.get("slug", "")
    else:
        title_en = title_fr
        slug_en = ""

    # Compute URL slugs for MOC
    slug_fr_full = f"/articles/{slug_fr}/" if slug_fr else ""
    slug_en_full = f"/en/articles/{slug_en}/" if slug_en else ""

    short_title_fr = extract_short_title(fr_path.name, article_id)

    # ─── Step 0: Move article Blog/ → Articles/ ──────────────────────
    if phase in ("all", "prep"):
        fr_path, en_path, changes = move_article(fr_path, en_path, dry_run)
        _step_summary("0. Move → Articles/", changes, verbose)

    # ─── Step 0b: Split title colon ──────────────────────────────────
    if phase in ("all", "prep"):
        changes_fr = split_title_colon(fr_path, dry_run)
        changes_en = split_title_colon(en_path, dry_run) if en_path else []
        _step_summary("0b. Split colon", changes_fr + changes_en, verbose)

    # ─── Step 1: Update article links ────────────────────────────────
    if phase in ("all", "fr"):
        changes = update_article_links(fr_path, LINK_RENAMES, dry_run)
        _step_summary("1. Links FR", changes, verbose)

    if phase in ("all", "en") and en_path:
        changes = update_article_links(en_path, LINK_RENAMES, dry_run)
        _step_summary("1. Links EN", changes, verbose)

    # ─── Step 1b: Sanitize forward links to unpublished articles ─────
    published_ids = get_published_ids()
    if phase in ("all", "fr"):
        changes = sanitize_forward_links(fr_path, published_ids, dry_run)
        _step_summary("1b. Forward links FR", changes, verbose)

    if phase in ("all", "en") and en_path:
        changes = sanitize_forward_links(en_path, published_ids, dry_run)
        _step_summary("1b. Forward links EN", changes, verbose)

    # ─── Step 1c: Ensure back-to-index link ──────────────────────────
    if phase in ("all", "fr"):
        changes = ensure_index_link(fr_path, dry_run)
        _step_summary("1c. Index link FR", changes, verbose)

    if phase in ("all", "en") and en_path:
        changes = ensure_index_link(en_path, dry_run)
        _step_summary("1c. Index link EN", changes, verbose)

    # ─── Step 2: Regenerate glossary FR ─────────────────────────────────
    if phase in ("all", "fr"):
        changes = regenerate_glossary(
            GLOSSARY_FR_PATH, ARTICLES_DIR, is_en=False, dry_run=dry_run,
        )
        _step_summary("2. Glossaire FR", changes, verbose)

    # ─── Step 3: Regenerate glossary EN ──────────────────────────────────
    if phase in ("all", "en"):
        if ARTICLES_EN_DIR.exists():
            changes = regenerate_glossary(
                GLOSSARY_EN_PATH, ARTICLES_EN_DIR, is_en=True, dry_run=dry_run,
            )
            _step_summary("3. Glossaire EN", changes, verbose)
        else:
            print("  3. Glossaire EN: (pas de dossier _en)")

    # ─── Step 4: Update backlinks ─────────────────────────────────────
    if phase in ("all", "fr"):
        changes = update_backlinks(
            ARTICLES_DIR, article_id, fr_path.name,
            short_title_fr, title_en, dry_run,
        )
        _step_summary("4. Backlinks", changes, verbose)

    # ─── Step 5: Update INDEX.md ──────────────────────────────────────
    if phase in ("all", "fr"):
        changes = update_index(INDEX_PATH, article_id, dry_run)
        _step_summary("5. INDEX.md", changes, verbose)

    # ─── Step 6: Update MOC ───────────────────────────────────────────
    if phase in ("all", "fr"):
        changes = update_moc(
            MOC_PATH, article_id, fr_path.name, title_fr,
            slug_fr_full, slug_en_full, dry_run,
        )
        _step_summary("6. MOC", changes, verbose)

    # ─── Step 7: Regenerate publishable INDEX ──────────────────────────
    if phase in ("all", "en"):
        output_fr = ARTICLES_DIR / "INDEX.md"
        output_en = ARTICLES_EN_DIR / "INDEX.md"
        if dry_run:
            print("  7. INDEX publiable: (dry-run, ignoré)")
        else:
            generate_index_article(MOC_PATH, output_fr, output_en)
            print("  7. INDEX publiable: régénéré")

    # Summary (only when running standalone, not as sub-phase)
    if phase == "all":
        if dry_run:
            print(f"\n{YELLOW}DRY-RUN. Utilisez --apply pour appliquer.{RESET}")
        else:
            print(f"\n{GREEN}✅ Publication {article_id} terminée.{RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="Automate article publication workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s L6              Dry-run: show changes without applying
  %(prog)s L6 --apply      Apply all changes
  %(prog)s --generate-index Generate publishable INDEX articles
        """,
    )
    parser.add_argument(
        "article_id",
        nargs="?",
        help="Article prefix (e.g. L6, M1, C2)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run)",
    )
    parser.add_argument(
        "--generate-index",
        action="store_true",
        help="Generate publishable INDEX articles from MOC",
    )
    parser.add_argument(
        "--phase",
        choices=["all", "prep", "fr", "en"],
        default="all",
        help="Run specific phase: prep (move+split), fr, en (default: all)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Afficher le détail de chaque changement",
    )

    args = parser.parse_args()

    if args.generate_index:
        output_fr = ARTICLES_DIR / "INDEX.md"
        output_en = ARTICLES_EN_DIR / "INDEX.md"
        generate_index_article(MOC_PATH, output_fr, output_en)
        return

    if not args.article_id:
        parser.print_help()
        sys.exit(1)

    # Validate article_id format
    if not re.match(r"^[A-Z]\d+$", args.article_id):
        print(
            f"{RED}Invalid article ID: '{args.article_id}'. "
            f"Expected format: L6, M1, C2, etc.{RESET}"
        )
        sys.exit(1)

    run_publish(args.article_id, args.apply, args.phase, args.verbose)


if __name__ == "__main__":
    main()
