// The Home page's text (event.json via the exporter). It is untrusted: every
// field is optional, only short plain strings survive, and the page shows it
// as text, never as markup. Pure (no DOM), tested in Node.

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const list = (value) => (Array.isArray(value) ? value : []);

/** event.json made safe; null when the organiser gave nothing. */
export function normalizeEvent(raw) {
  if (!isObject(raw)) return null;
  const text = (v, max = 1200) => (typeof v === 'string' ? v.trim().slice(0, max) : '');
  const texts = (v) => list(v).map((x) => text(x)).filter(Boolean).slice(0, 20);
  const timeline = list(raw.timeline)
    .filter((row) => isObject(row) && text(row.title))
    .slice(0, 30)
    .map((row) => ({ time: text(row.time, 40), title: text(row.title, 120), detail: text(row.detail) }));
  const event = {
    tagline: text(raw.tagline, 200),
    intro: texts(raw.intro),
    prize: text(raw.prize, 200),
    timeline,
    rules: texts(raw.rules),
    contact: text(raw.contact),
  };
  const empty = !event.tagline && !event.intro.length && !event.prize && !timeline.length && !event.rules.length && !event.contact;
  return empty ? null : event;
}
