#!/usr/bin/env python3
"""Split _source.html into one static HTML file per page, across 15 languages.

Each <div id="..." class="page ..." data-title data-description data-slug>
becomes its own `/<slug>/index.html` (English, root) and
`/<lang>/<slug>/index.html` for each translated language.

Translations live in `translations/<lang>.json`. Each file provides translated
page titles, descriptions, UI strings, and optional body-text replacements.

Re-run whenever _source.html or translation files change.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "_source.html"
TRANSLATIONS_DIR = ROOT / "translations"
CANONICAL_BASE = "https://smmpanelinfo.com"
SITE_NAME = "SMM Panel Info"
DEFAULT_LANG = "en"
LANG_SWITCHER_MARKER = "<!-- LANG_SWITCHER -->"
BODIES_SUFFIX = "_bodies.json"


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    html_lang: str
    direction: str = "ltr"


# 15 most widely-spoken world languages.
LANGUAGES: tuple[Language, ...] = (
    Language("en", "English", "en", "ltr"),
    Language("zh", "中文", "zh", "ltr"),
    Language("es", "Español", "es", "ltr"),
    Language("hi", "हिन्दी", "hi", "ltr"),
    Language("ar", "العربية", "ar", "rtl"),
    Language("pt", "Português", "pt", "ltr"),
    Language("bn", "বাংলা", "bn", "ltr"),
    Language("ru", "Русский", "ru", "ltr"),
    Language("ja", "日本語", "ja", "ltr"),
    Language("de", "Deutsch", "de", "ltr"),
    Language("fr", "Français", "fr", "ltr"),
    Language("ko", "한국어", "ko", "ltr"),
    Language("it", "Italiano", "it", "ltr"),
    Language("tr", "Türkçe", "tr", "ltr"),
    Language("id", "Bahasa Indonesia", "id", "ltr"),
)


def read_source() -> str:
    if not SOURCE.exists():
        sys.exit(f"missing source file: {SOURCE}")
    return SOURCE.read_text(encoding="utf-8")


def load_translations() -> dict[str, dict]:
    translations: dict[str, dict] = {}
    if not TRANSLATIONS_DIR.exists():
        return translations
    for path in sorted(TRANSLATIONS_DIR.glob("*.json")):
        if path.name.endswith(BODIES_SUFFIX):
            continue
        code = path.stem
        translations[code] = json.loads(path.read_text(encoding="utf-8"))
    return translations


def load_bodies() -> dict[str, dict[str, str]]:
    """Load per-language page body translations from translations/{lang}_bodies.json."""
    bodies: dict[str, dict[str, str]] = {}
    if not TRANSLATIONS_DIR.exists():
        return bodies
    for path in sorted(TRANSLATIONS_DIR.glob(f"*{BODIES_SUFFIX}")):
        code = path.name[: -len(BODIES_SUFFIX)]
        bodies[code] = json.loads(path.read_text(encoding="utf-8"))
    return bodies


def split_head(source: str) -> str:
    m = re.search(r"<head>(.*?)</head>", source, re.DOTALL | re.IGNORECASE)
    if not m:
        sys.exit("could not find <head> in source")
    head_inner = m.group(1)
    head_inner = re.sub(r"<title>.*?</title>\s*", "", head_inner, flags=re.DOTALL | re.IGNORECASE)
    head_inner = re.sub(
        r'<meta\s+name="description"[^>]*>\s*', "", head_inner, flags=re.IGNORECASE
    )
    return head_inner.strip()


def extract_block(source: str, start_tag_start: int) -> tuple[str, int]:
    """Return (full block text including closing </div>, index after it)."""
    i = start_tag_start
    depth = 0
    n = len(source)
    open_re = re.compile(r"<div\b", re.IGNORECASE)
    close_re = re.compile(r"</div>", re.IGNORECASE)
    while i < n:
        o = open_re.search(source, i)
        c = close_re.search(source, i)
        if c is None:
            sys.exit("unbalanced <div> in source")
        if o is not None and o.start() < c.start():
            depth += 1
            i = o.end()
        else:
            depth -= 1
            i = c.end()
            if depth == 0:
                return source[start_tag_start:i], i
    sys.exit("unbalanced <div> in source")


PAGE_START_RE = re.compile(
    r'<div\s+id="([^"]+)"\s+class="page[^"]*"\s+'
    r'data-title="([^"]*)"\s+'
    r'data-description="([^"]*)"\s+'
    r'data-slug="([^"]*)">',
    re.IGNORECASE,
)


def find_pages(source: str) -> list[dict]:
    pages: list[dict] = []
    for m in PAGE_START_RE.finditer(source):
        block, _ = extract_block(source, m.start())
        pages.append(
            {
                "id": m.group(1),
                "title": html.unescape(m.group(2)),
                "description": html.unescape(m.group(3)),
                "slug": m.group(4),
                "block": block,
            }
        )
    return pages


def extract_header(source: str) -> str:
    m = re.search(r"<header\b[^>]*>.*?</header>", source, re.DOTALL | re.IGNORECASE)
    if not m:
        sys.exit("could not find <header>")
    return m.group(0)


def extract_footer(source: str) -> str:
    m = re.search(r"<footer\b[^>]*>.*?</footer>", source, re.DOTALL | re.IGNORECASE)
    if not m:
        sys.exit("could not find <footer>")
    return m.group(0)


LINK_RE = re.compile(r'(<a[^>]*?)\s+onclick="showPage\([^)]*\)"', re.IGNORECASE)
LOGO_RE = re.compile(
    r'<div class="logo-wrap"\s+onclick="showPage\(\'home\'\)">(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
CARD_RE = re.compile(
    r'^(\s*)<div class="card" onclick="showPage\(\'([^\']+)\'\)">(.*)</div>\s*$',
    re.MULTILINE | re.IGNORECASE,
)


def lang_prefix(lang_code: str) -> str:
    """Return URL prefix for a language ('' for English root, '/xx' for others)."""
    return "" if lang_code == DEFAULT_LANG else f"/{lang_code}"


def rewrite_links(fragment: str, id_to_slug: dict[str, str], lang_code: str) -> str:
    """Strip showPage() handlers and rewrite hrefs to include /{lang} prefix."""
    prefix = lang_prefix(lang_code)
    fragment = LINK_RE.sub(r"\1", fragment)

    home_href = f"{prefix}/"
    fragment = LOGO_RE.sub(
        rf'<a class="logo-wrap" href="{home_href}" style="text-decoration:none;color:inherit;">\1</a>',
        fragment,
    )

    def card_sub(m: re.Match) -> str:
        indent = m.group(1)
        page_id = m.group(2)
        inner = m.group(3)
        slug = id_to_slug.get(page_id, "")
        href = f"{prefix}/{slug}" if slug else f"{prefix}/"
        return (
            f'{indent}<a class="card" href="{href}" '
            f'style="text-decoration:none;color:inherit;">{inner}</a>'
        )

    fragment = CARD_RE.sub(card_sub, fragment)

    # Rewrite plain href="/slug" links so language subdirectory pages keep
    # visitors inside their language. Root "/" stays a root link, prefixed.
    if prefix:
        def href_sub(m: re.Match) -> str:
            quote = m.group(1)
            path = m.group(2)
            if path.startswith(("http", "mailto:", "#")):
                return m.group(0)
            if path == prefix or path.startswith(f"{prefix}/"):
                return m.group(0)
            if path == "/":
                return f'href={quote}{prefix}/{quote}'
            return f'href={quote}{prefix}{path}{quote}'

        fragment = re.sub(r'href=(["\'])(/[^"\']*)\1', href_sub, fragment)

    return fragment


def activate_page_block(block: str) -> str:
    return re.sub(
        r'(<div\s+id="[^"]+"\s+class="page)[^"]*(")',
        r"\1 active\2",
        block,
        count=1,
        flags=re.IGNORECASE,
    )


def apply_string_replacements(html_fragment: str, replacements: dict[str, str]) -> str:
    """Replace English strings with translations in body HTML.

    Sort by length (longest first) so substring matches don't clobber superstrings.
    """
    if not replacements:
        return html_fragment
    for src in sorted(replacements, key=len, reverse=True):
        dst = replacements[src]
        if not dst:
            continue
        html_fragment = html_fragment.replace(src, dst)
    return html_fragment


PAGE_OPEN_TAG_RE = re.compile(
    r'(<div\s+id="[^"]+"\s+class="page[^"]*"[^>]*>)',
    re.IGNORECASE,
)


def replace_block_body(block: str, new_inner: str) -> str:
    """Swap the inner HTML of the page wrapper <div>, keeping the wrapper intact.

    The block is assumed to have been extracted with balanced div matching,
    so it starts with the wrapper opening tag and ends with its closing </div>.
    """
    m = PAGE_OPEN_TAG_RE.match(block)
    if not m:
        return block
    open_tag = m.group(1)
    return f"{open_tag}\n{new_inner}\n</div>"


def translate_page(
    page: dict,
    translations: dict,
    translated_body: str | None,
) -> dict:
    """Return a copy of page with title, description, block translated if possible.

    When a translated body is provided, it replaces the page's inner HTML
    entirely (authoritative translation). Otherwise, fall back to the
    substring-replacement `strings` map for whatever UI text overlaps.
    """
    out = dict(page)
    page_meta = translations.get("pages", {}).get(page["id"], {})
    if "title" in page_meta:
        out["title"] = page_meta["title"]
    if "description" in page_meta:
        out["description"] = page_meta["description"]
    if translated_body is not None:
        out["block"] = replace_block_body(out["block"], translated_body)
        return out
    strings = translations.get("strings", {})
    if strings:
        out["block"] = apply_string_replacements(out["block"], strings)
    return out


def translate_chrome(chrome_html: str, translations: dict) -> str:
    """Apply string replacements to header/footer chrome."""
    strings = translations.get("strings", {})
    if not strings:
        return chrome_html
    return apply_string_replacements(chrome_html, strings)


SCRIPT = """<script>
  function toggleFaq(el) {
    const answer = el.nextElementSibling;
    const isOpen = answer.classList.contains('open');
    el.closest('.faq').querySelectorAll('.faq-q').forEach(q => q.classList.remove('open'));
    el.closest('.faq').querySelectorAll('.faq-a').forEach(a => a.classList.remove('open'));
    if (!isOpen) {
      el.classList.add('open');
      answer.classList.add('open');
    }
  }
</script>"""


def lang_href(lang_code: str, slug: str) -> str:
    """Relative URL for a given slug in a given language."""
    prefix = lang_prefix(lang_code)
    if slug:
        return f"{prefix}/{slug}"
    return f"{prefix}/"


def build_lang_switcher(current_slug: str, current_lang: Language) -> str:
    """Return the HTML for the language switcher dropdown."""
    items: list[str] = []
    for lang in LANGUAGES:
        href = html.escape(lang_href(lang.code, current_slug), quote=True)
        active = " active" if lang.code == current_lang.code else ""
        name = html.escape(lang.name)
        items.append(
            f'      <a class="lang-item{active}" href="{href}" '
            f'hreflang="{lang.html_lang}" lang="{lang.html_lang}" '
            f'dir="{lang.direction}">{name}</a>'
        )
    menu = "\n".join(items)
    label = html.escape(current_lang.code.upper())
    return (
        '<details class="lang-switch">\n'
        f'      <summary aria-label="Change language">{label}'
        '<span class="lang-caret" aria-hidden="true">&#9662;</span></summary>\n'
        '      <div class="lang-menu" role="menu">\n'
        f"{menu}\n"
        "      </div>\n"
        "    </details>"
    )


def canonical_for(lang_code: str, slug: str) -> str:
    prefix = lang_prefix(lang_code)
    if slug:
        return f"{CANONICAL_BASE}{prefix}/{slug}"
    return f"{CANONICAL_BASE}{prefix}/"


def build_hreflang_tags(slug: str) -> str:
    """Emit alternate links for every language plus x-default (English)."""
    lines: list[str] = []
    for lang in LANGUAGES:
        href = canonical_for(lang.code, slug)
        lines.append(
            f'<link rel="alternate" hreflang="{lang.html_lang}" '
            f'href="{html.escape(href, quote=True)}">'
        )
    default_href = canonical_for(DEFAULT_LANG, slug)
    lines.append(
        f'<link rel="alternate" hreflang="x-default" '
        f'href="{html.escape(default_href, quote=True)}">'
    )
    return "\n".join(lines)


def build_head(
    page: dict,
    shared_head_inner: str,
    lang: Language,
) -> str:
    title = page["title"]
    description = page["description"]
    slug = page["slug"]
    canonical = canonical_for(lang.code, slug)
    esc_title = html.escape(title, quote=True)
    esc_desc = html.escape(description, quote=True)
    esc_canonical = html.escape(canonical, quote=True)
    hreflang_tags = build_hreflang_tags(slug)
    meta_tags = (
        f"<title>{esc_title}</title>\n"
        f'<meta name="description" content="{esc_desc}">\n'
        f'<link rel="canonical" href="{esc_canonical}">\n'
        f"{hreflang_tags}\n"
        f'<meta name="application-name" content="{SITE_NAME}">\n'
        f'<meta property="og:type" content="website">\n'
        f'<meta property="og:site_name" content="{SITE_NAME}">\n'
        f'<meta property="og:locale" content="{lang.html_lang}">\n'
        f'<meta property="og:title" content="{esc_title}">\n'
        f'<meta property="og:description" content="{esc_desc}">\n'
        f'<meta property="og:url" content="{esc_canonical}">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{esc_title}">\n'
        f'<meta name="twitter:description" content="{esc_desc}">\n'
    )
    return f"<head>\n{meta_tags}{shared_head_inner}\n</head>"


def build_html(
    page: dict,
    shared_head_inner: str,
    header: str,
    footer: str,
    id_to_slug: dict[str, str],
    lang: Language,
) -> str:
    block = activate_page_block(page["block"])
    header_out = rewrite_links(header, id_to_slug, lang.code)
    block_out = rewrite_links(block, id_to_slug, lang.code)
    footer_out = rewrite_links(footer, id_to_slug, lang.code)
    switcher = build_lang_switcher(page["slug"], lang)
    header_out = header_out.replace(LANG_SWITCHER_MARKER, switcher)
    html_attrs = f'lang="{lang.html_lang}" dir="{lang.direction}"'
    return (
        "<!DOCTYPE html>\n"
        f"<html {html_attrs}>\n"
        f"{build_head(page, shared_head_inner, lang)}\n"
        "<body>\n\n"
        f"{header_out}\n\n"
        f"{block_out}\n\n"
        f"{footer_out}\n\n"
        f"{SCRIPT}\n"
        "</body>\n"
        "</html>\n"
    )


def output_path(lang_code: str, slug: str) -> Path:
    base = ROOT if lang_code == DEFAULT_LANG else ROOT / lang_code
    if slug == "":
        return base / "index.html"
    return base / slug / "index.html"


def clean_previous_outputs(slugs: list[str]) -> None:
    """Remove per-slug directories at root (English) and each lang subdir."""
    # Remove language subdirectories entirely (will be regenerated).
    for lang in LANGUAGES:
        if lang.code == DEFAULT_LANG:
            continue
        d = ROOT / lang.code
        if d.is_dir():
            shutil.rmtree(d)
    # Remove English slug dirs at root.
    for slug in slugs:
        if not slug:
            continue
        d = ROOT / slug
        if d.is_dir():
            shutil.rmtree(d)


def generate_for_language(
    lang: Language,
    pages: list[dict],
    shared_head_inner: str,
    header: str,
    footer: str,
    id_to_slug: dict[str, str],
    translations_by_lang: dict[str, dict],
    bodies_by_lang: dict[str, dict[str, str]],
) -> None:
    translations = translations_by_lang.get(lang.code, {})
    bodies = bodies_by_lang.get(lang.code, {})
    header_loc = translate_chrome(header, translations) if translations else header
    footer_loc = translate_chrome(footer, translations) if translations else footer

    for page in pages:
        translated_body = bodies.get(page["id"]) if bodies else None
        localized = (
            translate_page(page, translations, translated_body)
            if (translations or translated_body is not None)
            else page
        )
        out = output_path(lang.code, localized["slug"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            build_html(localized, shared_head_inner, header_loc, footer_loc, id_to_slug, lang),
            encoding="utf-8",
        )
        print(f"wrote {out.relative_to(ROOT)}")


def main() -> None:
    source = read_source()
    shared_head_inner = split_head(source)
    header = extract_header(source)
    footer = extract_footer(source)
    pages = find_pages(source)
    translations_by_lang = load_translations()
    bodies_by_lang = load_bodies()

    if not pages:
        sys.exit("no pages found in source")

    slugs = [p["slug"] for p in pages]
    if len(slugs) != len(set(slugs)):
        sys.exit(f"duplicate slugs detected: {slugs}")

    id_to_slug = {p["id"]: p["slug"] for p in pages}

    print(f"found {len(pages)} pages and {len(LANGUAGES)} languages")

    clean_previous_outputs(slugs)

    for lang in LANGUAGES:
        print(f"\n=== {lang.code} ({lang.name}) ===")
        generate_for_language(
            lang,
            pages,
            shared_head_inner,
            header,
            footer,
            id_to_slug,
            translations_by_lang,
            bodies_by_lang,
        )


if __name__ == "__main__":
    main()
