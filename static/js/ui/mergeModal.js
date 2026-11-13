// ui/mergeModal.js – Modal de reordenação de PDFs antes de juntar

/**
 * Abre um modal onde o usuário pode ver e reordenar os arquivos
 * selecionados antes de confirmar a junção.
 *
 * Retorna uma Promise que resolve com o array de Files na ordem
 * escolhida pelo usuário, ou null se ele cancelar.
 */
export function openMergeOrderModal(files) {
  return new Promise((resolve) => {

    // ── Injeta estilos uma única vez ──────────────────────────────
    if (!document.getElementById('merge-modal-styles')) {
      const style = document.createElement('style');
      style.id = 'merge-modal-styles';
      style.textContent = `
        #merge-order-backdrop {
          position: fixed; inset: 0;
          background: rgba(0,0,0,.55);
          z-index: 9998;
          display: flex; align-items: center; justify-content: center;
        }
        #merge-order-modal {
          background: #fff;
          border-radius: 12px;
          padding: 28px 24px 20px;
          width: min(480px, 94vw);
          max-height: 80vh;
          display: flex; flex-direction: column;
          box-shadow: 0 8px 32px rgba(0,0,0,.22);
          z-index: 9999;
        }
        #merge-order-modal h2 {
          margin: 0 0 6px;
          font-size: 1.15rem;
          color: #1a1a2e;
        }
        #merge-order-modal .subtitle {
          font-size: .82rem;
          color: #666;
          margin-bottom: 16px;
        }
        #merge-order-list {
          list-style: none;
          margin: 0; padding: 0;
          overflow-y: auto;
          flex: 1;
        }
        #merge-order-list li {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 12px;
          border: 1px solid #e0e0e0;
          border-radius: 8px;
          margin-bottom: 8px;
          background: #fafafa;
          cursor: grab;
          user-select: none;
          transition: background .15s, box-shadow .15s;
        }
        #merge-order-list li.dragging {
          opacity: .45;
          box-shadow: 0 4px 14px rgba(0,0,0,.18);
          cursor: grabbing;
        }
        #merge-order-list li.drag-over {
          background: #e8f0fe;
          border-color: #4285f4;
        }
        .merge-item-index {
          font-size: .75rem;
          font-weight: 700;
          color: #fff;
          background: #4285f4;
          border-radius: 50%;
          width: 22px; height: 22px;
          display: flex; align-items: center; justify-content: center;
          flex-shrink: 0;
        }
        .merge-item-name {
          flex: 1;
          font-size: .88rem;
          color: #333;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .merge-item-drag-handle {
          font-size: 1.1rem;
          color: #bbb;
          flex-shrink: 0;
        }
        #merge-order-modal .btn-row {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          margin-top: 18px;
        }
        #merge-order-modal button {
          padding: 8px 20px;
          border-radius: 7px;
          border: none;
          font-size: .9rem;
          cursor: pointer;
          font-weight: 600;
        }
        #merge-btn-cancel {
          background: #f0f0f0; color: #444;
        }
        #merge-btn-cancel:hover { background: #e0e0e0; }
        #merge-btn-confirm {
          background: #4285f4; color: #fff;
        }
        #merge-btn-confirm:hover { background: #2b6fd4; }
      `;
      document.head.appendChild(style);
    }

    // ── Estado interno: cópia mutável da lista de arquivos ────────
    let orderedFiles = [...files];

    // ── Constrói o modal ──────────────────────────────────────────
    const backdrop = document.createElement('div');
    backdrop.id = 'merge-order-backdrop';

    backdrop.innerHTML = `
      <div id="merge-order-modal">
        <h2>📄 Ordenar PDFs antes de juntar</h2>
        <p class="subtitle">Arraste os itens para definir a ordem final do documento.</p>
        <ul id="merge-order-list"></ul>
        <div class="btn-row">
          <button id="merge-btn-cancel">Cancelar</button>
          <button id="merge-btn-confirm">Juntar em ordem ✓</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);

    const list = backdrop.querySelector('#merge-order-list');

    // ── Renderiza os itens da lista ───────────────────────────────
    function renderList() {
      list.innerHTML = '';
      orderedFiles.forEach((file, idx) => {
        const li = document.createElement('li');
        li.dataset.idx = idx;
        li.draggable = true;
        li.innerHTML = `
          <span class="merge-item-index">${idx + 1}</span>
          <span class="merge-item-name" title="${file.name}">${file.name}</span>
          <span class="merge-item-drag-handle">⠿</span>
        `;
        list.appendChild(li);
      });
      attachDragEvents();
    }

    // ── Drag-and-drop entre itens ─────────────────────────────────
    let dragSrcIdx = null;

    function attachDragEvents() {
      list.querySelectorAll('li').forEach(li => {
        li.addEventListener('dragstart', (e) => {
          dragSrcIdx = parseInt(li.dataset.idx);
          li.classList.add('dragging');
          e.dataTransfer.effectAllowed = 'move';
        });
        li.addEventListener('dragend', () => {
          li.classList.remove('dragging');
          list.querySelectorAll('li').forEach(l => l.classList.remove('drag-over'));
        });
        li.addEventListener('dragover', (e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          list.querySelectorAll('li').forEach(l => l.classList.remove('drag-over'));
          li.classList.add('drag-over');
        });
        li.addEventListener('drop', (e) => {
          e.preventDefault();
          const targetIdx = parseInt(li.dataset.idx);
          if (dragSrcIdx === null || dragSrcIdx === targetIdx) return;

          // Reordena o array
          const moved = orderedFiles.splice(dragSrcIdx, 1)[0];
          orderedFiles.splice(targetIdx, 0, moved);
          dragSrcIdx = null;
          renderList();
        });
      });
    }

    renderList();

    // ── Botões ────────────────────────────────────────────────────
    backdrop.querySelector('#merge-btn-cancel').addEventListener('click', () => {
      backdrop.remove();
      resolve(null);
    });

    backdrop.querySelector('#merge-btn-confirm').addEventListener('click', () => {
      backdrop.remove();
      resolve(orderedFiles);
    });

    // Fechar clicando fora do modal
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) {
        backdrop.remove();
        resolve(null);
      }
    });
  });
}