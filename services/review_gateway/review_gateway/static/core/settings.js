// Settings kept on this phone.

// Per-phone settings; a phone without storage just keeps the default.
export function readSetting(name, fallback) {
  try {
    return JSON.parse(localStorage.getItem(name)) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeSetting(name, value) {
  try {
    localStorage.setItem(name, JSON.stringify(value));
  } catch {
    /* private browsing */
  }
}
