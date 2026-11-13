// pdf/split.js – divide PDF por intervalos de páginas definidos pelo usuário
import { store } from '../store.js';
import { showLoadingOverlay, hideLoadingOverlay } from '../ui/loadingOverlay.js';
import { showTemporaryMessage } from '../ui/toast.js';

export function openSplitModal() {
  if (!store.currentPdfPath && !store.pdfUrl) {
    alert('Nenhum PDF carregado!');
    return;
  }

  const totalPages = store.pdfDoc ? store.pdfDoc.numPages : '?';
  _injectStyles();

  // Estado: lista de intervalos
  let intervals = [{ start: 1, end: totalPages === '?' ? 1 : totalPages }];

  const backdrop = document.createElement('div');
  backdrop.id = 'split-backdrop';

  function buildHTML() {
    return `
      <div id="split-modal">
        <h2>✂️ Dividir PDF</h2>
        <p class="sp-subtitle">
          PDF com <strong>${totalPages} páginas</strong>. Defina os intervalos que deseja separar.
          Cada intervalo vira um PDF dentro de um ZIP.
        </p>

        <div id="sp-intervals">
          ${intervals.map((iv, idx) => `
            <div class="sp-row" data-idx="${idx}">
              <span class="sp-num">${idx + 1}</span>
              <label class="sp-label">Página</label>
              <input class="sp-input sp-start" type="number" min="1" max="${totalPages}" value="${iv.start}" />
              <label class="sp-label">até</label>
              <input class="sp-input sp-end"   type="number" min="1" max="${totalPages}" value="${iv.end}"   />
              <button class="sp-remove" data-idx="${idx}" title="Remover">🗑</button>
            </div>
          `).join('')}
        </div>

        <button id="sp-add">＋ Adicionar intervalo</button>

        <div class="sp-btn-row">
          <button id="sp-cancel">Cancelar</button>
          <button id="sp-confirm">Dividir e baixar ZIP ✓</button>
        </div>
      </div>
    `;
  }

  function render() {
    backdrop.innerHTML = buildHTML();
    attachEvents();
  }

  function attachEvents() {
    // Atualiza estado quando inputs mudam
    backdrop.querySelectorAll('.sp-row').forEach(row => {
      const idx = parseInt(row.dataset.idx);
      row.querySelector('.sp-start').addEventListener('input', e => {
        intervals[idx].start = parseInt(e.target.value) || 1;
      });
      row.querySelector('.sp-end').addEventListener('input', e => {
        intervals[idx].end = parseInt(e.target.value) || 1;
      });
    });

    // Remover intervalo
    backdrop.querySelectorAll('.sp-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.idx);
        if (intervals.length === 1) {
          showTemporaryMessage('⚠️ Precisa ter pelo menos um intervalo.', 'warning');
          return;
        }
        intervals.splice(idx, 1);
        render();
      });
    });

    // Adicionar intervalo
    backdrop.querySelector('#sp-add').addEventListener('click', () => {
      const last = intervals[intervals.length - 1];
      const nextStart = (last.end || 1) + 1;
      intervals.push({
        start: nextStart,
        end: totalPages === '?' ? nextStart : Math.max(nextStart, totalPages)
      });
      render();
      // Rola a lista até o novo intervalo
      const list = backdrop.querySelector('#sp-intervals');
      if (list) list.scrollTop = list.scrollHeight;
    });

    backdrop.querySelector('#sp-cancel').addEventListener('click', () => {
      backdrop.remove();
    });

    backdrop.querySelector('#sp-confirm').addEventListener('click', async () => {
      // Lê valores atuais dos inputs antes de enviar
      backdrop.querySelectorAll('.sp-row').forEach(row => {
        const idx = parseInt(row.dataset.idx);
        intervals[idx].start = parseInt(row.querySelector('.sp-start').value) || 1;
        intervals[idx].end   = parseInt(row.querySelector('.sp-end').value)   || 1;
      });

      // Validação básica
      for (let i = 0; i < intervals.length; i++) {
        const iv = intervals[i];
        if (iv.start > iv.end) {
          alert(`Intervalo ${i + 1}: página inicial (${iv.start}) não pode ser maior que a final (${iv.end}).`);
          return;
        }
        if (totalPages !== '?' && iv.end > totalPages) {
          alert(`Intervalo ${i + 1}: página final (${iv.end}) ultrapassa o total de ${totalPages} páginas.`);
          return;
        }
      }

      backdrop.remove();
      await _executeSplit(intervals);
    });

    backdrop.addEventListener('click', e => {
      if (e.target === backdrop) backdrop.remove();
    });
  }

  document.body.appendChild(backdrop);
  render();
}

async function _executeSplit(intervals) {
  let pdfPath = store.currentPdfPath || store.pdfUrl || '';
  pdfPath = pdfPath.replace('/uploads/', '').replace('/ocr_outputs/', '');

  showLoadingOverlay('Dividindo PDF…');

  try {
    const resp = await fetch('/split_pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_path: pdfPath, intervals })
    });

    hideLoadingOverlay();

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `Erro HTTP ${resp.status}`);
    }

    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'pdf_dividido.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    showTemporaryMessage(`✅ PDF dividido em ${intervals.length} parte(s) — ZIP baixado!`);

  } catch (err) {
    hideLoadingOverlay();
    alert('Erro ao dividir PDF: ' + err.message);
  }
}

function _injectStyles() {
  if (document.getElementById('split-modal-styles')) return;
  const style = document.createElement('style');
  style.id = 'split-modal-styles';
  style.textContent = `
    #split-backdrop {
      position: fixed; inset: 0;
      background: rgba(0,0,0,.65);
      z-index: 9998;
      display: flex; align-items: center; justify-content: center;
    }
    #split-modal {
      background: #1C1C22 !important;
      border-radius: 14px;
      padding: 28px 24px 22px;
      width: min(500px, 94vw);
      max-height: min(85vh, 640px);
      display: flex;
      flex-direction: column;
      box-shadow: 0 8px 40px rgba(0,0,0,.5);
      z-index: 9999;
      font-family: 'Courier New', monospace;
    }
    #split-modal h2 {
      margin: 0 0 6px;
      font-size: 1.1rem;
      color: #ffffff !important;
      flex-shrink: 0;
    }
    .sp-subtitle {
      font-size: .8rem;
      color: #aaaabb !important;
      margin-bottom: 20px;
      line-height: 1.5;
      flex-shrink: 0;
    }
    .sp-subtitle strong { color: #ffffff !important; }
    #sp-intervals {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 12px;
      overflow-y: auto;
      min-height: 0;
      flex: 1 1 auto;
      padding-right: 4px;
      scrollbar-width: thin;
      scrollbar-color: #3a3a50 transparent;
    }
    #sp-intervals::-webkit-scrollbar { width: 8px; }
    #sp-intervals::-webkit-scrollbar-thumb { background: #3a3a50; border-radius: 4px; }
    #sp-intervals::-webkit-scrollbar-track { background: transparent; }
    .sp-row {
      display: flex;
      align-items: center;
      gap: 8px;
      background: #16161A;
      border: 1.5px solid #2A2A35;
      border-radius: 9px;
      padding: 10px 12px;
    }
    .sp-num {
      font-size: .75rem;
      font-weight: 700;
      color: #fff;
      background: #6C63FF;
      border-radius: 50%;
      width: 22px; height: 22px;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
    }
    .sp-label {
      font-size: .78rem;
      color: #8888aa !important;
      white-space: nowrap;
    }
    .sp-input {
      width: 62px;
      background: #0D0D0F !important;
      border: 1px solid #3a3a50;
      border-radius: 6px;
      color: #ffffff !important;
      font-family: inherit;
      font-size: .88rem;
      padding: 5px 8px;
      text-align: center;
    }
    .sp-input:focus { outline: none; border-color: #6C63FF; }
    .sp-remove {
      margin-left: auto;
      background: transparent;
      border: none;
      cursor: pointer;
      font-size: 1rem;
      opacity: .5;
      padding: 2px 4px;
    }
    .sp-remove:hover { opacity: 1; }
    #sp-add {
      width: 100%;
      background: #16161A !important;
      border: 1.5px dashed #3a3a50;
      border-radius: 9px;
      color: #8888cc !important;
      font-family: inherit;
      font-size: .85rem;
      padding: 9px;
      cursor: pointer;
      margin-bottom: 18px;
      flex-shrink: 0;
      transition: border-color .15s, color .15s;
    }
    #sp-add:hover { border-color: #6C63FF; color: #aaaaff !important; }
    .sp-btn-row {
      display: flex; justify-content: flex-end; gap: 10px;
      flex-shrink: 0;
    }
    .sp-btn-row button {
      padding: 9px 20px;
      border-radius: 8px;
      border: none;
      font-size: .85rem;
      cursor: pointer;
      font-weight: 700;
      font-family: inherit;
    }
    #sp-cancel       { background: #2A2A35 !important; color: #aaaacc !important; }
    #sp-cancel:hover { background: #35353F !important; }
    #sp-confirm       { background: #6C63FF !important; color: #fff !important; }
    #sp-confirm:hover { background: #5a52d5 !important; }
  `;
  document.head.appendChild(style);
}