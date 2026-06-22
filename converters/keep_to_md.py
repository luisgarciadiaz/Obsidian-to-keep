import re
from typing import Optional


def keep_to_md(title: str, text: str, tags: Optional[list[str]] = None) -> str:
    lines = text.split("\n")
    output: list[str] = []
    in_code_block = False
    in_callout = False
    callout_type = ""
    callout_lines: list[str] = []
    first_line_used = False

    front_matter_lines: list[str] = ["---"]
    if title:
        front_matter_lines.append(f'title: "{title}"')
    if tags:
        tag_str = ", ".join(f'"{t}"' for t in tags)
        front_matter_lines.append(f"tags: [{tag_str}]")
    front_matter_lines.append("keep_id: PLACEHOLDER")
    front_matter_lines.append("---")

    output.append(f"# {title}")
    output.append("")

    def flush_callout():
        nonlocal in_callout, callout_type
        if in_callout:
            callout_header = f"> [!{callout_type}]"
            if callout_lines:
                output.append(f"{callout_header} {callout_lines[0]}")
                for cl in callout_lines[1:]:
                    if cl:
                        output.append(f"> {cl}")
                    else:
                        output.append(">")
            else:
                output.append(callout_header)
            in_callout = False
            callout_type = ""
            callout_lines.clear()

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("[code]"):
            flush_callout()
            in_code_block = True
            lang = stripped[6:].strip()
            output.append(f"```{lang}")
            continue

        if in_code_block:
            if stripped == "":
                output.append("")
                continue
            if line.startswith("    "):
                output.append(line[4:])
                continue
            else:
                output.append("```")
                in_code_block = False
                output.append("")
                continue

        m_callout = re.match(r"^(📌|⚠️|💡)\s+(NOTE|WARNING|TIP):\s*(.*)", stripped)
        if m_callout:
            flush_callout()
            icon_map = {"📌": "NOTE", "⚠️": "WARNING", "💡": "TIP"}
            callout_type = icon_map.get(m_callout.group(1), m_callout.group(2))
            in_callout = True
            callout_lines = [m_callout.group(3)] if m_callout.group(3) else []
            continue

        if in_callout and stripped.startswith("📌") and not re.match(r"^(📌|⚠️|💡)\s+(NOTE|WARNING|TIP):", stripped):
            callout_lines.append(stripped[1:].strip())
            continue
        if in_callout and re.match(r"^(📌|⚠️|💡)\s+", stripped):
            flush_callout()

        if in_callout and (stripped == "" or not stripped.startswith(("📌", "⚠️", "💡"))):
            if stripped.startswith("  "):
                callout_lines.append(stripped.strip())
                continue
            else:
                flush_callout()

        if stripped == "":
            flush_callout()
            output.append("")
            continue

        if re.match(r"^☐\s", stripped):
            flush_callout()
            output.append(f"- [ ] {stripped[1:].strip()}")
            continue

        if re.match(r"^☑\s", stripped):
            flush_callout()
            output.append(f"- [x] {stripped[1:].strip()}")
            continue

        if re.match(r"^•\s", stripped):
            flush_callout()
            output.append(f"- {stripped[1:].strip()}")
            continue

        m_bold_heading = re.match(r"^\*\*(.+?)\*\*$", stripped)
        if m_bold_heading:
            flush_callout()
            output.append(f"## {m_bold_heading.group(1)}")
            continue

        if stripped.startswith("─────────────"):
            flush_callout()
            output.append("---")
            continue

        if re.match(r"^🔗\s", stripped):
            flush_callout()
            wikilink = stripped[1:].strip()
            output.append(f"[[{wikilink}]]")
            continue

        m_url = re.match(r"^(.+?)\s\(https?://\S+\)$", stripped)
        if m_url:
            text_part = m_url.group(1)
            url_match = re.search(r"\(https?://\S+\)", stripped)
            if url_match:
                url = url_match.group(0)[1:-1]
                output.append(f"[{text_part}]({url})")
                continue

        flush_callout()
        output.append(_restore_inline(stripped))

    flush_callout()
    if in_code_block:
        output.append("```")

    body = "\n".join(output)
    return "\n".join(front_matter_lines) + "\n\n" + body


def _restore_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"**\1**", text)
    text = re.sub(r"\*(.+?)\*", r"*\1*", text)
    return text
