// pdf/upload.js
import { store, setStore } from '../store.js';
import { showLoadingOverlay, hideLoadingOverlay, updateLoadingProgress } from '../ui/loadingOverlay.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { iniciarSessaoRedacao } from './session.js';
import { renderPDFLocal } from './render.js';
import { generateThumbnails } from './thumbnails.js';

export async function uploadPDF(eventOrFile = null) {
  if (store.pdfEdits) store.pdfEdits.tarjas = [];

  // ── obtém o File ──────────────────────────────────────────────
  let file = null;
  if (eventOrFile instanceof Event) {
    file = eventOrFile.target?.files?.[0];
  } else if (eventOrFile instanceof File) {
    file = eventOrFile;
  } else {
    file = document.getElementById('pdf-upload')?.files?.[0];
  }

  if (!file) { alert('Nenhum arquivo selecionado.'); return; }
  if (file.type !== 'application/pdf') { alert('Selecione um arquivo PDF válido.'); return; }

  showLoadingOverlay('Carregando PDF…');

  try {
    // ── 1) Lê o arquivo localmente — sem precisar baixar de volta ──
    updateLoadingProgress(10, 'Lendo arquivo…');
    const arrayBuf = await file.arrayBuffer();

    // ── 2) Upload pro servidor em paralelo (não bloqueia renderização) ──
    const uploadPromise = (async () => {
      const form = new FormData();
      form.append('pdf', file);
      const resp = await fetch('/upload', { method: 'POST', body: form });
      if (!resp.ok) throw new Error(`Upload falhou: ${await resp.text()}`);
      const json = await resp.json();
      setStore('currentPdfPath', json.file_path);
      setStore('pdfUrl', json.file_url);
      await iniciarSessaoRedacao(json.file_url);
    })();

    // ── 3) Abre com PDF.js usando o buffer local ───────────────────
    updateLoadingProgress(25, 'Interpretando PDF…');
    if (!window.pdfjsLib) throw new Error('PDF.js não está carregado!');
    const loadingTask = pdfjsLib.getDocument({ data: arrayBuf });
    loadingTask.onProgress = (p) => {
      const pct = 25 + Math.round((p.loaded / p.total) * 15);
      updateLoadingProgress(pct, 'Interpretando PDF…');
    };
    const pdf = await loadingTask.promise;

    setStore('pdfDoc', pdf);
    setStore('pageOrder', Array.from({ length: pdf.numPages }, (_, i) => i + 1));

    // ── 4) Cria containers HTML ────────────────────────────────────
    updateLoadingProgress(45, 'Preparando páginas…');
    const pdfRender = document.getElementById('pdf-render');
    if (!pdfRender) throw new Error('Elemento #pdf-render não encontrado!');
    pdfRender.innerHTML = '';

    const fragment = document.createDocumentFragment();
    for (let i = 1; i <= pdf.numPages; i++) {
      const container = document.createElement('div');
      container.className = 'page-container';
      container.setAttribute('data-page-id', i);
      container.setAttribute('data-page-number', i);
      container.innerHTML = `
        <canvas class="pdf-canvas"></canvas>
        <canvas class="draw-canvas"></canvas>
        <div class="text-layer"></div>
      `;
      fragment.appendChild(container);
    }
    pdfRender.appendChild(fragment);

    // ── 5) Mapeamento em paralelo ──────────────────────────────────
    updateLoadingProgress(60, 'Mapeando páginas…');
    const scale = store.currentScale || 1.5;
    const mappingEntries = await Promise.all(
      store.pageOrder.map(async id => {
        const page = await pdf.getPage(id);
        const vp = page.getViewport({ scale, rotation: 0 });
        return [id, {
          pdfDoc: pdf,
          pageInDoc: id,
          canvasWidth: vp.width,
          canvasHeight: vp.height,
          pdfWidthPoints: page.view[2],
          pdfHeightPoints: page.view[3]
        }];
      })
    );
    setStore('pageMappings', Object.fromEntries(mappingEntries));

    // ── 6) Renderiza páginas visíveis imediatamente ────────────────
    updateLoadingProgress(80, 'Renderizando páginas…');
    await renderPDFLocal(scale);

    hideLoadingOverlay();
    showTemporaryMessage('PDF carregado com sucesso!');

    // ── 7) Miniaturas em background — não bloqueia o usuário ───────
    generateThumbnails().catch(console.error);

    // ── 8) Aguarda upload terminar em background ───────────────────
    uploadPromise.catch(e => {
      console.error('Erro no upload para o servidor:', e);
      showTemporaryMessage('Aviso: falha ao salvar no servidor.', 'error');
    });

  } catch (error) {
    console.error('❌ Erro no upload:', error);
    hideLoadingOverlay();
    showTemporaryMessage('Erro ao carregar PDF: ' + error.message, 'error');
    alert('Erro ao carregar PDF: ' + error.message);
  }
}