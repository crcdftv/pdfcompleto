// ui/compressModal.js – Modal de seleção de nível + aviso de arquivo maior

export function openCompressModal() {
  return new Promise((resolve) => {
    _injectStyles();

    const levels = [
      { key: 'alta',    label: 'Alta',    desc: 'Qualidade máxima · só remove redundâncias', color: '#4ECDC4' },
      { key: 'medio',   label: 'Média',   desc: 'Equilibrado · reduz imagens sem perder texto', color: '#6C63FF' },
      { key: 'baixa',   label: 'Baixa',   desc: 'Mais redução · imagens com qualidade menor', color: '#FFB347' },
      { key: 'extrema', label: 'Extrema', desc: 'Redução máxima · preserva códigos e textos', color: '#FF6B6B' },
    ];

    let selected = 'alta';

    const backdrop = document.createElement('div');
    backdrop.id = 'compress-backdrop';
    backdrop.innerHTML = `
      <div id="compress-modal">
        <h2>🗜️ Comprimir PDF</h2>
        <p class="cm-subtitle">Escolha o nível de compressão ou defina um tamanho alvo.</p>
        <div class="cm-levels">
          ${levels.map(l => `
            <div class="cm-card ${l.key === 'alta' ? 'selected' : ''}"
                 data-key="${l.key}" style="--cc: ${l.color}">
              <span class="cm-dot" style="color:${l.color}">●</span>
              <div class="cm-info">
                <strong>${l.label}</strong>
                <span>${l.desc}</span>
              </div>
            </div>
          `).join('')}
        </div>
        <div class="cm-target-row">
          <label class="cm-target-label">
            <span class="cm-dot" style="color:#FF6B6B">●</span>
            <strong>Tamanho alvo (MB)</strong>
          </label>
          <div class="cm-target-input-group">
            <input type="number" id="cm-target-input" value="2" min="0.1" max="50" step="0.1">
            <span class="cm-target-unit">MB</span>
            <button id="cm-target-btn" class="cm-target-btn">Comprimir para</button>
          </div>
        </div>
        <div class="cm-btn-row">
          <button id="cm-cancel">Cancelar</button>
          <button id="cm-confirm">Comprimir ✓</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);

    backdrop.querySelectorAll('.cm-card').forEach(card => {
      card.addEventListener('click', () => {
        backdrop.querySelectorAll('.cm-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        selected = card.dataset.key;
      });
    });

    backdrop.querySelector('#cm-cancel').addEventListener('click', () => {
      backdrop.remove(); resolve(null);
    });
    backdrop.querySelector('#cm-confirm').addEventListener('click', () => {
      backdrop.remove(); resolve(selected);
    });
    backdrop.querySelector('#cm-target-btn').addEventListener('click', () => {
      const val = parseFloat(document.getElementById('cm-target-input').value);
      if (val > 0) {
        backdrop.remove();
        resolve({ target_size_mb: val });
      }
    });
    backdrop.addEventListener('click', e => {
      if (e.target === backdrop) { backdrop.remove(); resolve(null); }
    });
  });
}

/**
 * Avisa que o arquivo ficou maior e pergunta se quer tentar nível maior.
 * Retorna true se o usuário quiser tentar de novo, false se não.
 * @param {number} reductionPercent  valor negativo = ficou maior
 * @param {string} nivelAtual        nível usado ("baixa"|"medio"|"alta"|"extrema")
 */
export function openCompressWarningModal(reductionPercent, nivelAtual) {
  return new Promise((resolve) => {
    _injectStyles();

    const proximo = { alta: 'medio', medio: 'baixa', baixa: 'extrema', extrema: null }[nivelAtual];
    const aumentou = Math.abs(reductionPercent).toFixed(1);

    const backdrop = document.createElement('div');
    backdrop.id = 'compress-warn-backdrop';
    backdrop.innerHTML = `
      <div id="compress-warn-modal">
        <div class="cw-icon">⚠️</div>
        <h2>Arquivo ficou ${aumentou}% maior</h2>
        <p class="cw-msg">Este PDF já está bem otimizado e o nível <strong>${_labelNivel(nivelAtual)}</strong> não conseguiu reduzí-lo.</p>
        ${proximo
          ? `<p class="cw-suggest">Quer tentar com nível <strong>${_labelNivel(proximo)}</strong> para forçar uma compressão maior?</p>`
          : `<p class="cw-suggest">Você já está no nível máximo. Este PDF provavelmente não pode ser comprimido mais.</p>`
        }
        <div class="cm-btn-row" style="justify-content:center; gap:12px; margin-top:20px">
          <button id="cw-no">Baixar assim mesmo</button>
          ${proximo ? `<button id="cw-yes" class="cw-yes-btn">Tentar nível ${_labelNivel(proximo)}</button>` : ''}
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);

    backdrop.querySelector('#cw-no').addEventListener('click', () => {
      backdrop.remove(); resolve(false);
    });
    const yesBtn = backdrop.querySelector('#cw-yes');
    if (yesBtn) {
      yesBtn.addEventListener('click', () => {
        backdrop.remove(); resolve(proximo); // retorna o próximo nível
      });
    }
    backdrop.addEventListener('click', e => {
      if (e.target === backdrop) { backdrop.remove(); resolve(false); }
    });
  });
}

function _labelNivel(key) {
  return { alta: 'Alta', medio: 'Média', baixa: 'Baixa', extrema: 'Extrema' }[key] || key;
}

function _injectStyles() {
  if (document.getElementById('compress-modal-styles')) return;
  const style = document.createElement('style');
  style.id = 'compress-modal-styles';
  style.textContent = `
    #compress-backdrop, #compress-warn-backdrop {
      position: fixed; inset: 0;
      background: rgba(0,0,0,.65);
      z-index: 9998;
      display: flex; align-items: center; justify-content: center;
    }
    #compress-modal, #compress-warn-modal {
      background: #1C1C22 !important;
      border-radius: 14px;
      padding: 28px 24px 22px;
      width: min(460px, 94vw);
      box-shadow: 0 8px 40px rgba(0,0,0,.5);
      z-index: 9999;
      font-family: 'Courier New', monospace;
    }
    #compress-modal h2,
    #compress-warn-modal h2 {
      margin: 0 0 6px;
      font-size: 1.1rem;
      color: #ffffff !important;
      letter-spacing: .04em;
    }
    .cm-subtitle, .cw-msg, .cw-suggest {
      font-size: .8rem;
      color: #aaaabb !important;
      margin-bottom: 18px;
      line-height: 1.5;
    }
    .cw-msg strong, .cw-suggest strong {
      color: #ffffff !important;
    }
    .cw-icon {
      font-size: 2rem;
      text-align: center;
      margin-bottom: 10px;
    }
    .cm-levels {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 20px;
    }
    .cm-card {
      background: #16161A !important;
      border: 1.5px solid #2A2A35;
      border-radius: 10px;
      padding: 12px 14px;
      cursor: pointer;
      transition: border-color .18s, background .18s;
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }
    .cm-card:hover  { background: #202028 !important; }
    .cm-card.selected { border-color: var(--cc); background: #202028 !important; }
    .cm-target-row {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 16px;
      padding: 12px;
      background: #16161A !important;
      border: 1.5px solid #2A2A35;
      border-radius: 10px;
    }
    .cm-target-label {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: .85rem;
      color: #ffffff !important;
    }
    .cm-target-input-group {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .cm-target-input-group input {
      flex: 1;
      padding: 6px 10px;
      border: 1px solid #2A2A35;
      border-radius: 6px;
      background: #202028 !important;
      color: #fff !important;
      font-size: 14px;
      font-family: inherit;
      text-align: center;
      outline: none;
      max-width: 80px;
    }
    .cm-target-input-group input:focus {
      border-color: #FF6B6B;
    }
    .cm-target-unit {
      color: #aaaacc;
      font-size: .8rem;
    }
    .cm-target-btn {
      padding: 6px 14px;
      border-radius: 6px;
      border: none;
      background: #FF6B6B !important;
      color: #fff !important;
      font-size: .8rem;
      font-weight: 700;
      cursor: pointer;
      font-family: inherit;
      margin-left: auto;
    }
    .cm-target-btn:hover { background: #e05555 !important; }
    .cm-dot { font-size: 1rem; margin-top: 2px; flex-shrink: 0; }
    .cm-info strong {
      display: block;
      font-size: .9rem;
      color: #ffffff !important;
      margin-bottom: 2px;
    }
    .cm-info span {
      font-size: .74rem;
      color: #8888aa !important;
    }
    .cm-btn-row {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 4px;
    }
    .cm-btn-row button {
      padding: 9px 20px;
      border-radius: 8px;
      border: none;
      font-size: .85rem;
      cursor: pointer;
      font-weight: 700;
      font-family: inherit;
      color: #ffffff !important;
    }
    #cm-cancel        { background: #2A2A35 !important; color: #aaaacc !important; }
    #cm-cancel:hover  { background: #35353F !important; }
    #cm-confirm       { background: #6C63FF !important; }
    #cm-confirm:hover { background: #5a52d5 !important; }
    #cw-no            { background: #2A2A35 !important; color: #aaaacc !important; }
    #cw-no:hover      { background: #35353F !important; }
    .cw-yes-btn       { background: #FFB347 !important; color: #1a1a1a !important; }
    .cw-yes-btn:hover { background: #e09a30 !important; }
  `;
  document.head.appendChild(style);
}