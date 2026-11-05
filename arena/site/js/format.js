// Pure helpers: number and time formatting, hash routing, colour maths.
// Nothing here touches the DOM, so Node can test it (tests/site_js).

export const MINUS = '−';

/** Signed big blinds per hand, e.g. "+0.123". Never "-0.000". */
export function fmtBB(value, digits = 3) {
  if (value == null || !Number.isFinite(value)) return '—';
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return (0).toFixed(digits);
  return (rounded > 0 ? '+' : MINUS) + Math.abs(rounded).toFixed(digits);
}

/** Unsigned number for an interval half-width, e.g. "0.045". */
export function fmtPlain(value, digits = 3) {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toFixed(digits);
}

/** Whole chips with thousands separators. */
export function fmtChips(value) {
  if (value == null || !Number.isFinite(value)) return '—';
  return Math.round(value).toLocaleString('en-GB');
}

/** "just now", "12 s ago", "3 min ago", "2 h ago", "4 d ago". */
export function ago(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return '';
  const s = Math.max(0, Math.round(seconds));
  if (s < 5) return 'just now';
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

export function shortHash(hash) {
  return hash ? String(hash).slice(0, 7) : '';
}

/** Parses "#/team/alpha?kind=final" into {path: ['team','alpha'], query}. */
export function parseHash(hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const at = raw.indexOf('?');
  const pathPart = at === -1 ? raw : raw.slice(0, at);
  const queryPart = at === -1 ? '' : raw.slice(at + 1);
  const path = pathPart
    .split('/')
    .filter(Boolean)
    .map((piece) => {
      try {
        return decodeURIComponent(piece);
      } catch {
        return piece;
      }
    });
  const query = {};
  for (const [key, value] of new URLSearchParams(queryPart)) query[key] = value;
  return { path, query };
}

/** The inverse of parseHash. Empty query values are dropped. */
export function buildHash(path, query = {}) {
  const base = '#/' + path.map(encodeURIComponent).join('/');
  const pairs = Object.entries(query).filter(([, v]) => v != null && v !== '');
  if (!pairs.length) return base;
  return base + '?' + new URLSearchParams(pairs).toString();
}

/** Rounds up to 1, 2, 2.5, 5 or 10 times a power of ten. */
export function niceMax(value) {
  if (!(value > 0) || !Number.isFinite(value)) return 1;
  const exponent = Math.pow(10, Math.floor(Math.log10(value)));
  const fraction = value / exponent;
  let nice = 10;
  if (fraction <= 1) nice = 1;
  else if (fraction <= 2) nice = 2;
  else if (fraction <= 2.5) nice = 2.5;
  else if (fraction <= 5) nice = 5;
  return nice * exponent;
}

// ---- colour ----------------------------------------------------------

export function hexToRgb(hex) {
  const clean = String(hex).trim().replace(/^#/, '');
  const full =
    clean.length === 3
      ? clean.split('').map((c) => c + c).join('')
      : clean;
  const n = parseInt(full, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgbToHex([r, g, b]) {
  const part = (v) => Math.round(v).toString(16).padStart(2, '0');
  return '#' + part(r) + part(g) + part(b);
}

/** Linear mix of two hex colours: t=0 gives a, t=1 gives b. */
export function mixHex(a, b, t) {
  const k = Math.min(1, Math.max(0, t));
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  return rgbToHex([ar + (br - ar) * k, ag + (bg - ag) * k, ab + (bb - ab) * k]);
}

/** WCAG relative luminance. */
export function luminance(hex) {
  const lin = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const [r, g, b] = hexToRgb(hex).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** Black or white text, whichever reads better on `background`. */
export function inkFor(background, dark = '#0b0b0b', light = '#ffffff') {
  return contrast(background, dark) >= contrast(background, light) ? dark : light;
}

/** The q-quantile (0..1) of a list of numbers; 0 for an empty list. */
export function quantile(values, q) {
  const sorted = values.filter(Number.isFinite).sort((x, y) => x - y);
  if (!sorted.length) return 0;
  const index = Math.min(sorted.length - 1, Math.max(0, Math.round(q * (sorted.length - 1))));
  return sorted[index];
}
