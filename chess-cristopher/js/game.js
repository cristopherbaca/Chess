export const PIECE_NAMES = { p: 'pawn', n: 'knight', b: 'bishop', r: 'rook', q: 'queen', k: 'king' };
export const colorName = color => color === 'w' ? 'White' : 'Black';
export const otherColor = color => color === 'w' ? 'b' : 'w';
export const toUci = move => `${move.from}${move.to}${move.promotion || ''}`;
export const pieceSource = (color, type) => `assets/pieces/${color}${type.toUpperCase()}.svg`;

export function gameStatus(game, resigned = null) {
  if (resigned) return { title: `${colorName(otherColor(resigned))} wins`, detail: `${colorName(resigned)} resigned. A new game awaits.`, over: true };
  if (game.isCheckmate()) return { title: `${colorName(otherColor(game.turn()))} wins`, detail: 'Checkmate. A well-played finish.', over: true };
  const draws = [
    [game.isStalemate(), 'Stalemate'],
    [game.isThreefoldRepetition(), 'Threefold repetition'],
    [game.isInsufficientMaterial(), 'Insufficient material'],
    [game.isDrawByFiftyMoves(), '50-move rule']
  ];
  const draw = draws.find(([applies]) => applies);
  if (draw) return { title: 'Game drawn', detail: draw[1], over: true };
  if (game.isDraw()) return { title: 'Game drawn', detail: 'Drawn position.', over: true };
  return { title: `${colorName(game.turn())} to move${game.isCheck() ? ' · Check' : ''}`, detail: game.isCheck() ? 'Your king needs your attention.' : 'Take a breath. Find your next move.', over: false };
}

export function materialSummary(game) {
  const values = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
  const captured = { w: [], b: [] };
  for (const move of game.history({ verbose: true })) {
    if (move.captured) captured[move.color].push(move.captured);
  }
  for (const pieces of Object.values(captured)) pieces.sort((a, b) => values[b] - values[a]);
  // Count the live board so promotions also contribute to material advantage.
  const balance = game.board().flat().filter(Boolean).reduce((sum, piece) => sum + values[piece.type] * (piece.color === 'w' ? 1 : -1), 0);
  return { captured, balance };
}

export function undoTurn(game, opponent, humanColor) {
  if (!game.history().length) return;
  game.undo();
  if (opponent === 'ai') {
    while (game.turn() !== humanColor && game.history().length) game.undo();
  }
}
