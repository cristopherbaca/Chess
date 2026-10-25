import { Chess } from '../vendor/chess.js';
import { Board } from './board.js';
import { CONFIG } from './config.js';
import { getCristopherMove, checkCristopherHealth } from './cristopher.js';
import { PIECE_NAMES, colorName, otherColor, toUci, pieceSource, gameStatus, materialSummary, undoTurn } from './game.js';

const $ = id => document.getElementById(id);
const state = {
  game: new Chess(), opponent: 'ai', humanColor: 'w', difficulty: 'medium', orientation: 'w',
  selected: null, resigned: null, pendingPromotion: null, busy: false, aiError: '', requestId: 0,
  muted: false, audio: null, healthBusy: false, connection: 'local', renderedHistory: ''
};
const board = new Board($('board'), { onSquare: clickSquare, onSelect: selectSquare, onDrop: attemptMove, canSelect, onInteract: unlockAudio });

function isOver() { return Boolean(state.resigned) || state.game.isGameOver(); }
function isAiTurn() { return state.opponent === 'ai' && state.game.turn() !== state.humanColor; }
function canPlay() { return !state.busy && !isOver() && !isAiTurn() && !state.pendingPromotion; }
function canSelect(square) { return canPlay() && state.game.get(square)?.color === state.game.turn(); }
function selectSquare(square) { if (canSelect(square)) { state.selected = square; render(); } }

function clickSquare(square) {
  if (!canPlay()) return;
  if (square === state.selected) { state.selected = null; render(); return; }
  if (canSelect(square)) { selectSquare(square); return; }
  if (state.selected) attemptMove(state.selected, square);
}

function attemptMove(from, to) {
  if (!canPlay() || state.game.get(from)?.color !== state.game.turn()) return;
  const moves = state.game.moves({ square: from, verbose: true }).filter(move => move.to === to);
  if (!moves.length) return;
  if (moves.some(move => move.promotion)) {
    state.pendingPromotion = { from, to };
    const options = $('promotion-options');
    options.replaceChildren();
    for (const type of ['q', 'r', 'b', 'n']) {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-label', `Promote to ${PIECE_NAMES[type]}`);
      const image = document.createElement('img');
      image.src = pieceSource(state.game.turn(), type);
      image.alt = '';
      const label = document.createElement('span');
      label.textContent = PIECE_NAMES[type];
      button.append(image, label);
      button.addEventListener('click', () => {
        const pending = state.pendingPromotion;
        state.pendingPromotion = null;
        $('promotion-dialog').close();
        if (pending) commitMove({ ...pending, promotion: type });
      });
      options.append(button);
    }
    render();
    $('promotion-dialog').showModal();
    return;
  }
  commitMove({ from, to });
}

function commitMove(move) {
  const result = state.game.move(move);
  state.selected = null;
  playSound(result);
  render();
  void requestAiMove();
}

async function requestAiMove() {
  if (!isAiTurn() || isOver() || state.busy) return;
  const requestId = ++state.requestId;
  const fen = state.game.fen();
  state.busy = true;
  state.aiError = '';
  render();
  try {
    const result = await getCristopherMove({ fen, history: state.game.history({ verbose: true }).map(toUci), difficulty: state.difficulty });
    // A new game, undo, or resignation makes an in-flight result obsolete.
    if (requestId !== state.requestId || fen !== state.game.fen() || isOver()) return;
    const move = state.game.move({ from: result.move.slice(0, 2), to: result.move.slice(2, 4), ...(result.move[4] ? { promotion: result.move[4] } : {}) });
    playSound(move);
  } catch (error) {
    if (requestId !== state.requestId) return;
    state.aiError = error.message || 'Something interrupted Cristopher. Please try again.';
  } finally {
    if (requestId === state.requestId) { state.busy = false; render(); }
  }
}

function invalidateRequest() {
  state.requestId++;
  state.busy = false;
  state.aiError = '';
  state.selected = null;
  board.cancelDrag();
}

function render() {
  const history = state.game.history({ verbose: true });
  const status = gameStatus(state.game, state.resigned);
  board.render({ game: state.game, orientation: state.orientation, selected: state.selected, lastMove: history.at(-1), enabled: canPlay() });
  $('game-status').textContent = status.title;
  $('status-detail').textContent = state.busy ? 'Cristopher is thinking…' : state.aiError ? 'Waiting for Cristopher. Retry when you’re ready.' : status.detail;
  $('status-icon').textContent = status.over ? '⚑' : state.game.turn() === 'w' ? '♔' : '♚';
  $('thinking').hidden = !state.busy;
  $('ai-error').hidden = !state.aiError;
  $('error-text').textContent = state.aiError;
  $('undo-button').disabled = !history.length || Boolean(state.resigned) || (state.opponent === 'ai' && state.humanColor === 'b' && history.length === 1);
  $('resign-button').disabled = status.over;
  $('difficulty-label').textContent = state.opponent === 'local' ? 'Local · 2 players' : `${state.difficulty[0].toUpperCase()}${state.difficulty.slice(1)}`;
  renderPlayer('top-player', otherColor(state.orientation));
  renderPlayer('bottom-player', state.orientation);
  renderHistory(history);
  renderMaterial();
}

function renderPlayer(id, color) {
  const element = $(id);
  const ai = state.opponent === 'ai' && color !== state.humanColor;
  const name = state.opponent === 'local' ? `${colorName(color)} player` : ai ? 'Cristopher' : 'You';
  element.querySelector('.player-name').textContent = name;
  element.querySelector('.player-description').textContent = ai ? (state.busy ? 'Thinking…' : 'Your thinking partner') : state.opponent === 'local' ? 'Across the board, together' : 'Make yourself at home';
  element.querySelector('.player-color').textContent = colorName(color).toUpperCase();
  element.querySelector('.avatar').textContent = ai ? 'C' : state.opponent === 'local' ? colorName(color)[0] : 'Y';
  element.querySelector('.avatar').classList.toggle('human-avatar', !ai);
  element.classList.toggle('active-player', state.game.turn() === color && !isOver());
}

function renderHistory(history) {
  const key = history.map(move => move.san).join(' ');
  if (state.renderedHistory === key && $('move-list').childElementCount) return;
  state.renderedHistory = key;
  $('move-list').replaceChildren();
  $('empty-moves').hidden = history.length > 0;
  $('move-count').textContent = `${history.length} played`;
  for (let index = 0; index < history.length; index += 2) {
    const row = document.createElement('tr');
    const number = document.createElement('th');
    number.scope = 'row';
    number.textContent = `${index / 2 + 1}.`;
    row.append(number);
    for (const offset of [0, 1]) {
      const cell = document.createElement('td');
      cell.textContent = history[index + offset]?.san || '—';
      if (index + offset === history.length - 1) cell.className = 'latest-move';
      row.append(cell);
    }
    $('move-list').append(row);
  }
  $('move-scroll').scrollTop = $('move-scroll').scrollHeight;
}

function renderMaterial() {
  const { captured, balance } = materialSummary(state.game);
  for (const color of ['w', 'b']) {
    const prefix = color === 'w' ? 'white' : 'black';
    const container = $(`${prefix}-captures`);
    container.replaceChildren();
    for (const type of captured[color]) {
      const image = document.createElement('img');
      image.src = pieceSource(otherColor(color), type);
      image.alt = `${colorName(otherColor(color))} ${PIECE_NAMES[type]}`;
      container.append(image);
    }
    if (!captured[color].length) container.textContent = '—';
    const advantage = color === 'w' ? balance : -balance;
    $(`${prefix}-material`).textContent = advantage > 0 ? `+${advantage}` : '';
    $(`${prefix}-material`).setAttribute('aria-label', advantage > 0 ? `${colorName(color)} is ahead by ${advantage} material points` : '');
  }
}

function unlockAudio() {
  if (state.muted) return;
  try {
    state.audio ||= new (window.AudioContext || window.webkitAudioContext)();
    if (state.audio.state === 'suspended') void state.audio.resume().catch(() => {});
  } catch { /* Audio is optional when the browser cannot provide it. */ }
}

function playSound(move) {
  if (state.muted || !state.audio || state.audio.state !== 'running') return;
  const checking = state.game.isCheck();
  const frequencies = checking ? [520, 740] : move.captured ? [180, 120] : [420];
  const start = state.audio.currentTime;
  frequencies.forEach((frequency, index) => {
    const oscillator = state.audio.createOscillator();
    const gain = state.audio.createGain();
    const time = start + index * 0.085;
    oscillator.type = 'sine';
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.exponentialRampToValueAtTime(0.10, time + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.12);
    oscillator.connect(gain);
    gain.connect(state.audio.destination);
    oscillator.start(time);
    oscillator.stop(time + 0.13);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
  });
}

async function updateConnection() {
  if (!CONFIG.USE_API || state.healthBusy) return;
  state.healthBusy = true;
  try { await checkCristopherHealth(); state.connection = 'online'; }
  catch { state.connection = 'offline'; }
  finally { state.healthBusy = false; renderConnection(); }
}

function renderConnection() {
  $('connection').className = `connection ${state.connection}`;
  $('connection').querySelector('span').textContent = `Connection · ${{ local: 'Local placeholder', checking: 'Connecting…', online: 'Online', offline: 'Offline' }[state.connection]}`;
}

$('new-game-button').addEventListener('click', () => $('new-game-dialog').showModal());
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
$('opponent').addEventListener('change', () => {
  $('difficulty').disabled = $('opponent').value === 'local';
  $('difficulty-note').hidden = $('opponent').value === 'local';
});
if (CONFIG.USE_API) $('difficulty-note').textContent = 'Difficulty is sent to Cristopher with every move request.';
$('new-game-form').addEventListener('submit', event => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  invalidateRequest();
  state.game.reset();
  state.humanColor = data.get('color') === 'random' ? (Math.random() < 0.5 ? 'w' : 'b') : data.get('color');
  state.orientation = state.humanColor;
  state.opponent = data.get('opponent');
  state.difficulty = data.get('difficulty') || $('difficulty').value;
  state.resigned = null;
  state.pendingPromotion = null;
  $('new-game-dialog').close();
  unlockAudio();
  render();
  void requestAiMove();
});
$('undo-button').addEventListener('click', () => {
  invalidateRequest();
  undoTurn(state.game, state.opponent, state.humanColor);
  render();
  void requestAiMove();
});
$('flip-button').addEventListener('click', () => { state.orientation = otherColor(state.orientation); render(); });
$('resign-button').addEventListener('click', () => {
  const color = state.opponent === 'ai' ? state.humanColor : state.game.turn();
  $('resign-description').textContent = `${colorName(color)} resigns and ${colorName(otherColor(color))} wins this game.`;
  $('resign-dialog').showModal();
});
$('confirm-resign').addEventListener('click', () => {
  // The AI may have delivered checkmate while the confirmation was open.
  if (!isOver()) {
    state.resigned = state.opponent === 'ai' ? state.humanColor : state.game.turn();
    invalidateRequest();
    render();
  }
  $('resign-dialog').close();
});
$('retry-button').addEventListener('click', () => { void updateConnection(); void requestAiMove(); });
$('sound-button').addEventListener('click', () => {
  state.muted = !state.muted;
  $('sound-button').setAttribute('aria-pressed', String(state.muted));
  $('sound-button').setAttribute('aria-label', state.muted ? 'Unmute sounds' : 'Mute sounds');
  $('sound-button').title = state.muted ? 'Unmute sounds' : 'Mute sounds';
  $('sound-button').textContent = state.muted ? '♪̸' : '♪';
  if (!state.muted) unlockAudio();
});
function cancelPromotion() { state.pendingPromotion = null; $('promotion-dialog').close(); render(); }
$('cancel-promotion').addEventListener('click', cancelPromotion);
$('promotion-dialog').addEventListener('cancel', event => { event.preventDefault(); cancelPromotion(); });
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !document.querySelector('dialog[open]')) { state.selected = null; board.cancelDrag(); render(); }
});
render();
if (CONFIG.USE_API) {
  state.connection = 'checking';
  renderConnection();
  void updateConnection();
  setInterval(() => { if (!document.hidden) void updateConnection(); }, 30000);
}
