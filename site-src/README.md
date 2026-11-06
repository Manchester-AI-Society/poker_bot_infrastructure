# site-src: the arena site's Tailwind build

The static site in `arena/site/` is styled with Tailwind CSS v4, compiled at
build time. **The output is committed** (`arena/site/css/site.css` and
`arena/site/fonts/`), so `arena export` and running the arena need no Node.
Rebuild only when you change `input.css`, `arena/site/index.html` or a class
name in `arena/site/js/`.

```
cd site-src
npm ci            # or: npm install
npm run build     # writes ../arena/site/css/site.css (minified) and copies the fonts
npm run check     # rebuilds and fails if the committed output was stale
```

- `input.css` is the Tailwind entry: the `@source` paths, the bundled
  JetBrains Mono `@font-face` rules, the chart colour tokens and the
  component classes (`.card`, `.badge`, `.tbl`, ...) the scripts use.
- Fonts come from the `@fontsource/jetbrains-mono` npm package; the build copies
  four latin `.woff2` files and the OFL licence into `arena/site/fonts/`.
- Nothing is loaded from the internet: the tests in
  `tests/test_arena_site_assets.py` check the HTML, scripts and the compiled CSS.
- The same freshness check runs as a pytest (`test_the_committed_stylesheet_and_fonts_match_a_fresh_build`);
  it is skipped when `site-src/node_modules` is missing.
