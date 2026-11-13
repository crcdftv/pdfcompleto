// utils/selection.js
// A seleção agora é 100% nativa do browser — este arquivo existe
// apenas para manter compatibilidade com imports existentes.

export function clearAllSelections() {
  if (window.getSelection) window.getSelection().removeAllRanges();
}

// Mantidos como no-op para não quebrar nenhum import existente
export function handleSelectionStart() {}
export function handleSelectionMove() {}
export function handleSelectionEnd() {}