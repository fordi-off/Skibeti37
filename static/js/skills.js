// ---------------- Skills (right panel - on/off only) ----------------
// The backend reads the skills/ folder live on every call, so this panel
// just needs to re-poll to notice files added/removed outside the app.

const skillListEl = document.getElementById("skill-list");
let _lastSkillsJson = null;

async function refreshSkillList(force) {
  // Don't redraw the list out from under the pointer during a poll.
  if (!force && skillListEl.matches(":hover")) return;

  const skills = await window.pywebview.api.list_skills();
  const json = JSON.stringify(skills);
  if (!force && json === _lastSkillsJson) return;   // nothing changed, leave the DOM alone
  _lastSkillsJson = json;

  skillListEl.innerHTML = "";

  if (skills.length === 0) {
    skillListEl.innerHTML = `<div class="empty-hint">Ingen skills funnet. Legg til fra Innstillinger, eller dropp en .txt/.md-fil i skills/-mappen.</div>`;
    return;
  }

  skills.forEach(skill => {
    const item = document.createElement("div");
    item.className = "skill-item";
    const row = document.createElement("div");
    row.className = "skill-row";

    const switchLabel = document.createElement("label");
    switchLabel.className = "skill-switch";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = skill.active;
    checkbox.onchange = () => window.pywebview.api.toggle_skill(skill.id);
    const track = document.createElement("span");
    track.className = "skill-switch-track";
    switchLabel.appendChild(checkbox);
    switchLabel.appendChild(track);

    const nameSpan = document.createElement("span");
    nameSpan.className = "skill-name";
    nameSpan.textContent = skill.name;
    nameSpan.title = skill.name;

    row.appendChild(switchLabel);
    row.appendChild(nameSpan);
    item.appendChild(row);
    skillListEl.appendChild(item);
  });
}

document.getElementById("refresh-skills-btn").onclick = () => refreshSkillList(true);
window.addEventListener("focus", () => refreshSkillList());

// Pick up skill files added/removed outside the app without a restart.
setInterval(() => {
  refreshSkillList();
  const settingsOpen = !document.getElementById("settings-overlay").classList.contains("hidden");
  if (settingsOpen && typeof refreshSettingsSkillList === "function") refreshSettingsSkillList();
}, 2500);
