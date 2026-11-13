// ui/loadingOverlay.js
// Overlay de carregamento com suporte a barra de progresso real.
//
// API pública:
//   showLoadingOverlay(mensagem)          – exibe o overlay (barra zerada)
//   hideLoadingOverlay()                  – oculta e reseta
//   updateLoadingProgress(pct, mensagem)  – atualiza barra (0-100) e texto

let _overlayEl   = null;
let _barEl       = null;
let _pctEl       = null;
let _msgEl       = null;
let _animFrameId = null;
let _currentPct  = 0;
let _targetPct   = 0;

/* ── Cria o elemento uma única vez ──────────────────────────────────── */
function _getOrCreate() {
  if (_overlayEl) return _overlayEl;

  _overlayEl = document.createElement('div');
  _overlayEl.id = 'loading-overlay';
  _overlayEl.innerHTML = `
    <div class="loading-box">
      <div class="loading-spinner"></div>
      <p class="loading-msg">Carregando…</p>
      <div class="loading-progress-wrap" style="display:none">
        <div class="loading-progress-bar">
          <div class="loading-progress-fill"></div>
        </div>
        <span class="loading-progress-pct">0%</span>
      </div>
    </div>
  `;

  /* Estilos injetados inline para que o módulo seja auto-suficiente */
  if (!document.getElementById('loading-overlay-styles')) {
    const style = document.createElement('style');
    style.id = 'loading-overlay-styles';
    style.textContent = `
      #loading-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.55);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        backdrop-filter: blur(2px);
        opacity: 0;
        pointer-events: none;
        visibility: hidden;
        transition: opacity 0.2s ease, visibility 0.2s ease;
      }
      #loading-overlay.visible {
        opacity: 1;
        pointer-events: auto;
        visibility: visible;
      }

      .loading-box {
        background: #fff;
        border-radius: 12px;
        padding: 32px 40px;
        min-width: 280px;
        max-width: 360px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.18);
      }

      .loading-spinner {
        width: 44px;
        height: 44px;
        border: 4px solid #e5e7eb;
        border-top-color: #3b82f6;
        border-radius: 50%;
        animation: loading-spin 0.75s linear infinite;
        flex-shrink: 0;
      }
      @keyframes loading-spin { to { transform: rotate(360deg); } }

      .loading-msg {
        margin: 0;
        font-size: 14px;
        color: #374151;
        text-align: center;
        min-height: 20px;
        font-family: inherit;
      }

      .loading-progress-wrap {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .loading-progress-bar {
        flex: 1;
        height: 8px;
        background: #e5e7eb;
        border-radius: 99px;
        overflow: hidden;
      }

      .loading-progress-fill {
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #3b82f6, #6366f1);
        border-radius: 99px;
        transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1);
      }

      .loading-progress-pct {
        font-size: 12px;
        font-weight: 600;
        color: #6b7280;
        min-width: 34px;
        text-align: right;
        font-family: inherit;
        font-variant-numeric: tabular-nums;
      }
    `;
    document.head.appendChild(style);
  }

  _barEl = _overlayEl.querySelector('.loading-progress-fill');
  _pctEl = _overlayEl.querySelector('.loading-progress-pct');
  _msgEl = _overlayEl.querySelector('.loading-msg');

  document.body.appendChild(_overlayEl);
  return _overlayEl;
}

/* ── Exibe o overlay ─────────────────────────────────────────────────  */
export function showLoadingOverlay(mensagem = 'Carregando…') {
  const el = _getOrCreate();
  _currentPct = 0;
  _targetPct  = 0;
  _setBar(0);
  _msgEl.textContent = mensagem;
  void el.offsetHeight;
  el.classList.add('visible');
}

export function hideLoadingOverlay() {
  if (!_overlayEl) return;
  _overlayEl.classList.remove('visible');
  _setBar(0);
  _msgEl.textContent = 'Carregando…';
  if (_animFrameId) {
    cancelAnimationFrame(_animFrameId);
    _animFrameId = null;
  }
}

/* ── Atualiza progresso (chamado pelo polling do compress.js) ─────────
 *   pct      : 0–100
 *   mensagem : texto da etapa atual (opcional)
 */
export function updateLoadingProgress(pct, mensagem) {
  if (!_overlayEl) return;

  const wrap = _overlayEl.querySelector('.loading-progress-wrap');
  if (wrap) wrap.style.removeProperty('display');

  _targetPct = Math.max(0, Math.min(100, pct));
  if (mensagem !== undefined) _msgEl.textContent = mensagem;

  _animateBar();
}

/* ── Internos ────────────────────────────────────────────────────────  */
function _setBar(pct) {
  if (_barEl) _barEl.style.width = pct + '%';
  if (_pctEl) _pctEl.textContent = Math.round(pct) + '%';
}

function _animateBar() {
  if (_animFrameId) return; // já está animando

  function step() {
    const diff = _targetPct - _currentPct;
    if (Math.abs(diff) < 0.3) {
      _currentPct = _targetPct;
      _setBar(_currentPct);
      _animFrameId = null;
      return;
    }
    // Easing: avança 18% da diferença restante por frame (~60fps → suave)
    _currentPct += diff * 0.18;
    _setBar(_currentPct);
    _animFrameId = requestAnimationFrame(step);
  }

  _animFrameId = requestAnimationFrame(step);
}