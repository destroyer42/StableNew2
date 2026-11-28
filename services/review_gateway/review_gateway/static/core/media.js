// Media addresses, the element that shows one item, and the renditions fetched ahead.

import { el } from "./dom.js";

export const PREFETCH = 4;

export const mediaUrl = (item, variant) =>
  `/media/${encodeURIComponent(item.library_id)}/${encodeURIComponent(item.sha256)}/${variant}`;

export function mediaElement(item) {
  const poster = mediaUrl(item, "thumb");
  if (item.kind === "video") {
    const variant = item.variants.includes("video") ? "video" : "original";
    const video = el("video", { src: mediaUrl(item, variant), poster, controls: "", loop: "", playsinline: "", preload: "auto" });
    video.muted = true;
    video.autoplay = true;
    return video;
  }
  const variant = item.variants.includes("preview") ? "preview" : "original";
  return el("img", { src: mediaUrl(item, variant), alt: "", draggable: "false" });
}

// The next few phone renditions, held so the browser does not drop the requests. Originals are never fetched ahead.
let ahead = [];
export function prefetch(items) {
  ahead = items.map((item) => {
    const image = new Image();
    image.src = mediaUrl(item, item.kind === "image" && item.variants.includes("preview") ? "preview" : "thumb");
    return image;
  });
}
