// pdf/ocr.js – inicia a conversão OCR e acompanha o progresso
import { store, setStore } from '../store.js';
import { showLoadingOverlay, hideLoadingOverlay, updateLoadingProgress } from '../ui/loadingOverlay.js';
import { showTemporaryMessage } from '../ui/toast.js';

export async function convertPDFToSearchable() {
  if (!store.currentPdfPath) {
    alert('Carregue um PDF antes de iniciar OCR.');
    return;
  }

  const filename = store.currentPdfPath.split('/').pop();

  const btn = document.getElementById('ocr-btn');
  const originalHtml = btn ? btn.innerHTML : null;
  if (btn) btn.disabled = true;

  showLoadingOverlay('Iniciando OCR…');

  const resp = await fetch('/convert_pdf_to_searchable', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pdf_path: filename })
  });

  const data = await resp.json();
  if (!resp.ok) {
    hideLoadingOverlay();
    if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
    alert(`Erro ao iniciar OCR: ${data.error || resp.status}`);
    return;
  }

  setStore('conversionId', data.conversion_id);
  pollOcrProgress(data.ocr_pdf_path, btn, originalHtml);
}

async function pollOcrProgress(ocrPdfPath, btn, originalHtml) {
  const convId = store.conversionId;
  let attempts = 0;
  const max = 300;

  const interval = setInterval(async () => {
    attempts++;
    try {
      const resp = await fetch(`/conversion_progress/${convId}`);
      if (!resp.ok) throw new Error(`Status ${resp.status}`);

      const prog = await resp.json();
      const page = prog.current_page && prog.total_pages
        ? ` (${prog.current_page}/${prog.total_pages})`
        : '';
      updateLoadingProgress(prog.percentage || 0, `OCR em andamento…${page}`);

      if (prog.status === 'completed') {
        clearInterval(interval);
        hideLoadingOverlay();
        if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
        window.open(ocrPdfPath, '_blank');
        showTemporaryMessage('✅ OCR concluído! PDF aberto em nova aba.');
      } else if (prog.status === 'error') {
        throw new Error(prog.error || 'Erro desconhecido');
      } else if (attempts >= max) {
        throw new Error('Timeout – OCR demorou demais');
      }
    } catch (e) {
      clearInterval(interval);
      hideLoadingOverlay();
      if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
      alert(`Erro ao acompanhar OCR: ${e.message}`);
    }
  }, 1000);
}