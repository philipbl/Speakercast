// Speakercast — no framework, no build step. Reads assets/data.json and renders.

const FEED_APPS = {
  overcast: (url) => `overcast://x-callback-url/add?url=${encodeURIComponent(url)}`,
  pocketcasts: (url) => `pktc://subscribe/${url}`,
  podcasts: (url) => `pcast://${url}`,
  castro: (url) => `castro://subscribe/${url}`,
  downcast: (url) => `downcast://${url}`,
  itunes: (url) => `itpc://${url}`,
};

const dialog = document.getElementById("subscribe");
const searchInput = document.getElementById("search");
const statusEl = document.getElementById("status");
const allSpeakers = document.getElementById("all-speakers");

let speakers = [];
let sortKey = "name";

const lastName = (name) => name.trim().split(/\s+/).pop().toLowerCase();

/** Absolute https URL of a speaker's feed, for the subscribe links. */
function feedUrl(name) {
  const base = new URL("feeds/", window.location.href);
  return new URL(`${encodeURIComponent(name)}.rss`, base).href;
}

function speakerButton(speaker) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "speaker";
  button.innerHTML =
    `<span class="speaker-name"></span><span class="badge"></span>`;
  button.querySelector(".speaker-name").textContent = speaker.name;
  button.querySelector(".badge").textContent = speaker.count;
  button.title = `${speaker.count} talk${speaker.count === 1 ? "" : "s"}`;
  button.addEventListener("click", () => openSubscribe(speaker.name));
  return button;
}

function render(container, list) {
  container.replaceChildren(...list.map(speakerButton));
}

function sorted(list) {
  const copy = [...list];
  if (sortKey === "count") {
    copy.sort((a, b) => b.count - a.count || lastName(a.name).localeCompare(lastName(b.name)));
  } else {
    copy.sort((a, b) => lastName(a.name).localeCompare(lastName(b.name)));
  }
  return copy;
}

function applyFilter() {
  const query = searchInput.value.trim().toLowerCase();
  const matches = query
    ? speakers.filter((s) => s.name.toLowerCase().includes(query))
    : speakers;

  render(allSpeakers, sorted(matches));
  statusEl.textContent = matches.length
    ? `${matches.length} speaker${matches.length === 1 ? "" : "s"}`
    : `No speakers match “${searchInput.value.trim()}”.`;
}

function openSubscribe(name) {
  const url = feedUrl(name);
  document.getElementById("subscribe-title").textContent = `Talks By ${name}`;
  document.getElementById("feed-url").value = url;

  for (const link of dialog.querySelectorAll("[data-app]")) {
    // Podcast apps take the address without its scheme.
    link.href = FEED_APPS[link.dataset.app](url.replace(/^https?:\/\//, ""));
  }
  dialog.showModal();
}

async function copyFeedUrl() {
  const input = document.getElementById("feed-url");
  const button = document.getElementById("copy-button");
  try {
    await navigator.clipboard.writeText(input.value);
  } catch {
    input.select(); // Clipboard API needs a secure context; fall back to selecting.
    return;
  }
  button.textContent = "Copied";
  setTimeout(() => (button.textContent = "Copy"), 1500);
}

async function loadLeaders(byName) {
  const section = document.getElementById("leaders");
  try {
    const leaders = await fetch("assets/leaders.json").then((r) => r.json());
    const groups = [
      ["first-presidency", leaders.first_presidency],
      ["twelve-apostles", leaders.twelve_apostles],
    ];
    let shown = 0;
    for (const [id, names] of groups) {
      // Skip anyone with no feed yet, so a roster change can't leave dead links.
      const present = (names || []).map((n) => byName.get(n)).filter(Boolean);
      render(document.getElementById(id), present);
      shown += present.length;
    }
    section.hidden = shown === 0;
  } catch {
    section.hidden = true;
  }
}

async function init() {
  try {
    speakers = await fetch("assets/data.json").then((r) => r.json());
  } catch {
    statusEl.textContent = "Could not load the speaker list. Please try again later.";
    return;
  }

  applyFilter();
  loadLeaders(new Map(speakers.map((s) => [s.name, s])));

  searchInput.addEventListener("input", applyFilter);
  document.getElementById("copy-button").addEventListener("click", copyFeedUrl);

  for (const button of document.querySelectorAll(".sort-button")) {
    button.addEventListener("click", () => {
      sortKey = button.dataset.sort;
      for (const other of document.querySelectorAll(".sort-button")) {
        other.classList.toggle("is-active", other === button);
      }
      applyFilter();
    });
  }

  // Click outside the dialog card closes it.
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

init();
