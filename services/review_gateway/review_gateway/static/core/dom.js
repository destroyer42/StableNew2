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
  view.replaceChildren(...nodes.filter(Boolean)); // as in el(): a part that is not there is null, never text
}

// A notice under the header with one button. It stays until the page is loaded again.
export function banner(text, label, onclick) {
  const node = document.getElementById("update");
  node.replaceChildren(el("span", { text }), el("button", { type: "button", class: "primary", text: label, onclick }));
  node.hidden = false;
  document.body.classList.add("updating");
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
