// Playing cards drawn from text: a face (rank over suit glyph), a back, an
// empty slot. Shared by the hand replayer and the live table. The face is
// white in both colour schemes; the red suits are the one data-driven colour,
// and the glyph names the suit as well.

import { h } from '../dom.js';
import { parseCard } from '../replay-core.js';

export function cardEl(code) {
  const card = parseCard(code);
  return h(
    'span',
    { class: `card-pl${card.red ? ' red' : ''}`, 'aria-label': card.text },
    h('b', {}, card.rank),
    h('i', { 'aria-hidden': 'true' }, card.glyph),
  );
}

export const cardBack = () => h('span', { class: 'card-pl back', 'aria-label': 'hidden card' });
export const cardSlot = () => h('span', { class: 'card-pl empty', 'aria-hidden': 'true' });
