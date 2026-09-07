"""Skills are plain .md files in the skills/ folder. One file can define
several slash commands. The user triggers a command by typing it at the
start of a message (e.g. "/humanize rewrite this"); the command's
instruction text is then added to the system prompt for that one reply.

File format (see skills/ for live examples):

    # Skill name shown in Settings

    ## /command-name  Short description shown in the / menu
    The full instruction the model should follow for this command.
    Everything down to the next "## /..." heading (or end of file)
    is the instruction body.

    ## /another-command
    Description on its own first line if you didn't put it on the heading.

    The instruction body for this one.
"""

import os
import re

import config

SKILLS_DIR = "./skills"
os.makedirs(SKILLS_DIR, exist_ok=True)

# Matches a command heading: "## /name" with an optional inline description.
_COMMAND_HEADING = re.compile(r"^##\s+/([A-Za-z0-9_-]+)[ \t]*(.*)$")


WRITING_SKILL = """# Skrivehjelp

## /humanize  Fjern AI-preg – skriv naturlig og direkte
Write like a knowledgeable person explaining something directly to another person - not like marketing copy or a generic AI summary. This applies regardless of which language you are responding in (English, Norwegian, or any other). Avoid these specific habits, which are well-documented hallmarks of typical AI-generated text:

WORD CHOICES TO AVOID (unless the word is genuinely the most precise choice):
English: delve, tapestry (as an abstract concept), boasts (meaning "has"), crucial, pivotal, underscore (as a verb), foster/fostering, intricate/intricacies, showcase, robust, meticulous, vibrant, landscape (as an abstract concept for a field/situation), testament, leverage (as a verb), align/resonate with, garner, enhance, key (used loosely as an adjective), valuable insights, rich cultural heritage/tapestry, stunning, must-see/must-visit, enduring/lasting legacy.
Norwegian: fordype seg, (et rikt) mangfold/vev (i overført betydning), byr på (i betydningen "har"), avgjørende, sentral, understreke, fremme, intrikat, vise frem, robust, grundig/nøye, pulserende/livlig, landskap (i overført betydning), bevis/vitnesbyrd, utnytte, stemme overens med/gi gjenklang hos, høste, styrke/forbedre, nøkkel- (brukt løst), verdifull innsikt, rik kulturarv, fantastisk/betagende, må-se/må-besøke, varig arv.

INFLATED SIGNIFICANCE - don't artificially attribute grand importance to things:
Avoid constructions like "stands as a testament to", "plays a crucial/pivotal role", "underscores/highlights its importance", "marks a turning point", "represents a shift", "deeply rooted", "the evolving landscape", "an indelible mark", "a focal point" - and their Norwegian equivalents. If something is genuinely important, say concretely why - don't substitute these stock phrases for an actual point.

SUPERFICIAL ANALYSIS TACKED ONTO SENTENCES:
Avoid ending factual sentences with a vague "-ing" clause that pretends to add insight, e.g. "...underscoring the importance of X" or "...reflecting broader trends in Y". If there's nothing concrete to say, don't say it.

OVERUSED TRANSITION WORDS:
Don't repeatedly start sentences with "Moreover", "Furthermore", "Additionally" (English) or "Dessuten", "Videre", "I tillegg" (Norwegian) as filler. Vary sentence structure naturally.

FORCED GROUPS OF THREE:
Don't force lists of exactly three adjectives or points to sound thorough. Use as many points as actually make sense.

FALSE RANGES:
Avoid "from A to B" or "everything from X to Y" when there isn't actually a spectrum.

VAGUE, UNNAMED ATTRIBUTION:
Don't write "some critics argue" or "experts say" without naming who. If you don't know who, say so, or drop the claim.

FORMULAIC CONCLUSIONS:
Don't end with an "In summary," / "Overall," / "Ultimately," conclusion that just repeats what was already said. Stop when the answer is done.

NEGATIVE PARALLELISM:
Avoid "It's not just X, it's Y" constructions used as decoration.

FORMATTING OVERKILL:
Don't use bold text, bullet points or numbered lists as a substitute for writing good sentences. A short explanation should be flowing prose unless the structure is genuinely needed.

PROCESS NARRATION:
Don't describe your own thinking process instead of just answering. Just say what you actually know.

CHATBOT LANGUAGE:
Don't open with "Certainly!" or "I'd be happy to!", don't close with "I hope this helps!", and don't restate the question back before answering. Get straight to the point.

The goal is not to mechanically avoid these things at all costs, but to write naturally, precisely and directly - the way a person who actually knows the subject would, in whichever language you're responding in.

## /kort  Stram inn svaret til det viktigste
Answer in as few words as the question honestly allows.

- Cut throat-clearing, filler transitions and any restatement of the question.
- No preamble and no summary paragraph - lead with the answer.
- Prefer plain sentences over lists unless the content is genuinely a sequence of steps.
- Keep every concrete fact, number and caveat that actually matters; only cut padding.

Reply in whatever language the person is using.

## /enkelt  Forklar som til en smart 12-åring
Explain things as if to a curious 12-year-old who is smart but new to the topic.

- Short sentences. One idea per sentence.
- Start from something they already know, then build up.
- Use a concrete everyday example or analogy for anything abstract.
- The first time you use a technical term, define it in plain words right there.
- No long preambles - get to the explanation.

Don't oversimplify to the point of being wrong. Reply in whatever language the person is using.
"""


LANGUAGE_SKILL = """# Språk

## /norsk  Svar på klar, korrekt bokmål
Reply in Norwegian bokmål for this message, even if the question is written in another language.

- Natural, idiomatic Norwegian - not a word-for-word translation.
- Plain and clear: everyday words over bureaucratic ones, reasonably short sentences.
- Keep technical terms that have no good Norwegian equivalent, but explain them the first time.

## /korrektur  Korrekturles norsk tekst, behold stemmen
Use this to proofread or improve a piece of Norwegian text.

- Fix spelling, grammar, punctuation and clearly awkward phrasing.
- Keep the author's own voice, tone and vocabulary. Don't rewrite it into your own style.
- Don't add new content, arguments or examples. Don't remove content unless it's pure duplication.
- Keep the author's target norm (bokmål or nynorsk) - don't switch it.
- Output: first the corrected text, then a short bullet list of the substantive changes (skip trivial typo fixes).

If the text is already clean, say so instead of inventing changes.
"""


TUTOR_SKILL = """# Tutor

## /tutor  Veiled steg for steg, ikke gi fasiten
Act as a patient tutor, not an answer key. The person is trying to learn, so do not hand over the finished solution.

- Break the problem into smaller steps and work through one at a time.
- Ask a guiding question, or give the next small hint, then stop and let them try.
- If they're stuck, narrow the hint - don't jump to the answer.
- When they get something right, say briefly why it works.
- Only give the full worked solution if they explicitly ask for it after trying, and even then explain each step.
- For code: point at the line or concept that's wrong and why, rather than pasting corrected code.

Keep replies short. This applies in whatever language the person is using.
"""

_SEEDS = {
    "writing.md": WRITING_SKILL,
    "language.md": LANGUAGE_SKILL,
    "tutor.md": TUTOR_SKILL,
}


def seed_default_skills():
    for fname, text in _SEEDS.items():
        path = os.path.join(SKILLS_DIR, fname)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text.strip() + "\n")


def _parse_text(fname, text):
    """Return {file, name, commands:[{command, description, body}]} for one
    skill file. Lines before the first "## /" heading are ignored except for
    a leading "# ..." which becomes the skill's display name."""
    lines = text.splitlines()
    name = config.humanize_filename(fname)
    commands = []
    current = None

    for line in lines:
        m = _COMMAND_HEADING.match(line)
        if m:
            if current:
                commands.append(current)
            inline_desc = m.group(2).strip()
            current = {"command": m.group(1).lower(), "description": inline_desc, "body_lines": []}
            continue
        if current is None:
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("##"):
                name = stripped.lstrip("#").strip() or name
            continue
        current["body_lines"].append(line)

    if current:
        commands.append(current)

    cleaned = []
    for c in commands:
        body_lines = c.pop("body_lines")
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        if not c["description"] and body_lines:
            c["description"] = body_lines.pop(0).strip()
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)
        c["body"] = "\n".join(body_lines).strip()
        if c["command"] and c["body"]:
            cleaned.append(c)

    return {"file": fname, "name": name, "commands": cleaned}


def _all_parsed():
    parsed = []
    for fname in sorted(os.listdir(SKILLS_DIR)):
        if not fname.lower().endswith((".txt", ".md")):
            continue
        with open(os.path.join(SKILLS_DIR, fname), encoding="utf-8") as f:
            parsed.append(_parse_text(fname, f.read()))
    return parsed


def list_commands():
    """Flat list of every command across all skill files, for the / menu and
    the right-hand reference panel. Later files win on a name clash."""
    seen = {}
    for skill in _all_parsed():
        for c in skill["commands"]:
            seen[c["command"]] = {
                "command": c["command"],
                "description": c["description"],
                "skill": skill["name"],
            }
    return sorted(seen.values(), key=lambda c: c["command"])


def list_skills():
    """Grouped by file, for the Settings tab (create / delete)."""
    return [
        {
            "id": s["file"],
            "name": s["name"],
            "commands": [
                {"command": c["command"], "description": c["description"]}
                for c in s["commands"]
            ],
        }
        for s in _all_parsed()
    ]


def command_bodies(command_names):
    """Concatenated instruction text for the given command names, in order.
    Unknown names are skipped. Returns None if nothing matched."""
    if not command_names:
        return None
    wanted = [str(n).lstrip("/").lower() for n in command_names]
    index = {}
    for skill in _all_parsed():
        for c in skill["commands"]:
            index[c["command"]] = c["body"]
    parts = [index[n] for n in wanted if n in index]
    return "\n\n".join(parts) if parts else None


def add_skill(name, content):
    """Write a new skill file. `content` is the raw markdown in the format
    above. Raises ValueError if it defines no usable command."""
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in name).strip()
    slug = slug.replace(" ", "-").lower() or "skill"

    text = content.strip()
    if not any(_COMMAND_HEADING.match(ln) for ln in text.splitlines()):
        raise ValueError(
            "Fant ingen kommando. Hver kommando starter med en linje som '## /navn'."
        )
    if not _parse_text(f"{slug}.md", f"# {name}\n\n{text}")["commands"]:
        raise ValueError(
            "Kommandoen mangler instruksjonstekst under '## /navn'-linjen."
        )

    fname = f"{slug}.md"
    path = os.path.join(SKILLS_DIR, fname)
    counter = 1
    while os.path.exists(path):
        fname = f"{slug}-{counter}.md"
        path = os.path.join(SKILLS_DIR, fname)
        counter += 1

    header = "" if text.lstrip().startswith("#") and not text.lstrip().startswith("##") else f"# {name}\n\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + text + "\n")
    return list_skills()


def delete_skill(skill_id):
    path = os.path.join(SKILLS_DIR, skill_id)
    if os.path.exists(path):
        os.remove(path)
    return list_skills()
