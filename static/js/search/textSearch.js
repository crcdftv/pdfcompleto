// search/textSearch.js – busca texto no PDF (highlight + navegação)
import { store, setStore } from '../store.js';
import { redrawTarjasOnCanvas } from '../edit/redactionCanvas.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { getVisiblePageNumbers } from '../pdf/renderHelpers.js';

/* ------------------------------------------------------------------ */
/* Exporta a função que o botão da barra de busca chama */
export async function searchInPDF(term) {
  if (!store.pdfDoc) { alert('Nenhum PDF carregado.'); return; }

  const lower = term.toLowerCase();
  const hits = [];

  for (const pageId of store.pageOrder) {
    const mapping = store.pageMappings[pageId];
    const page = await mapping.pdfDoc.getPage(mapping.pageInDoc);
    const txt = await page.getTextContent();

    txt.items.forEach(item => {
      const txtStr = item.str.trim();
      if (!txtStr) return;

      if (txtStr.toLowerCase().includes(lower)) {
        // coordenadas simples (usamos o mesmo algoritmo de getPartialBounds do main.js)
        const bounds = getPartialBounds(item, page, store.currentScale);
        if (bounds) hits.push({ page: pageId, ...bounds });
      }
    });
  }

  if (hits.length === 0) {
    alert(`Termo “${term}” não encontrado.`);
    return;
  }

  // armazena no store para navegação entre resultados
  setStore('search', {
    highlights: hits,
    term,
    currentIdx: 0,
    timeoutId: null
  });

  drawSearchHighlights();
  goToHighlight(0);
}

/* ------------------------------------------------------------------ */
/* Desenha retângulos amarelos nos draw‑canvas */
function drawSearchHighlights() {
  const { highlights } = store.search;
  highlights.forEach(h => {
    const canvas = document.querySelector(`.page-container[data-page-id="${h.page}"] .draw-canvas`);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.save();
    ctx.fillStyle = 'rgba(255,255,0,0.4)';
    ctx.fillRect(h.x, h.y, h.w, h.h);
    ctx.restore();
  });
}

/* ------------------------------------------------------------------ */
export function goToHighlight(idx) {
  const { highlights, currentIdx } = store.search;
  if (!highlights.length) return;

  const next = (idx + highlights.length) % highlights.length;
  const hl = highlights[next];
  const cont = document.querySelector(`.page-container[data-page-id="${hl.page}"]`);
  if (cont) cont.scrollIntoView({ behavior: 'smooth', block: 'center' });
  setStore('search', { ...store.search, currentIdx: next });
}

/* ------------------------------------------------------------------ */
export function clearSearch() {
  // remove highlights de busca (não afeta tarjas)
  document.querySelectorAll('.draw-canvas').forEach(canvas => {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    redrawTarjasOnCanvas(canvas);
  });
  setStore('search', { highlights: [], term: '', currentIdx: 0, timeoutId: null });
}

/* ------------------------------------------------------------------ */
/* Helper: converte um TextItem para retângulo no canvas usando a matriz do viewport */
function getPartialBounds(item, page, scale) {
  const vp = page.getViewport({ scale });

  // Pega translação da matriz de transformação do item (canto inferior-esquerdo)
  const [, , , , pdfX, pdfY] = item.transform;
  const pdfW = item.width;
  const pdfH = item.height;

  // Converte os dois cantos usando a transformação do viewport do PDF.js
  const [x0, y0] = vp.convertToViewportPoint(pdfX,        pdfY);
  const [x1, y1] = vp.convertToViewportPoint(pdfX + pdfW, pdfY + pdfH);

  return {
    x: Math.min(x0, x1),
    y: Math.min(y0, y1),
    w: Math.abs(x1 - x0),
    h: Math.abs(y1 - y0),
  };
}