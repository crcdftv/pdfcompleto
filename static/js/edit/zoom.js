// edit/zoom.js – zoom com debounce (150 ms)
import { store, setStore } from '../store.js';
import { renderPDFLocal } from '../pdf/render.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { ZOOM_DELAY } from '../constants.js';

export function zoomIn() {
  if (!store.pdfUrl) { alert('Nenhum PDF carregado.'); return; }
  const newScale = Math.min(5, store.currentScale + 0.1);
  scheduleZoom(newScale, '🔍 Zoom Aumentado');
}

export function zoomOut() {
  if (!store.pdfUrl) { alert('Nenhum PDF carregado.'); return; }
  const newScale = Math.max(0.1, store.currentScale - 0.1);
  scheduleZoom(newScale, '🔎 Zoom Reduzido');
}

/* ------------------------------------------------------------------ */
function getCenterPage() {
  const containers = document.querySelectorAll('.page-container');
  const viewportCenter = window.scrollY + window.innerHeight / 2;
  let closest = null;
  let minDist = Infinity;

  for (const c of containers) {
    const top = window.scrollY + c.getBoundingClientRect().top;
    const bottom = top + c.offsetHeight;
    const center = (top + bottom) / 2;
    const dist = Math.abs(center - viewportCenter);
    if (dist < minDist) {
      minDist = dist;
      closest = c;
    }
  }
  return closest;
}

let zoomTimer = null;
function scheduleZoom(scale, msg) {
  clearTimeout(zoomTimer);

  // Salva qual página está no centro do viewport
  const centerPage = getCenterPage();
  const pageId = centerPage ? centerPage.dataset.pageId : null;

  zoomTimer = setTimeout(async () => {
    await renderPDFLocal(scale);
    setStore('currentScale', scale);

    // Restaura scroll para a mesma página
    if (pageId) {
      const target = document.querySelector(`.page-container[data-page-id="${pageId}"]`);
      if (target) {
        target.scrollIntoView({ block: 'start', behavior: 'auto' });
      }
    }

    showTemporaryMessage(msg);
  }, ZOOM_DELAY);
}
