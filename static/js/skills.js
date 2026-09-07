// ---------------- Slash commands ----------------
// Skills are .md files in skills/, each defining one or more "/command"s.
// The backend re-reads the folder on every call, so this file just polls
// list_commands() to keep the reference panel and the /-menu in sync with
// files added or edited outside the app.

const skillListEl = document.getElementById("skill-list");
const cmdMenuEl = document.getElementById("cmd-menu");
let _lastCommandsJson = null;

async function loadCommands(force) {
  if (!window.pywebview) return;   // bridge not ready yet on very first ticks
  const cmds = await window.pywebview.api.list_commands();
  const json = JSON.stringify(cmds);
  if (!force && json === _lastCommandsJson) return;
  _lastCommandsJson = json;
  allCommands = cmds;
  renderCommandPanel(force);
}

// Right-hand reference list: every available command, grouped by skill.
function renderCommandPanel(force) {
  if (!force && skillListEl.matches(":hover")) return;   // don't redraw under the pointer
  skillListEl.innerHTML = "";

  if (allCommands.length === 0) {
    skillListEl.innerHTML =
      `<div class="empty-hint">Ingen kommandoer. Legg til en skill i Innstillinger, eller slipp en .md-fil i skills/-mappen.</div>`;
    return;
  }

  const bySkill = {};
  allCommands.forEach(c => { (bySkill[c.skill] || (bySkill[c.skill] = [])).push(c); });

  Object.keys(bySkill).sort().forEach(skillName => {
    const group = document.createElement("div");
    group.className = "cmd-group";
    const head = document.createElement("div");
    head.className = "cmd-group-head";
    head.textContent = skillName;
    group.appendChild(head);

    bySkill[skillName].forEach(c => {
      const item = document.createElement("button");
      item.className = "cmd-ref";
      item.title = `Sett inn /${c.command}`;
      item.innerHTML = `<span class="cmd-ref-name">/${c.command}</span><span class="cmd-ref-desc"></span>`;
      item.querySelector(".cmd-ref-desc").textContent = c.description || "";
      item.onclick = () => insertCommand(c.command);
      group.appendChild(item);
    });
    skillListEl.appendChild(group);
  });
}

// Put "/command " at the front of the input, replacing any command already
// leading it, and focus the field.
function insertCommand(command) {
  const rest = inputEl.value.replace(/^\s*\/[A-Za-z0-9-]*\s*/, "");
  inputEl.value = `/${command} ` + rest;
  inputEl.focus();
  inputEl.setSelectionRange(command.length + 2, command.length + 2);
  autoGrow(inputEl, 160);
  hideCmdMenu();
}

// ---------------- The /-autocomplete menu ----------------

let cmdMenuMatches = [];
let cmdMenuIndex = 0;

// The "/word" fragment immediately before the caret, if the user is typing
// one at the start of the message or right after whitespace. Otherwise null.
function activeCommandFragment() {
  const pos = inputEl.selectionStart;
  const before = inputEl.value.slice(0, pos);
  const m = before.match(/(?:^|\s)\/([A-Za-z0-9-]*)$/);
  return m ? m[1].toLowerCase() : null;
}

function updateCmdMenu() {
  const frag = activeCommandFragment();
  if (frag === null) { hideCmdMenu(); return; }

  cmdMenuMatches = allCommands.filter(c => c.command.startsWith(frag));
  if (frag && cmdMenuMatches.length === 0) {
    cmdMenuMatches = allCommands.filter(c => c.command.includes(frag));
  }
  if (cmdMenuMatches.length === 0) { hideCmdMenu(); return; }

  cmdMenuIndex = 0;
  renderCmdMenu();
  cmdMenuEl.classList.remove("hidden");
}

function renderCmdMenu() {
  cmdMenuEl.innerHTML = "";
  cmdMenuMatches.forEach((c, i) => {
    const row = document.createElement("div");
    row.className = "cmd-menu-row" + (i === cmdMenuIndex ? " active" : "");
    row.innerHTML = `<span class="cmd-menu-name">/${c.command}</span><span class="cmd-menu-desc"></span>`;
    row.querySelector(".cmd-menu-desc").textContent = c.description || "";
    row.onmousedown = (e) => { e.preventDefault(); chooseCmd(i); };
    cmdMenuEl.appendChild(row);
  });
}

function hideCmdMenu() {
  cmdMenuEl.classList.add("hidden");
  cmdMenuMatches = [];
}

function cmdMenuOpen() {
  return !cmdMenuEl.classList.contains("hidden") && cmdMenuMatches.length > 0;
}

// Replace the fragment before the caret with the chosen "/command ".
function chooseCmd(i) {
  const c = cmdMenuMatches[i];
  if (!c) return;
  const pos = inputEl.selectionStart;
  const before = inputEl.value.slice(0, pos).replace(/\/([A-Za-z0-9-]*)$/, `/${c.command} `);
  const after = inputEl.value.slice(pos);
  inputEl.value = before + after;
  const caret = before.length;
  inputEl.setSelectionRange(caret, caret);
  hideCmdMenu();
  autoGrow(inputEl, 160);
}

// Capture phase so this runs before chat.js's Enter-to-send handler.
inputEl.addEventListener("keydown", (e) => {
  if (!cmdMenuOpen()) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    cmdMenuIndex = (cmdMenuIndex + 1) % cmdMenuMatches.length;
    renderCmdMenu();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    cmdMenuIndex = (cmdMenuIndex - 1 + cmdMenuMatches.length) % cmdMenuMatches.length;
    renderCmdMenu();
  } else if (e.key === "Enter" || e.key === "Tab") {
    e.preventDefault();
    e.stopPropagation();
    chooseCmd(cmdMenuIndex);
  } else if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    hideCmdMenu();
  }
}, true);

inputEl.addEventListener("input", updateCmdMenu);
inputEl.addEventListener("blur", () => setTimeout(hideCmdMenu, 100));

// Strip recognised leading "/command" tokens off a message. Returns
// { text, commands } - text with the tokens removed, and the command names
// that were found (in order, de-duplicated).
function extractCommands(raw) {
  const known = new Set(allCommands.map(c => c.command));
  const found = [];
  let text = raw;
  let m;
  const re = /^\s*\/([A-Za-z0-9-]+)(\s+|$)/;
  while ((m = text.match(re))) {
    const name = m[1].toLowerCase();
    if (!known.has(name)) break;
    if (!found.includes(name)) found.push(name);
    text = text.slice(m[0].length);
  }
  return { text: text.trimStart(), commands: found };
}

document.getElementById("refresh-skills-btn").onclick = () => loadCommands(true);
window.addEventListener("focus", () => loadCommands());

// Pick up skill files changed outside the app without a restart.
setInterval(() => {
  loadCommands();
  const settingsOpen = !document.getElementById("settings-overlay").classList.contains("hidden");
  if (settingsOpen && typeof refreshSettingsSkillList === "function") refreshSettingsSkillList();
}, 2500);
