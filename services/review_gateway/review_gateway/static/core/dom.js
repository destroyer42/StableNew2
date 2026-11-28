// The header, the view, the toast and the sheet. Text only: nothing here takes markup.

export const view = document.getElementById("view");
const title = document.getElementById("title");
export const back = document.getElementById("back");

export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "text") node.textContent = value;
    else if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value);
  }
  node.append(...children.filter(Boolean));
  return node;
}

let toastTimer = 0;
export function toast(message) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), 2500);
}

export function show(heading, canGoBack, ...nodes) {
  title.textContent = heading;
  back.hidden = !canGoBack;
  view.replaceChildren(...nodes);
}

export function closeSheet() {
  const sheet = document.getElementById("sheet");
  if (sheet) sheet.remove();
}

export function sheet(...nodes) {
  closeSheet();
  const node = el("div", { id: "sheet", class: "sheet", role: "dialog", "aria-modal": "true" }, [
    el("div", { class: "sheet-body" }, nodes),
  ]);
  node.addEventListener("click", (event) => {
    if (event.target === node) closeSheet(); // a tap outside the sheet closes it
  });
  document.body.append(node);
  return node;
}
