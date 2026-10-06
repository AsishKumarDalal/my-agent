/* my-agent web chat — SSE streaming client over the local harness */
"use strict";

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");
const inputEl = $("input");
const sendBtn = $("send");
const sessionListEl = $("session-list");
const chatTitleEl = $("chat-title");

let currentSid = null;
let sending = false;
let sessionsCache = [];

/* ---------- markdown (marked with plain-text fallback) ---------- */
function md(text) {
  if (window.marked) {
    try {
      marked.setOptions({ breaks: true, gfm: true });
      return marked.parse(text);
    } catch (_) { /* fall through */ }
  }
  const div = document.createElement("div");
  div.textContent = text;
  return `<p style="white-space:pre-wrap">${div.innerHTML}</p>`;
}

/* ---------- scroll handling ---------- */
let pinned = true;
messagesEl.addEventListener("scroll", () => {
  pinned = messagesEl.scrollHeight - messagesEl.scrollTop -
           messagesEl.clientHeight < 80;
});
function scrollDown(force) {
  if (force || pinned) messagesEl.scrollTop = messagesEl.scrollHeight;
}

/* ---------- message rendering ---------- */
function welcome(visible) {
  const w = $("welcome");
  if (w) w.style.display = visible ? "" : "none";
}

function addMessage(role, text, { markdown = false } = {}) {
  welcome(false);
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "you".slice(0, 1).toUpperCase() : "⌘";

  const bubble = document.createElement("div");
  bubble.className = `bubble${markdown && role === "assistant" ? " md" : ""}`;
  if (markdown && role === "assistant") bubble.innerHTML = md(text);
  else bubble.textContent = text;

  if (role === "user") { row.appendChild(bubble); }
  else { row.appendChild(avatar); row.appendChild(bubble); }
  messagesEl.appendChild(row);
  scrollDown(true);
  return bubble;
}

function addEvent(kind, text) {
  if (kind === "turn") {
    const div = document.createElement("div");
    div.className = "turn-divider";
    div.textContent = `turn ${text}`;
    messagesEl.appendChild(div);
    scrollDown();
    return div;
  }
  if (kind === "deny" || text.startsWith("APPROVAL DENIED")) {
    const chip = document.createElement("div");
    chip.className = "event-chip deny";
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "blocked";
    chip.appendChild(tag);
    chip.appendChild(document.createTextNode(text.replace(/^APPROVAL DENIED[^:]*:\s*/, "")));
    messagesEl.appendChild(chip);
    scrollDown();
    return chip;
  }

  // tool call ("name(args)") and its output — expandable <details>
  const details = document.createElement("details");
  details.className = `event-chip ${kind === "act" ? "act" : "observe"}`;
  const summary = document.createElement("summary");
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = kind === "act" ? "tool call" : "output";
  summary.appendChild(tag);

  if (kind === "act") {
    const paren = text.indexOf("(");
    const name = paren > 0 ? text.slice(0, paren) : text;
    const args = paren > 0 ? text.slice(paren + 1, -1) : "";
    summary.appendChild(document.createTextNode(name));
    const argPreview = document.createElement("span");
    argPreview.className = "arg-preview";
    argPreview.textContent = " " + args.slice(0, 70) + (args.length > 70 ? "…" : "");
    summary.appendChild(argPreview);
    const body = document.createElement("pre");
    body.textContent = args || "{}";
    details.appendChild(summary);
    details.appendChild(body);
  } else {
    summary.appendChild(document.createTextNode(
      ` ${text.length} chars`));
    const body = document.createElement("pre");
    body.textContent = text;
    details.appendChild(summary);
    details.appendChild(body);
  }

  messagesEl.appendChild(details);
  scrollDown();
  return details;
}

function addError(text) {
  const chip = document.createElement("div");
  chip.className = "error-chip";
  chip.textContent = text;
  messagesEl.appendChild(chip);
  scrollDown(true);
}

/* ---------- sessions ---------- */
async function loadSessions() {
  const res = await fetch("/api/sessions");
  sessionsCache = await res.json();
  sessionListEl.innerHTML = "";
  for (const s of sessionsCache) {
    const el = document.createElement("div");
    el.className = "session-item" + (s.id === currentSid ? " active" : "");
    el.innerHTML = `<span class="count">${s.count}</span>`;
    el.appendChild(document.createTextNode(s.title));
    el.title = `${s.id} · ${s.count} msgs · ${s.created}`;
    el.onclick = () => selectSession(s.id);
    sessionListEl.appendChild(el);
  }
}

async function selectSession(sid) {
  if (sending) return;
  currentSid = sid;
  document.querySelectorAll(".session-item").forEach((el) =>
    el.classList.remove("active"));
  const items = sessionListEl.children;
  for (const el of items) {
    if (el.title.startsWith(sid)) el.classList.add("active");
  }
  const [msgsRes] = await Promise.all([
    fetch(`/api/sessions/${sid}`),
    loadSessions(),
  ]);
  const data = await msgsRes.json();
  chatTitleEl.textContent = data.meta.title;
  messagesEl.querySelectorAll(".msg-row, .event-chip, .error-chip, .turn-divider")
    .forEach((el) => el.remove());
  const has = data.messages.length > 0;
  welcome(!has);
  for (const m of data.messages) addMessage(m.role, m.content,
    { markdown: m.role === "assistant" });
  scrollDown(true);
}

async function newChat() {
  if (sending) return;
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const data = await res.json();
  currentSid = data.id;
  chatTitleEl.textContent = "(untitled)";
  messagesEl.querySelectorAll(".msg-row, .event-chip, .error-chip, .turn-divider")
    .forEach((el) => el.remove());
  welcome(true);
  await loadSessions();
}

/* ---------- send + SSE streaming ---------- */
function setSending(on) {
  sending = on;
  sendBtn.disabled = on || !inputEl.value.trim();
  inputEl.disabled = on;
}

async function send() {
  const text = inputEl.value.trim();
  if (!text || sending) return;
  if (!currentSid) await newChat();

  inputEl.value = "";
  autosize();
  setSending(true);
  addMessage("user", text);

  const shell = addMessage("assistant", "");
  shell.innerHTML =
    `<details class="think-details" hidden>` +
    `<summary>💭 Thinking</summary><pre class="think-body"></pre></details>` +
    `<div class="thinking"><span></span><span></span><span></span></div>` +
    `<div class="content-part"></div>`;
  const thinkDetails = shell.querySelector(".think-details");
  const thinkBody = shell.querySelector(".think-body");
  const dots = shell.querySelector(".thinking");
  const contentPart = shell.querySelector(".content-part");
  let gotDelta = false;
  let thinkText = "";
  let accumulated = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSid, message: text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const ev = JSON.parse(line.slice(6));

        if (ev.type === "reasoning") {
          thinkDetails.hidden = false;
          thinkText += ev.text;
          thinkBody.textContent = thinkText;
          scrollDown();
        } else if (ev.type === "delta") {
          if (!gotDelta) {
            gotDelta = true;
            dots.style.display = "none";
            contentPart.classList.add("md");
          }
          accumulated += ev.text;
          contentPart.innerHTML = md(accumulated) + '<span class="caret"></span>';
          scrollDown();
        } else if (ev.type === "event") {
          addEvent(ev.kind, ev.text);
        } else if (ev.type === "done") {
          const finalText = ev.answer || accumulated;
          contentPart.classList.add("md");
          contentPart.innerHTML = md(finalText);
          dots.style.display = "none";
          if (thinkText) {
            thinkDetails.open = false;   // collapse once the answer lands
          }
        } else if (ev.type === "error") {
          addError(ev.text);
        }
      }
    }
    if (!gotDelta && !shell.querySelector(".error-chip")) {
      if (!contentPart.innerHTML.trim()) contentPart.textContent = "(no response)";
    }
  } catch (e) {
    addError(`Connection error: ${e.message}`);
    if (!gotDelta) shell.remove();
  } finally {
    setSending(false);
    scrollDown();
    loadSessions();
  }
}

/* ---------- composer behaviour ---------- */
function autosize() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + "px";
  sendBtn.disabled = sending || !inputEl.value.trim();
}

inputEl.addEventListener("input", autosize);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
sendBtn.addEventListener("click", send);
$("new-chat").addEventListener("click", newChat);
$("toggle-sidebar").addEventListener("click", () =>
  $("sidebar").classList.toggle("hidden"));
document.querySelectorAll(".suggestion").forEach((btn) =>
  btn.addEventListener("click", () => {
    inputEl.value = btn.dataset.prompt;
    autosize();
    send();
  }));

/* ---------- boot ---------- */
(async function boot() {
  await loadSessions();
  if (sessionsCache.length > 0) {
    await selectSession(sessionsCache[0].id);
  } else {
    await newChat();
  }
  inputEl.focus();
})();
