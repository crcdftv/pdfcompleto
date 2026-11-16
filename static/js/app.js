// app.js – ponto de entrada da aplicação (type="module")

// -------------------- Imports de Store --------------------
import { store } from './store.js';

// -------------------- Imports de UI --------------------
import { initMenu } from './ui/menu.js';
import { initSearchBar } from './ui/searchBar.js';
import { initDragDropOverlay } from './ui/dragDropOverlay.js';
import { initSessoesIndicator } from './ui/sessoes.js';
import { showLoadingOverlay, hideLoadingOverlay, updateLoadingProgress } from './ui/loadingOverlay.js';
import { showTemporaryMessage } from './ui/toast.js';

// -------------------- Imports de PDF --------------------
import { uploadPDF } from './pdf/upload.js';
import { renderPDFLocal } from './pdf/render.js';
import { generateThumbnails } from './pdf/thumbnails.js';
import { convertPDFToSearchable } from './pdf/ocr.js';
import { comprimirPDF } from './pdf/compress.js';
import { convertPDFToExcel } from './pdf/excelConvert.js';
import { openSplitModal } from './pdf/split.js';
import { mergePDFs } from './pdf/merge.js';

// -------------------- Imports de Edição --------------------
import {
  toggleRedaction,
  desfazerUltimaTarja,
  initRedactionCanvas,
  sincronizarHistoricoRedacao
} from './edit/redaction.js';
import { rotatePageLeft, rotatePageRight } from './edit/rotation.js';
import { zoomIn, zoomOut } from './edit/zoom.js';
import { toggleTextMode, initTextTool } from './edit/text.js';
import { highlightActiveThumbnail } from './ui/thumbnailHighlight.js';

// -------------------- Imports de Assinatura --------------------
import { startSignatureWorkflow } from './signature/signPdf.js';

// Polling genérico de progresso de conversões
async function pollJobProgress(jobId, progressUrl) {
  const INTERVAL_MS = 500;
  const MAX_WAIT_MS = 30 * 60 * 1000; // 30 min de espera máxima
  const startedAt = Date.now();

  while (true) {
    await new Promise(r => setTimeout(r, INTERVAL_MS));

    if (Date.now() - startedAt > MAX_WAIT_MS) {
      hideLoadingOverlay();
      alert('Tempo esgotado: a conversão demorou mais de 30 minutos.');
      return null;
    }

    let data;
    try {
      const resp = await fetch(`${progressUrl}/${jobId}`);
      data = await resp.json();
    } catch (err) {
      hideLoadingOverlay();
      alert('Erro ao verificar progresso: ' + err.message);
      return null;
    }

    if (data.status === 'error') {
      hideLoadingOverlay();
      alert('Erro na conversão: ' + (data.msg || data.error || 'Erro desconhecido'));
      return null;
    }

    updateLoadingProgress(data.pct ?? 0, data.msg ?? 'Convertendo…');

    if (data.status === 'done') {
      hideLoadingOverlay();
      return data;
    }
  }
}

// ---------------------------------------------------------------
// Inicialização quando o DOM estiver pronto
// ---------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  // ====== Inicialização de módulos ======
  initMenu();
  initSearchBar();
  initDragDropOverlay();
  initSessoesIndicator();
  initRedactionCanvas();
  initTextTool();

  // ====== Scroll: destaca miniatura da página visível ======
  let scrollTimeout;
  window.addEventListener('scroll', () => {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
      let bestPage = null;
      let bestArea = 0;
      document.querySelectorAll('.page-container').forEach(container => {
        const rect = container.getBoundingClientRect();
        const visible = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
        if (visible > bestArea) {
          bestArea = visible;
          bestPage = parseInt(container.dataset.pageId);
        }
      });
      if (bestPage) {
        store.focusedPage = bestPage;
        highlightActiveThumbnail(bestPage);
      }
    }, 100);
  });

  // ====== Event Listeners dos Botões ======

  // --- Upload de PDF ---
const uploadBtn = document.getElementById('pdf-upload');
if (uploadBtn) {
  uploadBtn.addEventListener('change', async (event) => {
    // ⭐ CORREÇÃO: Passa o evento, não o arquivo
    await uploadPDF(event);
  });
} else {
  console.warn('⚠️ Botão "pdf-upload" não encontrado no DOM');
}

  // --- Juntar Páginas ---
  const mergeBtn = document.getElementById('merge-pages-btn');
  if (mergeBtn) {
    mergeBtn.addEventListener('click', () => {
      const fileInput = document.getElementById('pdfFiles');
      if (fileInput) {
        fileInput.click();
      } else {
        console.error('❌ Input "pdfFiles" não encontrado');
      }
    });
  }

  // Dispara mergePDFs quando o usuário seleciona os arquivos
  const pdfFilesInput = document.getElementById('pdfFiles');
  if (pdfFilesInput) {
    pdfFilesInput.addEventListener('change', async (event) => {
      await mergePDFs(event.target.files);
      event.target.value = ''; // limpa para permitir selecionar os mesmos arquivos depois
    });
  }

  // --- OCR ---
  const ocrBtn = document.getElementById('ocr-btn');
  if (ocrBtn) {
    ocrBtn.addEventListener('click', convertPDFToSearchable);
  }

  // --- Comprimir ---
  const compressBtn = document.getElementById('compress-pdf-btn');
  if (compressBtn) {
    compressBtn.addEventListener('click', comprimirPDF);
  }

  // --- Salvar PDF Editado ---
const saveBtn = document.getElementById('save-pdf-btn');
if (saveBtn) {
  saveBtn.addEventListener('click', async () => {
    try {
      // Garante que o backend tenha o mesmo histórico de tarjas da tela.
      await sincronizarHistoricoRedacao();

      // Verifica se há PDF carregado
      if (!store.currentPdfPath && !store.pdfUrl) {
        alert('Nenhum PDF carregado!');
        return;
      }

      // ⭐ IMPORTANTE: O backend espera APENAS O NOME DO ARQUIVO
      // Exemplo: "1769165203894_arquivo.pdf" (sem /uploads/)
      let pdfFileName = store.currentPdfPath || store.pdfUrl;

      // Remove prefixos como /uploads/ ou /ocr_outputs/
      if (pdfFileName.startsWith('/uploads/')) {
        pdfFileName = pdfFileName.replace('/uploads/', '');
      } else if (pdfFileName.startsWith('/ocr_outputs/')) {
        pdfFileName = pdfFileName.replace('/ocr_outputs/', '');
      }

      // Monta os dados para enviar ao backend
      const payload = {
        pdf_files: [pdfFileName],
        edits: {
          tarjas: store.pdfEdits.tarjas || [],
          texts: store.texts || []
        },
        page_order: store.pageOrder.length > 0 ? store.pageOrder : [],
        page_rotations: store.pageRotations || {},
        coords_origin: 'top-left'
      };

      // Mostra loading
      const originalText = saveBtn.textContent;
      saveBtn.textContent = 'Salvando...';
      saveBtn.disabled = true;

      const response = await fetch('/apply_edits', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      // Se erro, tenta ler como JSON para pegar a mensagem
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error || 'Erro ao salvar PDF');
      }

      // Resposta de sucesso é o próprio PDF em binário
      const blob = await response.blob();

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;

      // Nome do arquivo baseado no original
      const originalName = pdfFileName.split('_').slice(1).join('_') || 'documento.pdf';
      a.download = `editado_${originalName}`;

      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      alert('PDF salvo e baixado com sucesso!');

      // Restaura botão
      saveBtn.textContent = originalText;
      saveBtn.disabled = false;

    } catch (error) {
      console.error('❌ Erro ao salvar:', error);
      alert('Erro ao salvar o PDF: ' + error.message);

      // Restaura botão em caso de erro
      saveBtn.textContent = 'Salvar';
      saveBtn.disabled = false;
    }
  });
}

  // --- Separar Páginas ---
  const splitBtn = document.getElementById('split-pages-btn');
  if (splitBtn) {
    splitBtn.addEventListener('click', openSplitModal);
  }

  // --- Assinar ---
  const signBtn = document.getElementById('sign-pdf-btn');
  if (signBtn) {
    signBtn.addEventListener('click', startSignatureWorkflow);
  }

  // --- Zoom ---
  const zoomInBtn = document.getElementById('zoom-in-btn');
  if (zoomInBtn) {
    zoomInBtn.addEventListener('click', zoomIn);
  }

  const zoomOutBtn = document.getElementById('zoom-out-btn');
  if (zoomOutBtn) {
    zoomOutBtn.addEventListener('click', zoomOut);
  }

  // --- Rotação ---
  const rotateLeftBtn = document.getElementById('rotate-left-btn');
  if (rotateLeftBtn) {
    rotateLeftBtn.addEventListener('click', rotatePageLeft);
  }

  const rotateRightBtn = document.getElementById('rotate-right-btn');
  if (rotateRightBtn) {
    rotateRightBtn.addEventListener('click', rotatePageRight);
  }

  // --- Tarja (Redaction) ---
  const toggleRedactionBtn = document.getElementById('toggle-redaction-btn');
  if (toggleRedactionBtn) {
    toggleRedactionBtn.addEventListener('click', toggleRedaction);
  }

  const undoRedactionBtn = document.getElementById('undo-redaction-btn');
  if (undoRedactionBtn) {
    undoRedactionBtn.addEventListener('click', desfazerUltimaTarja);
  }

  // --- Texto ---
  const textBtn = document.getElementById('toggle-text-btn');
  if (textBtn) {
    textBtn.addEventListener('click', toggleTextMode);
  }

  // --- PDF para Word ---
  const pdfToWordBtn = document.getElementById('pdf-to-word-btn');
  if (pdfToWordBtn) {
    pdfToWordBtn.addEventListener('click', async () => {
      try {
        if (!store.currentPdfPath) {
          alert('Nenhum PDF carregado!');
          return;
        }

        showLoadingOverlay('Convertendo para Word…');

        const response = await fetch('/convert-to-word', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: store.currentPdfPath })
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || 'Erro ao converter para Word');
        }

        const { job_id: jobId } = await response.json();
        if (!jobId) throw new Error('Falha ao iniciar conversão');

        const result = await pollJobProgress(jobId, '/convert-to-word/progress');
        if (!result) return;

        // Download nativo via link (funciona com arquivos grandes no QWebEngineView)
        const nomeBase = (store.currentPdfPath.split('/').pop() || 'documento')
          .replace(/^\d+_/, '')
          .replace(/\.pdf$/i, '');
        const a = document.createElement('a');
        a.href = `/convert-to-word/download/${jobId}`;
        a.download = `${nomeBase || 'documento'}.docx`;
        a.target = '_blank';
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => a.remove(), 500);

        showTemporaryMessage('✅ Arquivo Word gerado com sucesso!');
      } catch (error) {
        console.error('❌ Erro ao converter para Word:', error);
        hideLoadingOverlay();
        alert('Erro ao converter para Word: ' + error.message);
      }
    });
  }

  // --- PDF para Excel ---
  const pdfToExcelBtn = document.getElementById('pdf-to-excel-btn');
  if (pdfToExcelBtn) {
    pdfToExcelBtn.addEventListener('click', convertPDFToExcel);
  }

  // --- PDF para Imagem ---
  const pdfToImageBtn = document.getElementById('pdf-to-image-btn');
  if (pdfToImageBtn) {
    pdfToImageBtn.addEventListener('click', async () => {
      try {
        if (!store.pdfUrl) {
          alert('Nenhum PDF carregado!');
          return;
        }

        showLoadingOverlay('Convertendo para Imagem…');

        // Criar FormData e adicionar o PDF
        const formData = new FormData();

        // Buscar o arquivo PDF atual
        const pdfResponse = await fetch(store.pdfUrl);
        const pdfBlob = await pdfResponse.blob();
        formData.append('pdf', pdfBlob, 'documento.pdf');
        formData.append('format', 'png'); // ou 'jpg'
        formData.append('dpi', '200');

        const response = await fetch('/convert_pdf_to_image', {
          method: 'POST',
          body: formData
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || 'Erro ao converter para imagem');
        }

        const { job_id: jobId } = await response.json();
        if (!jobId) throw new Error('Falha ao iniciar conversão');

        const result = await pollJobProgress(jobId, '/convert_pdf_to_image/progress');
        if (!result) return;

        // Download nativo via link (funciona com arquivos grandes)
        const a = document.createElement('a');
        a.href = `/convert_pdf_to_image/download/${jobId}`;
        a.download = 'imagens.zip';
        a.target = '_blank';
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => a.remove(), 500);

        showTemporaryMessage('✅ Imagem gerada com sucesso!');
      } catch (error) {
        console.error('❌ Erro ao converter para Imagem:', error);
        hideLoadingOverlay();
        alert('Erro ao converter para Imagem: ' + error.message);
      }
    });
  }

  // --- Imagem para PDF ---
  const imageToPdfBtn = document.getElementById('image-to-pdf-btn');
  if (imageToPdfBtn) {
    imageToPdfBtn.addEventListener('click', () => {
      // Criar input de arquivo dinamicamente
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.multiple = true;

      input.addEventListener('change', async (event) => {
        const files = event.target.files;
        if (!files || files.length === 0) return;

        try {
          showLoadingOverlay('Convertendo imagens para PDF…');

          const formData = new FormData();
          for (let i = 0; i < files.length; i++) {
            formData.append('images', files[i]);
          }

          const response = await fetch('/convert/image-to-pdf', {
            method: 'POST',
            body: formData
          });

          if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || 'Erro ao converter imagens');
          }

          const blob = await response.blob();
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = 'resultado.pdf';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          window.URL.revokeObjectURL(url);

          hideLoadingOverlay();
          showTemporaryMessage('✅ PDF gerado com sucesso!');
        } catch (error) {
          console.error('❌ Erro ao converter imagens:', error);
          hideLoadingOverlay();
          alert('Erro ao converter imagens: ' + error.message);
        }
      });

      input.click();
    });
  }

  // ====== Auto-abrir PDF via ?file= na URL (desktop mode) ======
  const urlParams = new URLSearchParams(window.location.search);
  const fileParam = urlParams.get('file');
  if (fileParam) {
    (async () => {
      try {
        showLoadingOverlay('Carregando PDF…');
        const response = await fetch(`/uploads/${fileParam}`);
        if (!response.ok) throw new Error(`Erro ao buscar PDF: ${response.statusText}`);
        const blob = await response.blob();
        const file = new File([blob], fileParam, { type: 'application/pdf' });
        await uploadPDF(file);
      } catch (err) {
        console.error('❌ Erro ao auto-abrir PDF:', err);
        hideLoadingOverlay();
        showTemporaryMessage('Erro ao abrir PDF: ' + err.message, 'error');
      }
    })();
    // Limpa a URL sem recarregar a página
    window.history.replaceState({}, '', window.location.pathname);
  }
});

// Exportar store globalmente para debug (opcional, remova em produção)
window.APP_STORE = store;