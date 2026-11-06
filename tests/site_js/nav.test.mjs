import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createNav } from '../../arena/site/js/nav.js';

/** Just enough of an element for the menu code: classes, attributes, events. */
function fakeElement(classes = []) {
  const set = new Set(classes);
  const handlers = {};
  return {
    attrs: {},
    classList: {
      contains: (name) => set.has(name),
      toggle: (name, on) => (on ? set.add(name) : set.delete(name)),
    },
    setAttribute(name, value) { this.attrs[name] = value; },
    addEventListener(type, fn) { (handlers[type] ||= []).push(fn); },
    fire(type, event = {}) { for (const fn of handlers[type] || []) fn(event); },
    focus() { this.focused = true; },
    classes: () => [...set].sort(),
  };
}

const setup = () => {
  const toggle = fakeElement();
  const menu = fakeElement(['max-h-0', 'invisible']);
  const doc = fakeElement();
  const win = fakeElement();
  const nav = createNav(toggle, menu, { doc, win });
  return { toggle, menu, doc, win, nav };
};

test('the hamburger button opens and closes the menu and says so', () => {
  const { toggle, menu, nav } = setup();
  assert.equal(nav.isOpen(), false);
  toggle.fire('click');
  assert.equal(nav.isOpen(), true);
  assert.deepEqual(menu.classes(), ['max-h-96', 'visible']);
  assert.equal(toggle.attrs['aria-expanded'], 'true');
  toggle.fire('click');
  assert.deepEqual(menu.classes(), ['invisible', 'max-h-0']);
  assert.equal(toggle.attrs['aria-expanded'], 'false');
});

test('choosing a link in the open menu closes it, but clicking its padding does not', () => {
  const { toggle, menu, nav } = setup();
  toggle.fire('click');
  menu.fire('click', { target: { closest: () => null } });
  assert.equal(nav.isOpen(), true);
  menu.fire('click', { target: { closest: () => ({}) } });
  assert.equal(nav.isOpen(), false);
});

test('Escape and a page change close the menu', () => {
  const { toggle, doc, win, nav } = setup();
  toggle.fire('click');
  doc.fire('keydown', { key: 'a' });
  assert.equal(nav.isOpen(), true);
  doc.fire('keydown', { key: 'Escape' });
  assert.equal(nav.isOpen(), false);
  assert.equal(toggle.focused, true);
  nav.setOpen(true);
  win.fire('hashchange');
  assert.equal(nav.isOpen(), false);
});
