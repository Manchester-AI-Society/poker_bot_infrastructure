// The mobile menu: a hamburger button that expands the nav links. Loaded as
// its own module (not inline) so the page needs no inline script. On wide
// screens the menu is always shown by CSS and this only keeps the button's
// state in step.

const OPEN = ['max-h-96', 'visible'];
const CLOSED = ['max-h-0', 'invisible'];

/**
 * Wires a toggle button to a menu element. Returns {setOpen, isOpen}.
 * The menu is opened by the button and closed by the button, by choosing
 * anything inside the menu, by the Escape key, and when the page changes.
 */
export function createNav(toggle, menu, { doc = null, win = null } = {}) {
  const isOpen = () => menu.classList.contains('max-h-96');
  const setOpen = (open) => {
    for (const name of OPEN) menu.classList.toggle(name, open);
    for (const name of CLOSED) menu.classList.toggle(name, !open);
    toggle.setAttribute('aria-expanded', String(open));
  };
  toggle.addEventListener('click', () => setOpen(!isOpen()));
  // Following a link (or pressing a switch) in the open menu closes it again.
  menu.addEventListener('click', (event) => {
    if (isOpen() && event.target && event.target.closest && event.target.closest('a, button')) setOpen(false);
  });
  if (doc) {
    doc.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && isOpen()) {
        setOpen(false);
        if (toggle.focus) toggle.focus();
      }
    });
  }
  if (win) win.addEventListener('hashchange', () => setOpen(false));
  return { setOpen, isOpen };
}

if (typeof document !== 'undefined') {
  const toggle = document.getElementById('navbar-toggle');
  const menu = document.getElementById('navbar-default');
  if (toggle && menu) createNav(toggle, menu, { doc: document, win: window });
}
