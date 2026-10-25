import { Chess } from '../vendor/chess.js';
import { CONFIG } from '../js/config.js';
import { getCristopherMove, checkCristopherHealth } from '../js/cristopher.js';
import { gameStatus, materialSummary, toUci, undoTurn } from '../js/game.js';

const results = [];
const assert = (condition, message = 'Assertion failed') => { if (!condition) throw new Error(message); };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function test(name, run) {
  const item = document.createElement('li');
  try { await run(); item.className = 'pass'; item.textContent = `PASS — ${name}`; results.push({ name, pass: true }); }
  catch (error) { item.className = 'fail'; item.textContent = `FAIL — ${name}: ${error.message}`; results.push({ name, pass: false, error: error.message }); }
  document.getElementById('results').append(item);
}
async function rejects(run, message) {
  try { await run(); } catch (error) { assert(error.message.includes(message), error.message); return; }
  throw new Error('Expected rejection');
}
async function until(predicate, description) {
  for (let i = 0; i < 100; i++) { if (predicate()) return; await sleep(25); }
  throw new Error(`Timed out: ${description}`);
}

await test('Scholar’s mate and winner', () => {
  const game = new Chess();
  ['e4', 'e5', 'Bc4', 'Nc6', 'Qh5', 'Nf6', 'Qxf7#'].forEach(move => game.move(move));
  assert(game.isCheckmate());
  assert(gameStatus(game).title === 'White wins');
});
await test('Both colors can castle on either side', () => {
  for (const color of ['w', 'b']) for (const move of ['O-O', 'O-O-O']) {
    const game = new Chess(`r3k2r/8/8/8/8/8/8/R3K2R ${color} KQkq - 0 1`);
    const result = game.move(move);
    const rank = color === 'w' ? '1' : '8';
    assert(game.get(`${move === 'O-O' ? 'g' : 'c'}${rank}`).type === 'k');
    assert(game.get(`${move === 'O-O' ? 'f' : 'd'}${rank}`).type === 'r');
    assert(result.isKingsideCastle() || result.isQueensideCastle());
  }
});
await test('Castling through check is forbidden', () => {
  const game = new Chess('4kr2/8/8/8/8/8/8/4K2R w K - 0 1');
  assert(!game.moves().includes('O-O'));
});
await test('En passant removes and counts the captured pawn', () => {
  const game = new Chess();
  ['e4', 'a6', 'e5', 'd5', 'exd6'].forEach(move => game.move(move));
  assert(!game.get('d5') && game.get('d6').color === 'w');
  assert(materialSummary(game).captured.w.join('') === 'p');
  assert(materialSummary(game).balance === 1);
});
await test('All four promotions and promotion UCI', () => {
  for (const type of ['q', 'r', 'b', 'n']) {
    const game = new Chess('7k/P7/8/8/8/8/8/7K w - - 0 1');
    const move = game.move({ from: 'a7', to: 'a8', promotion: type });
    assert(game.get('a8').type === type && toUci(move) === `a7a8${type}`);
  }
});
await test('Stalemate, repetition, insufficient material, and 50-move draws', () => {
  assert(gameStatus(new Chess('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')).detail === 'Stalemate');
  assert(gameStatus(new Chess('7k/8/6K1/8/8/8/8/8 w - - 0 1')).detail === 'Insufficient material');
  assert(gameStatus(new Chess('7k/8/6K1/8/8/8/R7/8 w - - 100 51')).detail === '50-move rule');
  const game = new Chess();
  ['Nf3', 'Nf6', 'Ng1', 'Ng8', 'Nf3', 'Nf6', 'Ng1', 'Ng8'].forEach(move => game.move(move));
  assert(gameStatus(game).detail === 'Threefold repetition');
});
await test('Undo a completed AI round, an unanswered move, and a Black human round', () => {
  const game = new Chess();
  game.move('e4'); game.move('e5'); undoTurn(game, 'ai', 'w');
  assert(game.history().length === 0);
  game.move('e4'); undoTurn(game, 'ai', 'w'); assert(game.history().length === 0);
  game.move('e4'); game.move('e5'); game.move('Nf3'); undoTurn(game, 'ai', 'b');
  assert(game.history().length === 1 && game.turn() === 'b');
});
await test('Placeholder returns a legal UCI move after its delay', async () => {
  const game = new Chess();
  const started = performance.now();
  const result = await getCristopherMove({ fen: game.fen(), history: [], difficulty: 'hard' });
  assert(game.moves({ verbose: true }).map(toUci).includes(result.move));
  assert(performance.now() - started >= 390);
});

const originalConfig = { ...CONFIG };
const originalFetch = globalThis.fetch;
CONFIG.USE_API = true;
CONFIG.EXTRA_HEADERS = { 'ngrok-skip-browser-warning': 'true' };
const input = { fen: new Chess().fen(), history: [], difficulty: 'medium' };
await test('API sends the contract and optional headers; health returns OK', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify(url.endsWith('/health') ? { status: 'ok' } : { move: 'e2e4', info: { eval: .3, time_ms: 120 } })); };
  const result = await getCristopherMove(input);
  assert(result.move === 'e2e4' && result.info.eval === .3);
  assert(calls[0].options.method === 'POST' && calls[0].url === 'http://localhost:8000/move');
  assert(JSON.stringify(JSON.parse(calls[0].options.body)) === JSON.stringify(input));
  assert(calls[0].options.headers['ngrok-skip-browser-warning'] === 'true');
  await checkCristopherHealth();
  assert(calls[1].url.endsWith('/health') && calls[1].options.headers['ngrok-skip-browser-warning'] === 'true');
});
await test('Illegal moves and omitted promotion letters are rejected', async () => {
  for (const move of ['e2e5', 'nope', 'e2e4q']) {
    globalThis.fetch = async () => new Response(JSON.stringify({ move }));
    await rejects(() => getCristopherMove(input), 'invalid move');
  }
  globalThis.fetch = async () => new Response(JSON.stringify({ move: 'a7a8' }));
  await rejects(() => getCristopherMove({ ...input, fen: '7k/P7/8/8/8/8/8/7K w - - 0 1' }), 'invalid move');
});
await test('Network, HTTP, malformed JSON, and timeout failures are friendly', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await rejects(() => getCristopherMove(input), "couldn't reach");
  globalThis.fetch = async () => new Response('', { status: 503 });
  await rejects(() => getCristopherMove(input), 'HTTP 503');
  globalThis.fetch = async () => new Response('{');
  await rejects(() => getCristopherMove(input), 'unreadable');
  CONFIG.REQUEST_TIMEOUT_MS = 20;
  globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));
  await rejects(() => getCristopherMove(input), 'too long');
});
Object.assign(CONFIG, originalConfig);
globalThis.fetch = originalFetch;

const frame = document.getElementById('app');
await until(() => frame.contentDocument.querySelectorAll('.square').length === 64, 'application to load');
const doc = frame.contentDocument;
const click = id => doc.getElementById(id).click();
const square = name => doc.querySelector(`[data-square="${name}"]`);
const move = (from, to) => { square(from).click(); square(to).click(); };
function newGame(opponent = 'local', color = 'w') {
  click('new-game-button');
  doc.querySelector(`[name=color][value=${color}]`).checked = true;
  doc.getElementById('opponent').value = opponent;
  doc.getElementById('opponent').dispatchEvent(new Event('change'));
  doc.getElementById('new-game-form').requestSubmit();
}

await test('UI click selection, legal dots, illegal destination, and last move', () => {
  newGame(); square('e2').click();
  assert(square('e2').classList.contains('selected'));
  assert(square('e3').classList.contains('legal-move') && square('e4').classList.contains('legal-move'));
  square('e5').click(); assert(doc.getElementById('move-count').textContent === '0 played');
  square('e4').click();
  assert(square('e4').querySelector('img') && square('e2').classList.contains('last-move'));
  assert(doc.getElementById('game-status').textContent === 'Black to move');
});
await test('UI Scholar’s mate, capture rings, check king, SAN, and game lock', () => {
  newGame();
  [['e2','e4'],['e7','e5'],['f1','c4'],['b8','c6'],['d1','h5'],['g8','f6']].forEach(([from,to]) => move(from,to));
  square('h5').click(); assert(square('f7').classList.contains('legal-capture')); square('f7').click();
  assert(doc.getElementById('game-status').textContent === 'White wins');
  assert(square('e8').classList.contains('in-check'));
  assert(doc.getElementById('move-list').textContent.includes('Qxf7#'));
  assert(doc.getElementById('white-captures').querySelectorAll('img').length === 1);
  assert(doc.getElementById('board').classList.contains('input-locked'));
});
await test('UI en passant and Undo restore captured pieces', () => {
  newGame();
  [['e2','e4'],['a7','a6'],['e4','e5'],['d7','d5'],['e5','d6']].forEach(([from,to]) => move(from,to));
  assert(!square('d5').querySelector('img'));
  assert(doc.getElementById('white-material').textContent === '+1');
  click('undo-button');
  assert(square('d5').querySelector('img') && doc.getElementById('white-captures').textContent === '—');
});
await test('UI castling moves the king and rook on both sides', () => {
  const games = [
    { moves: [['e2','e4'],['e7','e5'],['g1','f3'],['b8','c6'],['f1','c4'],['f8','c5'],['e1','g1'],['g8','f6'],['d2','d3'],['e8','g8']], king: 'g', rook: 'f' },
    { moves: [['d2','d4'],['d7','d5'],['b1','c3'],['b8','c6'],['c1','f4'],['c8','f5'],['d1','d2'],['d8','d7'],['e1','c1'],['e8','c8']], king: 'c', rook: 'd' }
  ];
  for (const game of games) {
    newGame();
    game.moves.forEach(([from,to]) => move(from,to));
    for (const [color, rank] of [['w','1'],['b','8']]) {
      assert(square(`${game.king}${rank}`).querySelector('img')?.src.endsWith(`${color}K.svg`));
      assert(square(`${game.rook}${rank}`).querySelector('img')?.src.endsWith(`${color}R.svg`));
    }
    assert(doc.getElementById('move-count').textContent === '10 played');
  }
});
await test('UI promotion offers four choices; cancel preserves board; every choice works', () => {
  newGame();
  [['a2','a4'],['h7','h5'],['a4','a5'],['h5','h4'],['a5','a6'],['h4','h3'],['a6','b7'],['h3','g2']].forEach(([from,to]) => move(from,to));
  move('b7','a8');
  assert(doc.getElementById('promotion-dialog').open);
  assert(doc.querySelectorAll('#promotion-options button').length === 4);
  click('cancel-promotion'); assert(square('b7').querySelector('img'));
  for (const [type, name] of [['q','queen'],['r','rook'],['b','bishop'],['n','knight']]) {
    square('a8').click();
    assert(doc.getElementById('promotion-dialog').open);
    doc.querySelector(`[aria-label="Promote to ${name}"]`).click();
    assert(square('a8').querySelector('img').src.endsWith(`w${type.toUpperCase()}.svg`));
    click('undo-button'); square('b7').click();
  }
});
await test('UI keyboard navigation and flipped coordinates', () => {
  newGame(); square('e2').focus();
  square('e2').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
  assert(doc.activeElement.dataset.square === 'e3');
  click('flip-button');
  assert(doc.getElementById('board').firstElementChild.dataset.square === 'h1');
  assert(square('a8').querySelector('.file-coordinate').textContent === 'a');
});
await test('AI input lock, completed-round Undo, and stale response after Undo', async () => {
  newGame('ai'); move('e2','e4');
  assert(doc.getElementById('board').classList.contains('input-locked'));
  assert(!doc.getElementById('thinking').hidden);
  await until(() => doc.getElementById('move-count').textContent === '2 played', 'AI reply');
  click('undo-button'); assert(doc.getElementById('move-count').textContent === '0 played');
  move('e2','e4'); click('undo-button'); await sleep(900);
  assert(doc.getElementById('move-count').textContent === '0 played');
});
await test('New Game invalidates an in-flight response; Black auto-flips and AI opens', async () => {
  newGame('ai'); move('e2','e4'); newGame('local'); await sleep(900);
  assert(doc.getElementById('move-count').textContent === '0 played');
  newGame('ai', 'b');
  assert(doc.getElementById('board').firstElementChild.dataset.square === 'h1');
  await until(() => doc.getElementById('move-count').textContent === '1 played', 'AI opening');
  assert(doc.getElementById('game-status').textContent === 'Black to move');
  assert(doc.getElementById('undo-button').disabled);
});
await test('UI API failure preserves board, Retry succeeds, resignation invalidates pending move', async () => {
  const configUrl = new URL('../js/config.js', import.meta.url).href;
  const config = (await frame.contentWindow.eval(`import(${JSON.stringify(configUrl)})`)).CONFIG;
  const savedFetch = frame.contentWindow.fetch;
  try {
    config.USE_API = true;
    frame.contentWindow.fetch = async () => new Response(JSON.stringify({ move: 'a1a8' }));
    newGame('ai'); move('e2','e4');
    await until(() => !doc.getElementById('ai-error').hidden, 'error message');
    assert(doc.getElementById('move-count').textContent === '1 played');
    frame.contentWindow.fetch = async url => new Response(JSON.stringify(url.endsWith('/health') ? { status: 'ok' } : { move: 'e7e5' }));
    click('retry-button');
    await until(() => doc.getElementById('move-count').textContent === '2 played', 'retry');
    assert(doc.getElementById('ai-error').hidden);
    assert(doc.getElementById('connection').textContent.includes('Online'));
  } finally { config.USE_API = false; frame.contentWindow.fetch = savedFetch; }
  newGame('ai'); move('e2','e4'); click('resign-button'); click('confirm-resign'); await sleep(900);
  assert(doc.getElementById('game-status').textContent === 'Black wins');
  assert(doc.getElementById('move-count').textContent === '1 played');
});
const passed = results.filter(result => result.pass).length;
document.getElementById('summary').textContent = `${passed}/${results.length} checks passed`;
document.body.dataset.complete = 'true';
document.body.dataset.failed = results.length - passed;
