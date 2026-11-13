// pdf/renderHelpers.js – auxiliares usados por render.js
import { store } from '../store.js';
import { renderSinglePage } from './render.js';

export function getVisiblePageNumbers() {
  const visible = [];
  document.querySelectorAll('.page-container').forEach(cont => {
    const rect = cont.getBoundingClientRect();
    if (rect.bottom > 0 && rect.top < window.innerHeight) {
      const id = parseInt(cont.dataset.pageId, 10);
      if (id) visible.push(id);
    }
  });
  return visible;
}

export async function renderPagesBatch(pageIds, scale, signal, highPriority = false, onPageRendered = null) {
  if (highPriority) {
    await Promise.all(pageIds.map(async id => {
      await renderSinglePage(id, scale, signal);
      if (onPageRendered) onPageRendered();
    }));
    return;
  }

  const batchSize = 4;
  for (let i = 0; i < pageIds.length; i += batchSize) {
    if (signal.aborted) break;
    const batch = pageIds.slice(i, i + batchSize);
    await Promise.all(batch.map(async id => {
      await renderSinglePage(id, scale, signal);
      if (onPageRendered) onPageRendered();
    }));
    if (!signal.aborted) await new Promise(r => setTimeout(r, 16));
  }
}