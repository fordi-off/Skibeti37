// ---------------- Skills (høyre panel - kun av/på) ----------------

const skillListEl = document.getElementById("skill-list");

async function refreshSkillList() {
  const skills = await window.pywebview.api.list_skills();
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
    checkbox.onchange = async () => { await window.pywebview.api.toggle_skill(skill.id); };
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
