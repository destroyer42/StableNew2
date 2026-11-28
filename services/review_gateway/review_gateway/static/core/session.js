// What this phone may do: the session's grants, read once.

import { api } from "./api.js";

let scopes = null; // the session's grants, read once

// A new pairing has its own grants.
export const forgetScopes = () => {
  scopes = null;
};

export async function loadScopes() {
  if (scopes === null) {
    try {
      scopes = (await api("/api/session")).scopes || [];
    } catch {
      return [];
    }
  }
  return scopes;
}

export const canQueue = () => Array.isArray(scopes) && scopes.includes("queue");

export const canUpdate = () => Array.isArray(scopes) && scopes.includes("admin");
