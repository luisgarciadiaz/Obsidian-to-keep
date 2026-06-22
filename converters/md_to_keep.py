import re
from mistletoe import block_token, span_token


def md_to_keep_text(markdown: str) -> str:
    lines = markdown.split("\n")
    output: list[str] = []
    front_matter_done = False
    in_callout = False
    in_code_block = False
    code_lang = ""
    i = 0

    while i < len(lines):
        line = lines[i]

        if not front_matter_done and line.startswith("---"):
            front_matter_done = True
            i += 1
            while i < len(lines) and not lines[i].startswith("---"):
                i += 1
            i += 1
            continue

        front_matter_done = True

        if line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line[3:].strip()
                output.append(f"[code] {code_lang}")
            else:
                in_code_block = False
                code_lang = ""
            i += 1
            continue

        if in_code_block:
            output.append(f"    {line}")
            i += 1
            continue

        if line.startswith("> [!NOTE]"):
            text = line[10:].strip()
            output.append(f"📌 NOTE: {text}")
            in_callout = True
            i += 1
            continue
        elif line.startswith("> [!WARNING]"):
            text = line[12:].strip()
            output.append(f"⚠️ WARNING: {text}")
            in_callout = True
            i += 1
            continue
        elif line.startswith("> [!TIP]"):
            text = line[9:].strip()
            output.append(f"💡 TIP: {text}")
            in_callout = True
            i += 1
            continue
        elif line.startswith("> ") and in_callout:
            output.append(f"  {line[2:].strip()}")
            i += 1
            continue
        elif line == ">" and in_callout:
            output.append("")
            i += 1
            continue
        else:
            in_callout = False

        if line.startswith("# "):
            output.append(line[2:].strip())
            i += 1
            continue

        if line.startswith("## "):
            output.append(f"**{line[3:].strip()}**")
            i += 1
            continue

        if line.startswith("### "):
            output.append(f"**{line[4:].strip()}**")
            i += 1
            continue

        if re.match(r"^-\s\[ \]\s", line):
            output.append(f"☐ {line[6:].strip()}")
            i += 1
            continue

        if re.match(r"^-\s\[x\]\s", line):
            output.append(f"☑ {line[6:].strip()}")
            i += 1
            continue

        if re.match(r"^[\-\*]\s", line):
            output.append(f"• {line[2:].strip()}")
            i += 1
            continue

        if line.startswith("---"):
            output.append("─────────────")
            i += 1
            continue

        if line.strip() == "":
            output.append("")
            i += 1
            continue

        text = _convert_inline(line)
        output.append(text)
        i += 1

    return "\n".join(output).strip()


def _convert_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"🔗 \1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"**\1**", text)
    text = re.sub(r"\*(.+?)\*", r"*\1*", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def extract_title(markdown: str) -> str:
    for line in markdown.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_tags(markdown: str) -> list[str]:
    tags: list[str] = []
    in_front = False
    for line in markdown.split("\n"):
        if line.startswith("---"):
            if not in_front:
                in_front = True
            else:
                break
        if in_front:
            m = re.match(r"tags:\s*\[(.+)\]", line)
            if m:
                raw = m.group(1)
                tags = [t.strip().strip("'\"") for t in raw.split(",")]
    return tags


def extract_tasks(markdown: str) -> list[tuple[bool, str]]:
    tasks: list[tuple[bool, str]] = []
    for line in markdown.split("\n"):
        m = re.match(r"^- \[([ x])\] (.+)", line)
        if m:
            checked = m.group(1) == "x"
            tasks.append((checked, m.group(2)))
    return tasks
