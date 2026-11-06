// Copies the JetBrains Mono files the site uses from the npm package into
// arena/site/fonts/ (committed, so `arena export` needs no Node). Also copies
// the SIL Open Font License that ships with the fonts.
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const pkg = join(here, '..', 'node_modules', '@fontsource', 'jetbrains-mono');
const out = join(here, '..', '..', 'arena', 'site', 'fonts');

const FILES = [
  'jetbrains-mono-latin-400-normal.woff2',
  'jetbrains-mono-latin-500-normal.woff2',
  'jetbrains-mono-latin-700-normal.woff2',
  'jetbrains-mono-latin-400-italic.woff2',
];

mkdirSync(out, { recursive: true });
for (const name of FILES) copyFileSync(join(pkg, 'files', name), join(out, name));
copyFileSync(join(pkg, 'LICENSE'), join(out, 'OFL.txt'));
