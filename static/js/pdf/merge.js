// pdf/merge.js – junta múltiplos PDFs usando a rota /juntar_pdfs
import { store, setStore } from '../store.js';
import { showLoadingOverlay, hideLoadingOverlay } from '../ui/loadingOverlay.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { renderPDFLocal } from './render.js';
import { generateThumbnails } from './thumbnails.js';
import { openMergeOrderModal } from '../ui/mergeModal.js';

export async function mergePDFs(fileList) {
  if (!fileList || fileList.length < 2) {
    alert('Selecione pelo menos 2 PDFs para juntar.');
    return;
  }

  // ── 0) Abre o modal de reordenação e espera o usuário confirmar ──
  // O browser entrega arquivos de <input multiple> em ordem alfabética,
  // não na ordem de seleção — por isso a ordem precisa ser definida aqui.
  const orderedFiles = await openMergeOrderModal(Array.from(fileList));
  if (!orderedFiles) return; // usuário cancelou

  showLoadingOverlay(`Juntando ${orderedFiles.length} PDFs…`);

  try {
    // ── 1) Envia os arquivos na ordem confirmada pelo usuário ─────
    const form = new FormData();
    for (const file of orderedFiles) {
      form.append('pdfs', file);
    }
    form.append('nome', 'documento_juntado');
    // Ordem explícita: o backend usará isso para ordenar, ignorando
    // a ordem de entrega do multipart (imprevisível entre browsers).
    form.append('file_order', orderedFiles.map(f => f.name).join(','));

    const resp = await fetch('/juntar_pdfs', { method: 'POST', body: form });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || 'Erro ao juntar PDFs');
    }

    // ── 2) Faz upload do blob mesclado e inicializa a sessão correta ──
    showLoadingOverlay('Processando resultado…');

    const blob = await resp.blob();
    const mergedFile = new File([blob], 'documento_juntado.pdf', { type: 'application/pdf' });

    const uploadForm = new FormData();
    uploadForm.append('pdf', mergedFile);

    const uploadResp = await fetch('/upload', { method: 'POST', body: uploadForm });
    if (!uploadResp.ok) throw new Error('Erro ao carregar PDF mesclado');
    const uploadJson = await uploadResp.json();

    // Inicializa a sessão Flask com o arquivo mesclado recém-enviado.
    // Garante que /apply_edits (Salvar) use o PDF correto.
    const sessionResp = await fetch('/init_merged_session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: [uploadJson.file_path] })
    });
    if (!sessionResp.ok) throw new Error('Erro ao inicializar sessão do PDF mesclado');

    // ── 3) Abre o PDF mesclado no PDF.js ─────────────────────────
    showLoadingOverlay('Renderizando páginas…');

    const arrayBuf = await blob.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: arrayBuf }).promise;

    setStore('currentPdfPath', uploadJson.file_path);
    setStore('pdfUrl',         uploadJson.file_url);
    setStore('pdfDoc',         pdf);
    setStore('pageOrder',      Array.from({ length: pdf.numPages }, (_, i) => i + 1));
    setStore('pageRotations',  {});
    if (store.pdfEdits) store.pdfEdits.tarjas = [];

    // ── 4) Monta pageMappings ─────────────────────────────────────
    const mappings = {};
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const vp   = page.getViewport({ scale: store.currentScale || 1.5, rotation: 0 });
      mappings[i] = {
        pdfDoc:          pdf,
        pageInDoc:       i,
        canvasWidth:     vp.width,
        canvasHeight:    vp.height,
        pdfWidthPoints:  page.view[2],
        pdfHeightPoints: page.view[3],
      };
    }
    setStore('pageMappings', mappings);

    // ── 5) Reconstrói containers HTML ─────────────────────────────
    const pdfRender = document.getElementById('pdf-render');
    pdfRender.innerHTML = '';
    for (let i = 1; i <= pdf.numPages; i++) {
      const div = document.createElement('div');
      div.className = 'page-container';
      div.setAttribute('data-page-id', i);
      div.setAttribute('data-page-number', i);
      div.innerHTML = `
        <canvas class="pdf-canvas"></canvas>
        <canvas class="draw-canvas"></canvas>
        <div class="text-layer"></div>
      `;
      pdfRender.appendChild(div);
    }

    // ── 6) Renderiza e miniaturas ─────────────────────────────────
    await renderPDFLocal(store.currentScale || 1.5);

    showLoadingOverlay('Gerando miniaturas…');
    await generateThumbnails();

    hideLoadingOverlay();
    showTemporaryMessage(`✅ ${orderedFiles.length} PDFs juntados — ${pdf.numPages} páginas no total.`);

  } catch (error) {
    console.error('❌ Erro ao juntar PDFs:', error);
    hideLoadingOverlay();
    alert('Erro ao juntar PDFs: ' + error.message);
  }
}