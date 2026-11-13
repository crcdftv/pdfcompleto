// pdf/thumbnails.js – gera miniaturas + drag‑and‑drop + botão de excluir
import { store, setStore } from '../store.js';
import { reorderPages } from '../edit/reorder.js';
import { highlightActiveThumbnail } from '../ui/thumbnailHighlight.js';
import { deletePage } from '../edit/deletePage.js';
import { showTemporaryMessage } from '../ui/toast.js';

export async function generateThumbnails(onProgress = null) {
  const container = document.getElementById('thumbnails');
  container.innerHTML = '';

  const total = store.pageOrder.length;

  // Renderiza todas as miniaturas em paralelo com limite de concorrência
  // pra não sobrecarregar o PDF.js (máx 4 simultâneas)
  const CONCURRENCY = 4;
  const results = new Array(total);

  for (let i = 0; i < total; i += CONCURRENCY) {
    const batch = store.pageOrder.slice(i, i + CONCURRENCY);
    await Promise.all(batch.map(async (id, batchIdx) => {
      const idx = i + batchIdx;
      const map = store.pageMappings[id];
      const page = await map.pdfDoc.getPage(map.pageInDoc);
      const vp = page.getViewport({ scale: 0.2 });

      const canvas = document.createElement('canvas');
      canvas.width = vp.width;
      canvas.height = vp.height;
      await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;

      results[idx] = { id, canvas, label: idx + 1 };

      if (typeof onProgress === 'function') {
        onProgress(Math.round(((idx + 1) / total) * 100));
      }
    }));
  }

  // Monta o DOM de uma vez usando fragment — muito mais rápido
  const fragment = document.createDocumentFragment();
  for (const { id, canvas, label } of results) {
    const thumb = document.createElement('div');
    thumb.className = 'thumbnail';
    thumb.dataset.pageId = id;
    thumb.draggable = true;

    const labelEl = document.createElement('span');
    labelEl.className = 'thumbnail-label';
    labelEl.textContent = `Pág ${label}`;
    thumb.appendChild(labelEl);
    thumb.appendChild(canvas);

    const btn = document.createElement('button');
    btn.className = 'delete-page-button';
    btn.innerHTML = '&times;';
    btn.title = `Excluir página ${id}`;
    btn.onclick = e => {
      e.stopPropagation();
      if (confirm(`Excluir página ${id}?`)) deletePage(id);
    };
    thumb.appendChild(btn);

    thumb.addEventListener('click', () => {
      store.focusedPage = id;
      const pc = document.querySelector(`.page-container[data-page-id="${id}"]`);
      if (pc) pc.scrollIntoView({ behavior: 'smooth', block: 'start' });
      highlightActiveThumbnail(id);
    });

    thumb.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', id);
      thumb.classList.add('dragging');
    });
    thumb.addEventListener('dragend', () => thumb.classList.remove('dragging'));
    thumb.addEventListener('dragover', e => {
      e.preventDefault();
      thumb.classList.add('drag-over');
    });
    thumb.addEventListener('dragleave', () => thumb.classList.remove('drag-over'));
    thumb.addEventListener('drop', e => {
      e.preventDefault();
      thumb.classList.remove('drag-over');
      const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
      reorderPages(from, id);
    });

    fragment.appendChild(thumb);
  }

  container.appendChild(fragment);
  showTemporaryMessage('Miniaturas geradas.');
}