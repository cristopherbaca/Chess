import { PIECE_NAMES, colorName, pieceSource } from './game.js';

export class Board {
  constructor(element, { onSquare, onSelect, onDrop, canSelect, onInteract }) {
    this.element = element;
    this.callbacks = { onSquare, onSelect, onDrop, canSelect, onInteract };
    this.squares = new Map();
    this.focusSquare = 'e2';
    this.drag = null;
    this.suppressClick = false;
    for (let rank = 1; rank <= 8; rank++) {
      for (const file of 'abcdefgh') {
        const square = `${file}${rank}`;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'square';
        button.dataset.square = square;
        button.tabIndex = square === this.focusSquare ? 0 : -1;
        this.squares.set(square, button);
      }
    }
    element.addEventListener('click', event => {
      if (this.suppressClick && event.detail > 0) { this.suppressClick = false; return; }
      const square = event.target.closest('[data-square]')?.dataset.square;
      if (square) { onInteract(); onSquare(square); }
    });
    element.addEventListener('focusin', event => {
      const square = event.target.dataset.square;
      if (!square) return;
      this.squares.get(this.focusSquare).tabIndex = -1;
      this.focusSquare = square;
      this.squares.get(square).tabIndex = 0;
    });
    element.addEventListener('keydown', event => this.navigate(event));
    element.addEventListener('pointerdown', event => this.pointerDown(event));
    element.addEventListener('pointermove', event => this.pointerMove(event));
    element.addEventListener('pointerup', event => this.pointerUp(event));
    element.addEventListener('pointercancel', event => {
      if (event.pointerId === this.drag?.pointerId) this.cancelDrag();
    });
    element.addEventListener('lostpointercapture', event => {
      // Touch transfers implicit capture from the square to the board while dragging.
      if (event.target === element && event.pointerId === this.drag?.pointerId) this.cancelDrag();
    });
    element.addEventListener('dragstart', event => event.preventDefault());
  }

  render({ game, orientation, selected, lastMove, enabled }) {
    this.enabled = enabled;
    const files = [...'abcdefgh'];
    const ranks = [8, 7, 6, 5, 4, 3, 2, 1];
    if (orientation === 'b') { files.reverse(); ranks.reverse(); }
    this.order = ranks.flatMap(rank => files.map(file => `${file}${rank}`));
    if (this.orientation !== orientation) {
      this.cancelDrag();
      this.orientation = orientation;
      this.element.replaceChildren(...this.order.map(square => this.squares.get(square)));
    }
    const destinations = selected ? game.moves({ square: selected, verbose: true }) : [];
    this.element.classList.toggle('input-locked', !enabled);
    this.element.setAttribute('aria-label', `Chess board, ${colorName(orientation)} at bottom. Arrow keys navigate; Enter selects a piece or destination.`);
    for (const [square, button] of this.squares) {
      const piece = game.get(square);
      const move = destinations.find(candidate => candidate.to === square);
      const dark = (square.charCodeAt(0) - 97 + Number(square[1])) % 2 === 1;
      const checkingKing = game.isCheck() && piece?.type === 'k' && piece.color === game.turn();
      button.className = ['square', dark ? 'dark' : 'light', selected === square ? 'selected' : '', lastMove && [lastMove.from, lastMove.to].includes(square) ? 'last-move' : '', move ? (move.captured ? 'legal-capture' : 'legal-move') : '', checkingKing ? 'in-check' : ''].filter(Boolean).join(' ');
      button.setAttribute('aria-label', `${square}${piece ? `, ${colorName(piece.color)} ${PIECE_NAMES[piece.type]}` : ', empty'}${move ? ', legal destination' : ''}${checkingKing ? ', in check' : ''}`);
      button.setAttribute('aria-pressed', String(selected === square));
      button.setAttribute('aria-disabled', String(!enabled));
      const signature = `${piece?.color || ''}${piece?.type || ''}:${orientation}`;
      if (button.dataset.signature === signature) continue;
      button.dataset.signature = signature;
      button.replaceChildren();
      if (piece) {
        const image = document.createElement('img');
        image.src = pieceSource(piece.color, piece.type);
        image.alt = '';
        image.draggable = false;
        image.className = 'piece';
        button.append(image);
      }
      if (square[0] === files[0]) this.coordinate(button, square[1], 'rank-coordinate');
      if (Number(square[1]) === ranks[7]) this.coordinate(button, square[0], 'file-coordinate');
    }
  }

  coordinate(button, text, className) {
    const label = document.createElement('span');
    label.className = className;
    label.textContent = text;
    label.setAttribute('aria-hidden', 'true');
    button.append(label);
  }

  navigate(event) {
    const steps = { ArrowUp: -8, ArrowDown: 8, ArrowLeft: -1, ArrowRight: 1 };
    if (!(event.key in steps)) return;
    event.preventDefault();
    const index = this.order.indexOf(this.focusSquare);
    const next = index + steps[event.key];
    if (next < 0 || next > 63 || (Math.abs(steps[event.key]) === 1 && Math.floor(next / 8) !== Math.floor(index / 8))) return;
    this.squares.get(this.order[next]).focus();
  }

  pointerDown(event) {
    if (event.button !== 0 || !event.isPrimary || !this.enabled) return;
    this.suppressClick = false;
    const square = event.target.closest('[data-square]')?.dataset.square;
    if (!square || !this.callbacks.canSelect(square)) return;
    this.callbacks.onInteract();
    this.drag = { square, x: event.clientX, y: event.clientY, pointerId: event.pointerId, ghost: null };
  }

  pointerMove(event) {
    const drag = this.drag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (!drag.ghost && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 6) {
      this.callbacks.onSelect(drag.square);
      const source = this.squares.get(drag.square);
      drag.ghost = source.querySelector('.piece').cloneNode();
      drag.ghost.className = 'drag-piece';
      drag.ghost.style.width = `${source.clientWidth * 0.86}px`;
      document.body.append(drag.ghost);
      source.classList.add('drag-source');
      this.element.setPointerCapture(event.pointerId);
    }
    if (drag.ghost) {
      drag.ghost.style.left = `${event.clientX}px`;
      drag.ghost.style.top = `${event.clientY}px`;
    }
  }

  pointerUp(event) {
    const drag = this.drag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dragged = Boolean(drag.ghost);
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-square]');
    this.cancelDrag();
    if (dragged) {
      this.suppressClick = true;
      // Only suppress the click generated by this pointer release, never a later tap or key.
      setTimeout(() => { this.suppressClick = false; }, 0);
      if (target && this.element.contains(target)) this.callbacks.onDrop(drag.square, target.dataset.square);
    }
  }

  cancelDrag() {
    if (!this.drag) return;
    const { square, ghost, pointerId } = this.drag;
    this.drag = null;
    ghost?.remove();
    this.squares.get(square).classList.remove('drag-source');
    if (this.element.hasPointerCapture(pointerId)) this.element.releasePointerCapture(pointerId);
  }
}
