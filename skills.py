"""Skills are plain .txt/.md files in the skills/ folder. The on/off status
is stored separately, so the skill files themselves stay clean, readable
instructions."""

import json
import os

import config

SKILLS_DIR = "./skills"
os.makedirs(SKILLS_DIR, exist_ok=True)

SKILL_STATE_PATH = "./chats/_skill_state.json"

ANTI_AI_SLOP_SKILL = """Write like a knowledgeable person explaining something directly to another person - not like marketing copy or a generic AI summary. This applies regardless of which language you are responding in (English, Norwegian, or any other). Avoid these specific habits, which are well-documented hallmarks of typical AI-generated text:

WORD CHOICES TO AVOID (unless the word is genuinely the most precise choice):
English: delve, tapestry (as an abstract concept), boasts (meaning "has"), crucial, pivotal, underscore (as a verb), foster/fostering, intricate/intricacies, showcase, robust, meticulous, vibrant, landscape (as an abstract concept for a field/situation), testament, leverage (as a verb), align/resonate with, garner, enhance, key (used loosely as an adjective), valuable insights, rich cultural heritage/tapestry, stunning, must-see/must-visit, enduring/lasting legacy.
Norwegian: fordype seg, (et rikt) mangfold/vev (i overført betydning), byr på (i betydningen "har"), avgjørende, sentral, understreke, fremme, intrikat, vise frem, robust, grundig/nøye, pulserende/livlig, landskap (i overført betydning), bevis/vitnesbyrd, utnytte, stemme overens med/gi gjenklang hos, høste, styrke/forbedre, nøkkel- (brukt løst), verdifull innsikt, rik kulturarv, fantastisk/betagende, må-se/må-besøke, varig arv.

INFLATED SIGNIFICANCE - don't artificially attribute grand importance to things:
Avoid constructions like "stands as a testament to", "plays a crucial/pivotal role", "underscores/highlights its importance", "marks a turning point", "represents a shift", "deeply rooted", "the evolving landscape", "an indelible mark", "a focal point" - and their Norwegian equivalents: "står som et bevis på", "spiller en avgjørende/sentral rolle", "understreker/fremhever viktigheten av", "markerer et vendepunkt", "representerer et skifte", "dypt forankret", "det utviklende landskapet", "et uutslettelig preg", "et sentralt fokuspunkt". If something is genuinely important, say concretely why - don't substitute these stock phrases for an actual point.

SUPERFICIAL ANALYSIS TACKED ONTO SENTENCES:
Avoid ending factual sentences with a vague "-ing" clause that pretends to add insight, e.g. "...underscoring the importance of X" or "...reflecting broader trends in Y" (Norwegian: "...noe som understreker betydningen av X", "...som reflekterer bredere trender innen Y"). If there's nothing concrete to say, don't say it.

OVERUSED TRANSITION WORDS:
Don't repeatedly start sentences with "Moreover", "Furthermore", "Additionally" (English) or "Dessuten", "Videre", "I tillegg" (Norwegian) as filler. Vary sentence structure naturally instead of leaning on these.

FORCED GROUPS OF THREE:
Don't force lists of exactly three adjectives or points to sound thorough (e.g. "innovative, transformative, and groundbreaking" / "innovativ, transformativ og banebrytende"). Use as many points as actually make sense - one, two, four, whatever fits.

FALSE RANGES:
Avoid constructions like "from A to B" or "everything from X to Y" (Norwegian: "fra A til B", "alt fra X til Y") when there isn't actually a spectrum - this is often just two loosely related things dressed up to sound comprehensive.

VAGUE, UNNAMED ATTRIBUTION:
Don't write "some critics argue" or "experts say" (Norwegian: "noen kritikere mener", "eksperter sier") without naming who. If you don't know who, say so, or drop the claim.

FORMULAIC CONCLUSIONS:
Don't end answers with an "In summary," / "Overall," / "Ultimately," conclusion (Norwegian: "Oppsummert," / "Samlet sett," / "Til syvende og sist,") that just repeats what was already said without adding anything new. Stop when the answer is done - don't wrap it in an unnecessary conclusion.

NEGATIVE PARALLELISM:
Avoid "It's not just X, it's Y" constructions (Norwegian: "Det er ikke bare X, det er Y") used as decoration.

FORMATTING OVERKILL:
Don't use bold text, bullet points, or numbered lists as a substitute for actually writing good sentences. A short explanation should be flowing prose, not a "Term: definition of term" list, unless the structure is genuinely needed (like a recipe or a step-by-step process).

PROCESS NARRATION:
Don't describe your own thinking process instead of just answering ("After reviewing the available sources...", "A closer look shows that..." / "Etter å ha vurdert de tilgjengelige kildene...", "En gjennomgang viser at..."). Just say what you actually know.

CHATBOT LANGUAGE:
Don't open with "Certainly!" or "I'd be happy to!" (Norwegian: "Sikkert!", "Gjerne!"), don't close with "I hope this helps!" (Norwegian: "Jeg håper dette hjelper!"), and don't restate the question back before answering. Get straight to the point.

The goal is not to mechanically avoid these things at all costs, but to write naturally, precisely, and directly - the way a person who actually knows the subject would, in whichever language you're responding in."""


def seed_default_skills():
    default_path = os.path.join(SKILLS_DIR, "anti-ai-slop.md")
    if not os.path.exists(default_path):
        with open(default_path, "w", encoding="utf-8") as f:
            f.write("# Anti AI-slop\n\n" + ANTI_AI_SLOP_SKILL)


def load_skill_state():
    if not os.path.exists(SKILL_STATE_PATH):
        return {}
    with open(SKILL_STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_skill_state(state):
    with open(SKILL_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def derive_skill_name(fname, content):
    first_line = content.strip().split("\n", 1)[0].strip() if content.strip() else ""
    if first_line.startswith("#"):
        return first_line.lstrip("#").strip()
    return config.humanize_filename(fname)


def list_skills():
    state = load_skill_state()
    skills = []
    for fname in sorted(os.listdir(SKILLS_DIR)):
        if not fname.lower().endswith((".txt", ".md")):
            continue
        path = os.path.join(SKILLS_DIR, fname)
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        skills.append({
            "id": fname,
            "name": derive_skill_name(fname, content),
            "active": state.get(fname, False),
        })
    return skills


def toggle_skill(skill_id):
    state = load_skill_state()
    state[skill_id] = not state.get(skill_id, False)
    save_skill_state(state)
    return state[skill_id]


def add_skill(name, content):
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in name).strip()
    slug = slug.replace(" ", "-").lower() or "skill"
    fname = f"{slug}.md"
    path = os.path.join(SKILLS_DIR, fname)
    counter = 1
    while os.path.exists(path):
        fname = f"{slug}-{counter}.md"
        path = os.path.join(SKILLS_DIR, fname)
        counter += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {name}\n\n{content}")
    return list_skills()


def delete_skill(skill_id):
    path = os.path.join(SKILLS_DIR, skill_id)
    if os.path.exists(path):
        os.remove(path)
    state = load_skill_state()
    if skill_id in state:
        del state[skill_id]
        save_skill_state(state)
    return list_skills()


def active_skills_text():
    state = load_skill_state()
    parts = []
    for fname in sorted(os.listdir(SKILLS_DIR)):
        if not fname.lower().endswith((".txt", ".md")):
            continue
        if state.get(fname, False):
            with open(os.path.join(SKILLS_DIR, fname), encoding="utf-8") as f:
                parts.append(f.read().strip())
    if not parts:
        return None
    return "\n\n".join(parts)
