// Fails when the committed arena/site/css/site.css or fonts differ from a
// fresh build. Skips (exit 0) when node_modules is absent.
import { execSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
if (!existsSync(join(root, 'node_modules', 'tailwindcss'))) {
  console.log('site-src/node_modules is missing: run `npm install` first. Skipping.');
  process.exit(0);
}
const files = [
  'css/site.css',
  'fonts/OFL.txt',
  'fonts/jetbrains-mono-latin-400-normal.woff2',
  'fonts/jetbrains-mono-latin-500-normal.woff2',
  'fonts/jetbrains-mono-latin-700-normal.woff2',
  'fonts/jetbrains-mono-latin-400-italic.woff2',
];
const site = join(root, '..', 'arena', 'site');
// A Windows checkout may turn LF into CRLF in the text files; that is not a difference.
const read = (f) => {
  const bytes = readFileSync(join(site, f));
  return /\.(css|txt)$/.test(f) ? Buffer.from(bytes.toString('utf8').replace(/\r\n/g, '\n')) : bytes;
};
const before = files.map(read);
execSync('npm run build', { cwd: root, stdio: 'inherit' });
const stale = files.filter((f, i) => !read(f).equals(before[i]));
if (stale.length) {
  console.error(`Committed build output was out of date: ${stale.join(', ')} (now rewritten; review and commit).`);
  process.exit(1);
}
console.log('arena/site/css/site.css and fonts match a fresh build.');
