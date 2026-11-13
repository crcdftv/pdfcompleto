// signature/signPdf.js – desenha a caixa de assinatura e envia ao backend
import { store } from '../store.js';
import { openTokenDialog } from './tokenDialog.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { canvasToPdf } from '../utils/coords.js';
import { renderSinglePage } from '../pdf/render.js';

/* -------------------------------------------------------------- */
export async function startSignatureWorkflow() {
  if (!store.pdfUrl) {
    alert('Carregue um PDF antes de assinar.');
    return;
  }

  await openTokenDialog(async ({ label, pin }) => {
    store.storedPin = pin;
    store.assinaturaTexto = `Assinado Digitalmente\n${label}`;

    iniciarDesenhoDaAssinatura();
    showTemporaryMessage('Selecione a área da assinatura.');
  });
}

/* -------------------------------------------------------------- */
export function iniciarDesenhoDaAssinatura() {
  if (!store.focusedPage) {
    alert('Clique em uma página antes de desenhar a assinatura.');
    return;
  }

  const pageContainer = document.querySelector(`.page-container[data-page-id="${store.focusedPage}"]`);
  if (!pageContainer) {
    alert('Container da página não encontrado.');
    return;
  }

  // Remove overlay anterior se existir
  document.getElementById('signature-draw-overlay')?.remove();

  // Cria um overlay transparente que cobre TODA a página
  // Isso evita que o clique caia na camada de texto do PDF (que causa seleção de texto)
  const overlay = document.createElement('div');
  overlay.id = 'signature-draw-overlay';
  Object.assign(overlay.style, {
    position:      'absolute',
    inset:         '0',          // cobre 100% da página (top/right/bottom/left = 0)
    zIndex:        '10000',
    cursor:        'crosshair',
    userSelect:    'none',
    WebkitUserSelect: 'none',
  });
  pageContainer.style.position = 'relative'; // garante que o absolute funcione
  pageContainer.appendChild(overlay);

  let rectEl = null;
  let start  = null;

  const onDown = e => {
    e.preventDefault();
    const r = overlay.getBoundingClientRect();
    start = { x: e.clientX - r.left, y: e.clientY - r.top };

    rectEl = document.createElement('div');
    rectEl.id = 'signature-rect';
    Object.assign(rectEl.style, {
      position:   'absolute',
      border:     '2px dashed red',
      background: 'rgba(255,0,0,0.1)',
      zIndex:     '10001',
      pointerEvents: 'none',
    });
    overlay.appendChild(rectEl);
  };

  const onMove = e => {
    if (!start || !rectEl) return;
    const r   = overlay.getBoundingClientRect();
    const cur = { x: e.clientX - r.left, y: e.clientY - r.top };
    const x = Math.min(start.x, cur.x);
    const y = Math.min(start.y, cur.y);
    const w = Math.abs(cur.x - start.x);
    const h = Math.abs(cur.y - start.y);
    Object.assign(rectEl.style, {
      left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px`,
    });
  };

  const onUp = async e => {
    overlay.removeEventListener('mousedown', onDown);
    overlay.removeEventListener('mousemove', onMove);
    overlay.removeEventListener('mouseup',   onUp);

    const r     = overlay.getBoundingClientRect();
    const final = { x: e.clientX - r.left, y: e.clientY - r.top };
    const x = Math.min(start.x, final.x);
    const y = Math.min(start.y, final.y);
    const w = Math.abs(final.x - start.x);
    const h = Math.abs(final.y - start.y);

    // Remove overlay e retângulo visual
    overlay.remove();
    window.getSelection()?.removeAllRanges();

    if (w < 5 || h < 5) {
      alert('Área muito pequena. Tente novamente.');
      return;
    }

    // Converte coordenadas do overlay (= coordenadas da página) para PDF
    const { x: pdfX, y: pdfY, w: pdfW, h: pdfH } = canvasToPdf(store.focusedPage, {
      x, y, w, h
    });

    const pageZero = store.focusedPage - 1;

    const payload = {
      filename:         store.currentPdfPath,
      pin:              store.storedPin,
      assinatura_texto: store.assinaturaTexto,
      signature_x:      pdfX,
      signature_y:      pdfY,
      signature_width:  pdfW,
      signature_height: pdfH,
      page_num:         pageZero,
    };

    const resp = await fetch('/assinar_pdf_area_texto', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    const data = await resp.json();
    if (resp.ok) {
      showTemporaryMessage('PDF assinado com sucesso!');
      window.open(data.signed_pdf_path, '_blank');
    } else {
      alert(`Erro ao assinar: ${data.error || 'desconhecido'}`);
    }
  };

  overlay.addEventListener('mousedown', onDown);
  overlay.addEventListener('mousemove', onMove);
  overlay.addEventListener('mouseup',   onUp);
}