/**
 * A filter's colour matrix as the booth draws it.
 *
 * The API gives three rows (red, green, blue out) of four numbers: the weights of red, green and
 * blue in, then an offset, all on 0..1 values. The server applies them with Pillow. The booth
 * applies the very same numbers with an SVG feColorMatrix in sRGB, whose rows have five numbers
 * (r, g, b, alpha, offset) and a fourth row for alpha, which stays as it is.
 */
export function matrixValues(matrix: readonly number[]): string {
  const row = (i: number) => [...matrix.slice(i * 4, i * 4 + 3), 0, matrix[i * 4 + 3] ?? 0]
  return [...row(0), ...row(1), ...row(2), 0, 0, 0, 1, 0].join(' ')
}

/**
 * What feColorMatrix makes of one 8-bit colour (each channel clamped to 0..1, then back to 8
 * bits). Only the parity test uses it, to prove the booth reads the matrix as the server does.
 */
export function applyMatrix(
  matrix: readonly number[],
  rgb: readonly [number, number, number],
): [number, number, number] {
  const values = matrixValues(matrix).split(' ').map(Number)
  const input = [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1, 1]
  const out = [0, 1, 2].map((row) => {
    const sum = input.reduce((acc, value, column) => acc + value * (values[row * 5 + column] ?? 0), 0)
    return Math.round(Math.min(1, Math.max(0, sum)) * 255)
  })
  return [out[0] ?? 0, out[1] ?? 0, out[2] ?? 0]
}
