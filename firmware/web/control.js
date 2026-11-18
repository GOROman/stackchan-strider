"use strict";

const SERVICE = "48a23901-7920-49ee-889b-93d7dd615b02";
const COMMAND = "48a23902-7920-49ee-889b-93d7dd615b02";
const STATE = "48a23903-7920-49ee-889b-93d7dd615b02";
const byId = (id) => document.getElementById(id);
const connect = byId("connect");
const status = byId("status");
const battery = byId("battery");
const throttle = byId("throttle");
const throttleSurface = byId("throttle-surface");
const touchCursor = byId("touch-cursor");
const PITCH_CENTER = 30;
const pitchSlider = byId("pitch");

let device;
let command;
let direction = 0;
let speed = 35;
let maxDrive = 60;
let pitch = PITCH_CENTER;
let pointerId;
let touchId;
let heldKey;
let throttleValue = 0;
let dirty = false;
let writing = false;

function render() {
  byId("motion").disabled = byId("settings").disabled = !command;
  connect.textContent = command ? "切断" : "Bluetooth で接続";
  battery.hidden = !command;
  throttle.min = -(maxDrive - 9);
  throttle.max = maxDrive - 9;
  throttle.value = throttleValue;
  const motion = direction ? `${direction === 1 ? "前進" : "後退"} ${speed}%` : "停止";
  throttle.setAttribute("aria-valuetext", motion);
  byId("throttle-value").textContent = motion;
  pitchSlider.value = pitch;
  byId("pitch-value").textContent = `${pitch}°`;
}

function reset(message) {
  const previous = device;
  device = undefined;
  command = undefined;
  direction = 0;
  pointerId = undefined;
  touchId = undefined;
  touchCursor.hidden = true;
  heldKey = undefined;
  throttleValue = 0;
  dirty = false;
  previous?.gatt.disconnect();
  status.textContent = message;
  render();
}

// Keep at most one write in flight. If input changes, send the latest state next.
async function send() {
  if (!command) return;
  dirty = true;
  if (writing) return;
  writing = true;
  try {
    while (command && dirty) {
      dirty = false;
      const target = command;
      const flags = Number(byId("invert").checked) | (Number(byId("animate").checked) << 1);
      try {
        await target.writeValueWithResponse(Uint8Array.of(direction, speed, pitch, flags));
      } catch (error) {
        if (command === target) reset(`通信エラー（${error.message}）`);
      }
    }
  } finally {
    writing = false;
  }
}

function setThrottle(value) {
  const range = maxDrive - 9;
  throttleValue = Math.max(-range, Math.min(range, value));
  direction = throttleValue > 0 ? 1 : throttleValue < 0 ? 2 : 0;
  if (direction) speed = Math.abs(throttleValue) + 9;
  render();
  void send();
}

function stop() {
  const captured = pointerId;
  pointerId = undefined;
  touchId = undefined;
  touchCursor.hidden = true;
  heldKey = undefined;
  if (captured !== undefined && throttleSurface.hasPointerCapture(captured)) {
    throttleSurface.releasePointerCapture(captured);
  }
  if (direction) setThrottle(0);
}

connect.addEventListener("click", async () => {
  if (command) {
    reset("切断しました");
    return;
  }
  connect.disabled = true;
  status.textContent = "機器を選択してください";
  try {
    const selected = await navigator.bluetooth.requestDevice({
      filters: [{ services: [SERVICE] }, { namePrefix: "Strider-" }],
      optionalServices: [SERVICE],
    });
    device = selected;
    selected.addEventListener("gattserverdisconnected", () => {
      if (device === selected && !selected.gatt.connected) reset("Bluetooth 接続が切れました");
    }, { once: true });
    const server = await selected.gatt.connect();
    const service = await server.getPrimaryService(SERVICE);
    const writable = await service.getCharacteristic(COMMAND);
    const readable = await service.getCharacteristic(STATE);
    const value = await readable.readValue();
    if (device !== selected || !selected.gatt.connected) throw new Error("Bluetooth 接続が切れました");
    maxDrive = value.byteLength >= 7 ? Math.min(100, Math.max(10, value.getUint8(6))) : 60;
    speed = Math.min(value.getUint8(1), maxDrive);
    pitch = value.getUint8(2);
    const flags = value.getUint8(3);
    byId("invert").checked = Boolean(flags & 1);
    byId("animate").checked = Boolean(flags & 2);
    battery.textContent = `接続時のバッテリー電圧 ${(value.getUint16(4, true) / 1000).toFixed(2)} V`;
    command = writable;
    status.textContent = `${selected.name || "Strider"} に接続中`;
    void send();
  } catch (error) {
    reset(error.name === "NotFoundError" ? "機器が選択されませんでした" : `接続できません（${error.message}）`);
  } finally {
    connect.disabled = false;
    render();
  }
});

function dragThrottle(event) {
  const bounds = throttleSurface.getBoundingClientRect();
  const cursorX = Math.max(0, Math.min(bounds.width, event.clientX - bounds.left));
  const cursorY = Math.max(0, Math.min(bounds.height, event.clientY - bounds.top));
  touchCursor.style.left = `${cursorX}px`;
  touchCursor.style.top = `${cursorY}px`;
  touchCursor.hidden = false;
  const { top, height } = throttle.getBoundingClientRect();
  const thumbHeight = 2.25 * parseFloat(getComputedStyle(document.documentElement).fontSize);
  const position = (top + height / 2 - event.clientY) / ((height - thumbHeight) / 2);
  setThrottle(Math.round(position * (maxDrive - 9)));
}

throttleSurface.addEventListener("pointerdown", (event) => {
  if (event.pointerType === "touch" || event.button !== 0 ||
      !command || pointerId !== undefined || touchId !== undefined || heldKey) return;
  event.preventDefault();
  throttle.focus({ preventScroll: true });
  throttleSurface.setPointerCapture(event.pointerId);
  pointerId = event.pointerId;
  dragThrottle(event);
});
throttleSurface.addEventListener("pointermove", (event) => {
  if (event.pointerId === pointerId) dragThrottle(event);
});
for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
  throttleSurface.addEventListener(name, (event) => {
    if (event.pointerId === pointerId) stop();
  });
}
throttleSurface.addEventListener("touchstart", (event) => {
  event.preventDefault();
  if (!command || touchId !== undefined || pointerId !== undefined || heldKey) return;
  const touch = event.changedTouches[0];
  touchId = touch.identifier;
  dragThrottle(touch);
}, { passive: false });
throttleSurface.addEventListener("touchmove", (event) => {
  event.preventDefault();
  const touch = Array.from(event.changedTouches).find((point) => point.identifier === touchId);
  if (touch) dragThrottle(touch);
}, { passive: false });
for (const name of ["touchend", "touchcancel"]) {
  throttleSurface.addEventListener(name, (event) => {
    event.preventDefault();
    if (Array.from(event.changedTouches).some((point) => point.identifier === touchId)) stop();
  }, { passive: false });
}

throttle.addEventListener("keydown", (event) => {
  const step = event.key === "ArrowUp" ? 1 : event.key === "ArrowDown" ? -1 : 0;
  if (!step) {
    if (event.key === "Escape") stop();
    return;
  }
  event.preventDefault();
  if (!command || pointerId !== undefined || touchId !== undefined || (heldKey && heldKey !== event.key)) return;
  heldKey = event.key;
  setThrottle(throttleValue + step);
});
throttle.addEventListener("keyup", (event) => { if (event.key === heldKey) stop(); });
throttle.addEventListener("blur", stop);
// Ignore native slider changes that do not have a corresponding release event.
throttle.addEventListener("input", () => { throttle.value = throttleValue; });

byId("stop").addEventListener("click", stop);
byId("center").addEventListener("click", () => {
  pitch = PITCH_CENTER;
  stop();
  render();
  void send();
});
window.addEventListener("blur", stop);
window.addEventListener("pagehide", stop);
document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
setInterval(() => { if (direction) void send(); }, 300);

pitchSlider.addEventListener("input", () => {
  pitch = pitchSlider.valueAsNumber;
  render();
  void send();
});
for (const id of ["invert", "animate"]) byId(id).addEventListener("change", send);

render();
if (!navigator.bluetooth) {
  connect.disabled = true;
  status.textContent = "Mac の Chrome で localhost の操作ページを開いてください";
}
