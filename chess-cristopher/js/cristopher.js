import { Chess } from '../vendor/chess.js';
import { CONFIG } from './config.js';

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), CONFIG.REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${CONFIG.API_URL.replace(/\/+$/, '')}${path}`, {
      ...options,
      headers: { ...options.headers, ...CONFIG.EXTRA_HEADERS },
      signal: controller.signal
    });
    if (!response.ok) throw new Error(`Cristopher's server returned HTTP ${response.status}. Please try again.`);
    return await response.json();
  } catch (error) {
    if (controller.signal.aborted) throw new Error('Cristopher took too long to respond. Please try again.');
    if (error instanceof TypeError) throw new Error("We couldn't reach Cristopher. Check the connection and try again.");
    if (error instanceof SyntaxError) throw new Error("Cristopher sent an unreadable response. Please try again.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function getCristopherMove({ fen, history, difficulty }) {
  const game = new Chess(fen);
  const legalMoves = game.moves({ verbose: true });
  if (game.isGameOver() || !legalMoves.length) throw new Error('This position has no available move.');
  if (!CONFIG.USE_API) {
    await new Promise(resolve => setTimeout(resolve, 400 + Math.random() * 400));
    const move = legalMoves[Math.floor(Math.random() * legalMoves.length)];
    return { move: `${move.from}${move.to}${move.promotion || ''}`, info: { placeholder: true } };
  }
  const result = await request('/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fen, history, difficulty })
  });
  const legal = typeof result?.move === 'string' && /^[a-h][1-8][a-h][1-8][qrbn]?$/.test(result.move)
    && legalMoves.some(move => `${move.from}${move.to}${move.promotion || ''}` === result.move);
  if (!legal) throw new Error('Cristopher returned an invalid move. Your board is safe. Please try again.');
  return { move: result.move, info: result.info };
}

export async function checkCristopherHealth() {
  if (!CONFIG.USE_API) return true;
  const result = await request('/health', { cache: 'no-store' });
  if (result?.status !== 'ok') throw new Error('Cristopher is not ready yet.');
  return true;
}
