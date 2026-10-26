export class ChessClock {
  constructor(onTick, onTimeout, now = () => performance.now()) {
    this.onTick = onTick;
    this.onTimeout = onTimeout;
    this.now = now;
    this.remaining = { w: 0, b: 0 };
    this.seconds = 0;
    this.active = null;
    this.stamp = now();
    this.timer = setInterval(() => this.tick(), 100);
  }

  start(seconds, color = "w") {
    this.seconds = seconds;
    this.remaining = { w: seconds * 1000, b: seconds * 1000 };
    this.active = seconds ? color : null;
    this.stamp = this.now();
    this.onTick(this.value());
  }

  value() {
    return {
      remaining: { ...this.remaining },
      seconds: this.seconds,
      active: this.active,
    };
  }

  tick() {
    if (!this.active) return;
    const color = this.active;
    const now = this.now();
    this.remaining[color] = Math.max(
      0,
      this.remaining[color] - Math.max(0, now - this.stamp),
    );
    this.stamp = now;
    if (this.remaining[color] === 0) this.active = null;
    this.onTick(this.value());
    if (this.remaining[color] === 0) this.onTimeout(color);
  }

  switchTurn(color) {
    this.tick();
    if (!this.seconds || !this.active) return;
    this.active = color;
    this.stamp = this.now();
    this.onTick(this.value());
  }

  snapshot() {
    this.tick();
    return this.value();
  }
  stop() {
    this.active = null;
    this.onTick(this.value());
  }

  restore(snapshot, color) {
    this.remaining = { ...snapshot.remaining };
    this.seconds = snapshot.seconds;
    this.active = this.seconds && this.remaining[color] > 0 ? color : null;
    this.stamp = this.now();
    this.onTick(this.value());
  }

  destroy() {
    clearInterval(this.timer);
  }
}

export function formatTime(milliseconds) {
  const seconds = Math.ceil(Math.max(0, milliseconds) / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
