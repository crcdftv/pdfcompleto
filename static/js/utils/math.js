// utils/math.js – funções matemáticas genéricas
export function isNum(v) {
  return typeof v === 'number' && Number.isFinite(v);
}

/**
 * Mapeia um valor de um intervalo para outro.
 * Ex.: mapValue(dist, 0, 100, 120, 20) → velocidade do scroll.
 */
export function mapValue(value, inMin, inMax, outMax, outMin) {
  return Math.max(
    outMin,
    Math.min(
      outMax,
      ((value - inMin) * (outMax - outMin)) / (inMax - inMin) + outMin
    )
  );
}
