// ui/thumbnailHighlight.js – destaca a thumbnail da página em foco
import { store } from '../store.js';

export function highlightActiveThumbnail(pageId) {
  document.querySelectorAll('.thumbnail')
          .forEach(t => t.classList.remove('active-thumbnail'));

  const active = document.querySelector(`.thumbnail[data-page-id="${pageId}"]`);
  if (!active) return;

  active.classList.add('active-thumbnail');

  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  const thumbRect = active.getBoundingClientRect();
  const sideRect = sidebar.getBoundingClientRect();
  if (thumbRect.top < sideRect.top || thumbRect.bottom > sideRect.bottom) {
    sidebar.scrollTop += thumbRect.top - sideRect.top - 8;
  }
}
