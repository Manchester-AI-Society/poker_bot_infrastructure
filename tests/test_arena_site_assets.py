"""The static site's own files: complete, self-contained and publishable."""

from __future__ import annotations

import re

from arena.export import SITE_DIR, ExportOptions, export_site
from arena.store import Store

IMPORT = re.compile(r"""(?:import|export)[^'"]*?from\s+['"](\.[^'"]+)['"]""")
BARE_IMPORT = re.compile(r"""import\s+['"](\.[^'"]+)['"]""")
EXTERNAL = re.compile(r"""(?:src|href)=["'](https?:)?//""", re.IGNORECASE)
REMOTE_URL = re.compile(r"https?://")
# The SVG namespace is an identifier, not something the page fetches.
ALLOWED_URLS = ("http://www.w3.org/2000/svg",)
# The Register page sends the visitor to GitHub (a link they click, and example
# text). Only these two files may name it, and never to fetch anything.
GITHUB_LINK = "https://github.com/"
GITHUB_LINK_FILES = ("register-core.js", "register.js")


def js_files():
    return sorted(SITE_DIR.rglob("*.js"))


def code_only(text: str) -> str:
    """The source without comments, so a comment cannot trip a check."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    return re.sub(r"\s//\s.*$", "", text, flags=re.MULTILINE)


def remote_urls_in(code: str, name: str = "") -> bool:
    allowed_here = ALLOWED_URLS
    if name in GITHUB_LINK_FILES:
        allowed_here += (GITHUB_LINK,)
    for allowed in allowed_here:
        code = code.replace(allowed, "")
    return bool(REMOTE_URL.search(code))


def test_the_site_has_an_entry_page_and_stylesheet():
    assert (SITE_DIR / "index.html").exists()
    assert (SITE_DIR / "css" / "site.css").exists()
    assert (SITE_DIR / "js" / "main.js").exists()


def test_every_relative_javascript_import_points_at_a_real_file():
    # A typo in an import path gives a blank page with no server-side error.
    missing = []
    for source in js_files():
        text = source.read_text(encoding="utf-8")
        for target in IMPORT.findall(text) + BARE_IMPORT.findall(text):
            if not (source.parent / target).resolve().exists():
                missing.append(f"{source.relative_to(SITE_DIR)} -> {target}")
    assert js_files(), "expected JavaScript modules"
    assert missing == []


def test_the_page_loads_nothing_from_the_internet():
    # It must work on a venue network with no internet, and a public host
    # must not depend on a third party being up.
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    assert not EXTERNAL.search(html)
    for source in js_files():
        code = code_only(source.read_text(encoding="utf-8"))
        assert not remote_urls_in(code, source.name), source.name
        if source.name in GITHUB_LINK_FILES:
            assert "fetch(" not in code, source.name
            assert "XMLHttpRequest" not in code, source.name


def test_the_url_check_can_actually_fail():
    # Guards the guard: a real remote URL in code must be noticed, while a
    # comment or the SVG namespace must not be.
    assert remote_urls_in(code_only("fetch('https://cdn.example.com/a.js');"))
    assert not remote_urls_in(code_only("// see https://example.com\nlet a;"))
    assert not remote_urls_in("createElementNS('http://www.w3.org/2000/svg')")
    # The GitHub link is allowed only in the Register files, and no other host.
    link = "const u = 'https://github.com/a/b';"
    assert not remote_urls_in(link, "register-core.js")
    assert remote_urls_in(link, "main.js")
    assert remote_urls_in("x = 'https://evil.example/a';", "register-core.js")


def test_the_page_never_writes_data_into_the_document_as_markup():
    # Team names and the organiser's text must go in as text, never HTML.
    for source in js_files():
        code = code_only(source.read_text(encoding="utf-8"))
        assert "innerHTML" not in code, source.name
        assert "insertAdjacentHTML" not in code, source.name
        assert "document.write" not in code, source.name


def test_the_index_references_files_that_exist():
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    for reference in re.findall(r"""(?:src|href)="([^"#:]+)"\s*""", html):
        assert (SITE_DIR / reference).exists(), reference


def test_export_copies_the_page_but_not_development_files(tmp_path):
    store = Store(tmp_path / "arena_data")
    out = tmp_path / "site"

    export_site(store.root, out, ExportOptions())

    assert (out / "index.html").exists()
    assert (out / "js" / "main.js").exists()
    assert (out / "js" / "views" / "replay.js").exists()
    assert (out / "css" / "site.css").exists()
    assert (out / ".nojekyll").exists()
    # Only there so Node can import the modules in tests.
    assert not (out / "package.json").exists()
    published = {
        p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
    }
    assert "data/manifest.json" in published


def test_export_repairs_a_page_file_that_was_edited_or_deleted(tmp_path):
    store = Store(tmp_path / "arena_data")
    out = tmp_path / "site"
    export_site(store.root, out, ExportOptions())
    original = (out / "js" / "main.js").read_text(encoding="utf-8")
    (out / "js" / "main.js").write_text("broken", encoding="utf-8")
    (out / "css" / "site.css").unlink()

    export_site(store.root, out, ExportOptions())

    assert (out / "js" / "main.js").read_text(encoding="utf-8") == original
    assert (out / "css" / "site.css").exists()
