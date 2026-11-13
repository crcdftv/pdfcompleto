// pdf/compress.js – comprime qualquer PDF com barra de progresso real
import { store } from '../store.js';
import { showLoadingOverlay, hideLoadingOverlay, updateLoadingProgress } from '../ui/loadingOverlay.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { openCompressModal, openCompressWarningModal } from '../ui/compressModal.js';

export async function comprimirPDF() {

  // ── 1) Obtém o arquivo ────────────────────────────────────────────
  let file      = null;
  let inputPath = null;
  const useLoaded = !!store.currentPdfPath;

  if (useLoaded) {
    inputPath = store.currentPdfPath;
  } else {
    file = await _askUserForPdf();
    if (!file) return;
  }

  // ── 2) Modal de nível de compressão ──────────────────────────────
  let nivel = await openCompressModal();
  if (!nivel) return;

  // ── 2b) Se escolheu alvo, dispara rota de target size ────────────
  if (typeof nivel === 'object' && nivel.target_size_mb) {
    if (useLoaded) {
      await _comprimirPorAlvo(inputPath, nivel.target_size_mb);
    } else {
      await _comprimirPorUploadAlvo(file, nivel.target_size_mb);
    }
    return;
  }

  // ── 3) Dispara compressão pelo caminho correto ────────────────────
  if (useLoaded) {
    await _comprimirPorCaminho(inputPath, nivel);
  } else {
    await _comprimirPorUpload(file, nivel);
  }
}

/* ── Fluxo A: PDF já carregado na interface ──────────────────────── */
async function _comprimirPorCaminho(inputPath, nivelInicial) {
  let nivel = nivelInicial;

  while (nivel) {
    const outputPath   = inputPath.replace(/^uploads[\\/]/, 'compressed/');
    const nomeOriginal = inputPath.split('/').pop().replace(/^\d+_/, '');
    const nomeSugerido = _nomeSugerido(nomeOriginal);

    showLoadingOverlay('Iniciando compressão…');
    let jobId;
    try {
      const resp = await fetch('/comprimir_pdf', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_pdf_path:  inputPath,
          output_pdf_path: outputPath,
          quality:         nivel,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        hideLoadingOverlay();
        alert('Erro ao iniciar compressão: ' + (data.message || data.error));
        return;
      }
      jobId = data.job_id;
    } catch (err) {
      hideLoadingOverlay();
      alert('Erro de conexão: ' + err.message);
      return;
    }

    const result = await _pollProgress(jobId);
    if (!result) return;

    if (result.reduction_percent <= 0) {
      const proximo = await openCompressWarningModal(result.reduction_percent, nivel);
      if (proximo === false) {
        _baixarESalvar(jobId, nomeSugerido);
        showTemporaryMessage('⚠️ PDF baixado — arquivo não foi reduzido.');
        return;
      }
      nivel = proximo;
      continue;
    }

    const engineLabels = {
      'pymupdf': ' (PyMuPDF)'
    };
    const engineMsg = engineLabels[result.engine] || '';
    showTemporaryMessage(
      '✅ Reduzido em ' + result.reduction_percent + '% ' +
      '(' + result.original_size_mb + ' MB → ' + result.compressed_size_mb + ' MB)' +
      engineMsg
    );
    _baixarESalvar(jobId, nomeSugerido);
    return;
  }
}

/* ── Fluxo B: PDF selecionado direto do disco ────────────────────── */
async function _comprimirPorUpload(file, nivelInicial) {
  let nivel = nivelInicial;
  const nomeSugerido = _nomeSugerido(file.name);

  while (nivel) {
    showLoadingOverlay('Enviando PDF…');
    let jobId;
    try {
      const form = new FormData();
      form.append('pdf', file);
      form.append('quality', nivel);

      const resp = await fetch('/comprimir_pdf_upload', { method: 'POST', body: form });
      const data = await resp.json();
      if (!resp.ok) {
        hideLoadingOverlay();
        alert('Erro ao iniciar compressão: ' + (data.message || data.error));
        return;
      }
      jobId = data.job_id;
    } catch (err) {
      hideLoadingOverlay();
      alert('Erro de conexão: ' + err.message);
      return;
    }

    const result = await _pollProgress(jobId);
    if (!result) return;

    if (result.reduction_percent <= 0) {
      const proximo = await openCompressWarningModal(result.reduction_percent, nivel);
      if (proximo === false) {
        _baixarESalvar(jobId, nomeSugerido);
        showTemporaryMessage('⚠️ PDF baixado — arquivo não foi reduzido.');
        return;
      }
      nivel = proximo;
      continue;
    }

    const engineLabels = {
      'pymupdf': ' (PyMuPDF)'
    };
    const engineMsg = engineLabels[result.engine] || '';
    showTemporaryMessage(
      '✅ Reduzido em ' + result.reduction_percent + '% ' +
      '(' + result.original_size_mb + ' MB → ' + result.compressed_size_mb + ' MB)' +
      engineMsg
    );
    _baixarESalvar(jobId, nomeSugerido);
    return;
  }
}

/* ── Polling: consulta o backend até status done ou error ─────────── */
async function _pollProgress(jobId) {
  const INTERVAL_MS = 400;

  while (true) {
    await _sleep(INTERVAL_MS);

    let data;
    try {
      const resp = await fetch('/comprimir_pdf/progress/' + jobId);
      data = await resp.json();
    } catch (err) {
      hideLoadingOverlay();
      alert('Erro ao verificar progresso: ' + err.message);
      return null;
    }

    updateLoadingProgress(data.pct ?? 0, data.msg ?? 'Processando…');

    if (data.status === 'error') {
      hideLoadingOverlay();
      alert('Erro na compressão: ' + (data.msg || 'Erro desconhecido'));
      return null;
    }

    if (data.status === 'done') {
      hideLoadingOverlay();
      return data;
    }
  }
}

/* ── Dispara o download apontando direto para a URL do servidor ──────
 *
 *  NÃO usa fetch() + blob() nem showSaveFilePicker — ambos bloqueiam
 *  o JS ou não funcionam no QWebEngineView com arquivos grandes.
 *
 *  Cria um <a href="/comprimir_pdf/download/jobId"> e clica:
 *  o browser gerencia o download nativamente e abre a caixa "Salvar
 *  como…" do sistema operacional sem travar o JS.
 * ──────────────────────────────────────────────────────────────────── */
function _baixarESalvar(jobId, nomeSugerido) {
  const a   = document.createElement('a');
  a.href     = '/comprimir_pdf/download/' + jobId;
  a.download = nomeSugerido;
  a.target   = '_blank';
  a.rel      = 'noopener';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => a.remove(), 500);
}

/* ── Helpers ─────────────────────────────────────────────────────── */
function _askUserForPdf() {
  return new Promise(resolve => {
    const inp = document.createElement('input');
    inp.type     = 'file';
    inp.accept   = 'application/pdf';
    inp.onchange = () => resolve(inp.files[0] || null);
    inp.oncancel = () => resolve(null);
    inp.click();
  });
}

function _nomeSugerido(nomeOriginal) {
  const semTimestamp = nomeOriginal.replace(/^\d+_/, '');
  return semTimestamp.replace(/\.pdf$/i, '_comprimido.pdf') || 'documento_comprimido.pdf';
}

/* ── Fluxo C: compressão com tamanho alvo ──────────────────────────── */

async function _comprimirPorAlvo(inputPath, targetSizeMb) {
  const outputPath   = inputPath.replace(/^uploads[\\/]/, 'compressed/');
  const nomeOriginal = inputPath.split('/').pop().replace(/^\d+_/, '');
  const nomeSugerido = nomeOriginal.replace(/\.pdf$/i, `_${targetSizeMb}mb.pdf`) || `documento_${targetSizeMb}mb.pdf`;

  showLoadingOverlay(`Comprimindo para ≤ ${targetSizeMb} MB…`);
  let jobId;
  try {
    const resp = await fetch('/comprimir_pdf_target', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_pdf_path:  inputPath,
        output_pdf_path: outputPath,
        target_size_mb:  targetSizeMb,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      hideLoadingOverlay();
      alert('Erro ao iniciar compressão alvo: ' + (data.message || data.error));
      return;
    }
    jobId = data.job_id;
  } catch (err) {
    hideLoadingOverlay();
    alert('Erro de conexão: ' + err.message);
    return;
  }

  const result = await _pollProgress(jobId);
  if (!result) return;

  showTemporaryMessage(
    '✅ Comprimido: ' + result.original_size_mb + ' MB → ' + result.compressed_size_mb + ' MB' +
    (result.reduction_percent > 0 ? ` (${result.reduction_percent}% redução)` : '')
  );
  _baixarESalvar(jobId, nomeSugerido);
}

async function _comprimirPorUploadAlvo(file, targetSizeMb) {
  const nomeSugerido = file.name.replace(/\.pdf$/i, `_${targetSizeMb}mb.pdf`) || `documento_${targetSizeMb}mb.pdf`;

  showLoadingOverlay('Enviando PDF…');
  let jobId;
  try {
    const form = new FormData();
    form.append('pdf', file);
    form.append('target_size_mb', targetSizeMb);

    const resp = await fetch('/comprimir_pdf_upload_target', { method: 'POST', body: form });
    const data = await resp.json();
    if (!resp.ok) {
      hideLoadingOverlay();
      alert('Erro ao iniciar compressão alvo: ' + (data.message || data.error));
      return;
    }
    jobId = data.job_id;
  } catch (err) {
    hideLoadingOverlay();
    alert('Erro de conexão: ' + err.message);
    return;
  }

  const result = await _pollProgress(jobId);
  if (!result) return;

  showTemporaryMessage(
    '✅ Comprimido: ' + result.original_size_mb + ' MB → ' + result.compressed_size_mb + ' MB' +
    (result.reduction_percent > 0 ? ` (${result.reduction_percent}% redução)` : '')
  );
  _baixarESalvar(jobId, nomeSugerido);
}

function _sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}