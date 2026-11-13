// pdf/render.js – renderiza todas as páginas (optimizado)
import { store, setStore } from '../store.js';
import { redrawTarjasOnCanvas } from '../edit/redactionCanvas.js';
import { renderTextLayer } from './textLayer.js';
import { getVisiblePageNumbers, renderPagesBatch } from './renderHelpers.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { highlightActiveThumbnail } from '../ui/thumbnailHighlight.js';
import { updateLoadingProgress } from '../ui/loadingOverlay.js';

/**
 * Renderiza todo o documento (ou apenas as páginas visíveis, se preferir).
 * `scale` → novo zoom; `scrollRatio` mantém a posição de scroll.
 */
export async function renderPDFLocal(scale = 1, scrollRatio = 0) {
  if (store.isRendering) {
    store.pendingRenderRequest = { scale, scrollRatio };
    return;
  }

  store.isRendering = true;
  if (store.renderAbortController) store.renderAbortController.abort();
  store.renderAbortController = new AbortController();
  const signal = store.renderAbortController.signal;

  try {
    const pdfRender = document.getElementById('pdf-render');
    if (!pdfRender) {
      console.error('❌ Elemento #pdf-render não encontrado!');
      return;
    }

    const visiblePages = getVisiblePageNumbers();
    const allPages = [...store.pageOrder];
    const totalPages = allPages.length;
    let renderedCount = 0;

    function reportProgress() {
      renderedCount++;
      const pct = Math.round((renderedCount / totalPages) * 100);
      updateLoadingProgress(Math.min(pct, 100), `Renderizando páginas… ${renderedCount}/${totalPages}`);
    }

    // --------- 1️⃣ Atualiza containers (tamanho) ----------
    for (const id of store.pageOrder) {
      const map = store.pageMappings[id];
      if (!map || !map.pdfDoc) continue;

      const page = await map.pdfDoc.getPage(map.pageInDoc);
      const rotation = store.pageRotations[id] || 0;
      const vp = page.getViewport({ scale, rotation });

      const cont = pdfRender.querySelector(`.page-container[data-page-id="${id}"]`);
      if (cont) {
        cont.style.width = `${vp.width}px`;
        cont.style.height = `${vp.height}px`;
      }

      map.canvasWidth = vp.width;
      map.canvasHeight = vp.height;
    }

    // --------- 2️⃣ Restaura scroll ----------
    if (scrollRatio > 0) {
      const newHeight = pdfDiv.scrollHeight;
      window.scrollTo(0, scrollRatio * newHeight);
    }

    // --------- 3️⃣ Renderiza páginas visíveis primeiro ----------
    await renderPagesBatch(visiblePages, scale, signal, true, reportProgress);
    if (signal.aborted) return;

    // --------- 4️⃣ Renderiza invisíveis (background) ----------
    const invisible = allPages.filter(p => !visiblePages.includes(p));
    await renderPagesBatch(invisible, scale, signal, false, reportProgress);

    // --------- 5️⃣ Atualiza estado ----------
    setStore('currentScale', scale);
    highlightActiveThumbnail(store.focusedPage);

  } catch (e) {
    if (e.name !== 'AbortError') {
      console.error('❌ Erro renderPDFLocal →', e);
    }
  } finally {
    store.isRendering = false;
    store.renderAbortController = null;

    if (store.pendingRenderRequest) {
      const { scale, scrollRatio } = store.pendingRenderRequest;
      store.pendingRenderRequest = null;
      setTimeout(() => renderPDFLocal(scale, scrollRatio), 50);
    }
  }
}

/**
 * Renderiza uma única página (usado por renderPagesBatch)
 * @param {string} pageId - ID da página
 * @param {number} scale - Escala de renderização
 * @param {AbortSignal} signal - Signal para cancelar renderização
 */
export async function renderSinglePage(pageId, scale, signal) {
  if (signal && signal.aborted) return;

  const map = store.pageMappings[pageId];
  if (!map || !map.pdfDoc) {
    console.warn(`⚠️ Mapeamento não encontrado para página: ${pageId}`);
    return;
  }

  try {
    const page = await map.pdfDoc.getPage(map.pageInDoc);
    const rotation = store.pageRotations[pageId] || 0;
    const vp = page.getViewport({ scale, rotation });

    const container = document.querySelector(`.page-container[data-page-id="${pageId}"]`);
    if (!container) {
      console.warn(`⚠️ Container não encontrado para página: ${pageId}`);
      return;
    }

    const pdfCanvas = container.querySelector('.pdf-canvas');
    const drawCanvas = container.querySelector('.draw-canvas');
    const textLayer = container.querySelector('.text-layer');

    if (!pdfCanvas || !drawCanvas) {
      console.warn(`⚠️ Canvas não encontrado para página: ${pageId}`);
      return;
    }

    // ---- Renderiza PDF no canvas ----
    const ctx = pdfCanvas.getContext('2d');
    pdfCanvas.width = vp.width;
    pdfCanvas.height = vp.height;

    await page.render({
      canvasContext: ctx,
      viewport: vp
    }).promise;

    // ---- Renderiza camada de texto ----
    if (textLayer) {
      await renderTextLayer(page, textLayer, vp);
    }

    // ---- Renderiza tarjas (drawCanvas) ----
    drawCanvas.width = vp.width;
    drawCanvas.height = vp.height;
    redrawTarjasOnCanvas(drawCanvas);

  } catch (error) {
    console.error(`❌ Erro ao renderizar página ${pageId}:`, error);
  }
}

/**
 * Re-renderiza todas as páginas com novo zoom
 * @param {number} newScale - Nova escala
 */
export async function reRenderWithZoom(newScale) {
  const pdfDiv = document.getElementById('pdf-render');
  if (!pdfDiv) return;

  const scrollRatio = window.scrollY / (pdfDiv.scrollHeight || 1);
  await renderPDFLocal(newScale, scrollRatio);
}

/**
 * Re-renderiza uma página específica
 * @param {string} pageId - ID da página
 */
export async function reRenderPage(pageId) {
  const scale = store.currentScale || 1.5;
  await renderSinglePage(pageId, scale, { aborted: false });
}

// ⭐ Alias para compatibilidade com app.js
// Como o upload.js já faz tudo, renderPDF será apenas um alias
export { renderPDFLocal as renderPDF };