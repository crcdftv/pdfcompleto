// pdf/excelConvert.js – Conversão PDF → Excel com progresso em tempo real

import { store } from '../store.js';
import { showTemporaryMessage } from '../ui/toast.js';

function openExcelModal() {
  return new Promise((resolve) => {
    const modal      = document.getElementById('excelModal');
    const confirmBtn = document.getElementById('excel-modal-confirm');
    const cancelBtn  = document.getElementById('excel-modal-cancel');
    const warning    = document.getElementById('excel-warning-slow');
    const progressArea = document.getElementById('excel-progress-area');
    const qLabels    = { fast: document.getElementById('excel-q-fast'), quality: document.getElementById('excel-q-quality') };

    // Reset estado
    progressArea.style.display = 'none';
    confirmBtn.disabled        = false;
    confirmBtn.textContent     = 'Converter';
    modal.style.display        = 'flex';

    function highlightQuality() {
      const val = modal.querySelector('input[name="excel-quality"]:checked')?.value;
      qLabels.fast.style.borderColor    = val === 'fast'    ? '#1D6F42' : '#e0e0e0';
      qLabels.fast.style.background     = val === 'fast'    ? '#f0faf4' : '#fff';
      qLabels.quality.style.borderColor = val === 'quality' ? '#1D6F42' : '#e0e0e0';
      qLabels.quality.style.background  = val === 'quality' ? '#f0faf4' : '#fff';
      warning.style.display             = val === 'quality' ? 'block'   : 'none';
    }
    modal.querySelectorAll('input[name="excel-quality"]')
         .forEach(r => r.addEventListener('change', highlightQuality));
    highlightQuality();

    function cleanup() {
      modal.style.display = 'none';
      confirmBtn.removeEventListener('click', onConfirm);
      cancelBtn.removeEventListener('click',  onCancel);
    }

    function onConfirm() {
      const quality = modal.querySelector('input[name="excel-quality"]:checked')?.value || 'fast';
      cleanup();
      resolve(quality);
    }
    function onCancel() { cleanup(); resolve(null); }

    confirmBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click',  onCancel);
  });
}

function showProgress(pct, msg) {
  const area = document.getElementById('excel-progress-area');
  if (!area) return;
  area.style.display = 'block';
  document.getElementById('excel-progress-bar').style.width = pct + '%';
  document.getElementById('excel-progress-pct').textContent = pct + '%';
  document.getElementById('excel-progress-msg').textContent = msg || '';
}

async function pollProgress(jobId, onUpdate) {
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const res  = await fetch(`/convert/pdf-to-excel/progress/${jobId}`);
        const data = await res.json();
        onUpdate(data.pct, data.msg);
        if (data.status === 'done')   { clearInterval(interval); resolve();          }
        if (data.status === 'error')  { clearInterval(interval); reject(new Error(data.msg)); }
      } catch (e) {
        clearInterval(interval);
        reject(e);
      }
    }, 800);
  });
}

export async function convertPDFToExcel() {
  const quality = await openExcelModal();
  if (!quality) return;

  // Reabre modal só para mostrar progresso
  const modal = document.getElementById('excelModal');
  modal.style.display = 'flex';
  document.getElementById('excel-modal-confirm').disabled    = true;
  document.getElementById('excel-modal-confirm').textContent = 'Convertendo…';
  document.getElementById('excel-modal-cancel').disabled     = true;
  document.getElementById('excel-progress-area').style.display = 'block';
  showProgress(0, 'Iniciando…');

  try {
    if (!store.currentPdfPath) throw new Error('Nenhum PDF carregado!');

    // Inicia conversão — retorna job_id imediatamente
    const startRes = await fetch('/convert/pdf-to-excel', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ filename: store.currentPdfPath, quality })
    });

    if (!startRes.ok) {
      const err = await startRes.json().catch(() => ({}));
      throw new Error(err.error || `Erro ${startRes.status}`);
    }

    const { job_id, filename } = await startRes.json();

    // Polling de progresso
    await pollProgress(job_id, (pct, msg) => showProgress(pct, msg));

    // Download direto via link (evita blob: URLs e o aviso de conexão insegura)
    showProgress(100, 'Baixando arquivo…');
    const a = document.createElement('a');
    a.href     = `/convert/pdf-to-excel/download/${job_id}`;
    a.download = filename || 'resultado.xlsx';
    a.target   = '_blank';
    a.rel      = 'noopener';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 500);

    modal.style.display = 'none';
    showTemporaryMessage('✅ Excel gerado com sucesso!');

  } catch (error) {
    console.error('❌ Erro Excel:', error);
    modal.style.display = 'none';
    alert('Erro ao converter: ' + error.message);
  } finally {
    // Re-enable botões para próxima vez
    document.getElementById('excel-modal-confirm').disabled    = false;
    document.getElementById('excel-modal-confirm').textContent = 'Converter';
    document.getElementById('excel-modal-cancel').disabled     = false;
    document.getElementById('excel-progress-area').style.display = 'none';
  }
}