// utils/coords.js – conversões de coordenadas canvas ↔ PDF
import { isNum } from './math.js';

/**
 * Normaliza coordenadas de tarja para valores 0..1
 */
export function normalizeTarjaRect(canvasX, canvasY, canvasW, canvasH, canvasWidth, canvasHeight) {
  console.log('🔧 normalizeTarjaRect chamada com:', {
    canvasX, canvasY, canvasW, canvasH, canvasWidth, canvasHeight
  });

  // Validação dos parâmetros
  if (!isNum(canvasX) || !isNum(canvasY) || !isNum(canvasW) || !isNum(canvasH)) {
    console.error('❌ Coordenadas inválidas:', { canvasX, canvasY, canvasW, canvasH });
    return null;
  }

  if (!canvasWidth || !canvasHeight || canvasWidth <= 0 || canvasHeight <= 0) {
    console.error('❌ Dimensões do canvas inválidas:', { canvasWidth, canvasHeight });
    return null;
  }

  const normalized = {
    x: canvasX / canvasWidth,
    y: canvasY / canvasHeight,
    w: canvasW / canvasWidth,
    h: canvasH / canvasHeight
  };

  console.log('✅ Normalizado:', normalized);
  return normalized;
}

/**
 * Converte coordenadas normalizadas (0..1) de volta para pixels do canvas
 */
export function denormalizeTarjaRect(normalized, canvasWidth, canvasHeight) {
  return {
    x: normalized.x * canvasWidth,
    y: normalized.y * canvasHeight,
    w: normalized.w * canvasWidth,
    h: normalized.h * canvasHeight
  };
}

/**
 * Converte coordenadas de canvas para coordenadas PDF (pontos)
 * ⭐ ADICIONAR ESTA FUNÇÃO
 */
export function canvasToPdf(canvasCoords, canvasWidth, canvasHeight, pdfWidth, pdfHeight) {
  return {
    x: (canvasCoords.x / canvasWidth) * pdfWidth,
    y: (canvasCoords.y / canvasHeight) * pdfHeight,
    w: (canvasCoords.w / canvasWidth) * pdfWidth,
    h: (canvasCoords.h / canvasHeight) * pdfHeight
  };
}

/**
 * Converte coordenadas de canvas para coordenadas PDF (pontos) - versão alternativa
 */
export function canvasToPdfCoords(canvasX, canvasY, scale, pdfWidth, pdfHeight) {
  return {
    x: (canvasX / scale),
    y: (canvasY / scale)
  };
}

/**
 * Converte coordenadas PDF (pontos) para coordenadas de canvas
 */
export function pdfToCanvasCoords(pdfX, pdfY, scale) {
  return {
    x: pdfX * scale,
    y: pdfY * scale
  };
}

/**
 * Converte coordenadas PDF para canvas (versão com dimensões)
 */
export function pdfToCanvas(pdfCoords, canvasWidth, canvasHeight, pdfWidth, pdfHeight) {
  return {
    x: (pdfCoords.x / pdfWidth) * canvasWidth,
    y: (pdfCoords.y / pdfHeight) * canvasHeight,
    w: (pdfCoords.w / pdfWidth) * canvasWidth,
    h: (pdfCoords.h / pdfHeight) * canvasHeight
  };
}

/**
 * Mapeia coordenadas de um sistema para outro (considerando rotação)
 */
export function mapCoordinates(x, y, fromWidth, fromHeight, toWidth, toHeight, rotation = 0) {
  let mappedX = (x / fromWidth) * toWidth;
  let mappedY = (y / fromHeight) * toHeight;

  // Aplica rotação se necessário
  if (rotation === 90) {
    [mappedX, mappedY] = [mappedY, toWidth - mappedX];
  } else if (rotation === 180) {
    mappedX = toWidth - mappedX;
    mappedY = toHeight - mappedY;
  } else if (rotation === 270) {
    [mappedX, mappedY] = [toHeight - mappedY, mappedX];
  }

  return { x: mappedX, y: mappedY };
}