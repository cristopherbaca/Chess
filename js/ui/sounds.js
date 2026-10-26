export function soundNotes(move, { over, check }) {
  if (over) return [523, 659, 784, 523];
  if (move.promotion) return [392, 523, 659, 784];
  if (check) return [520, 740];
  if (move.flags?.includes("k") || move.flags?.includes("q"))
    return [330, 440, 330];
  return move.captured ? [180, 120] : [420];
}
