from converters.keep_to_md import keep_to_md
from converters.md_to_keep import extract_tags, extract_tasks, extract_title, md_to_keep_text


class TestMdToKeep:
    def test_heading_conversion(self):
        md = "# My Title\n\n## Section\n\n### Subsection"
        result = md_to_keep_text(md)
        assert "My Title" in result
        assert "**Section**" in result
        assert "**Subsection**" in result

    def test_task_conversion(self):
        md = "- [ ] Todo item\n- [x] Done item"
        result = md_to_keep_text(md)
        assert "☐ Todo item" in result
        assert "☑ Done item" in result

    def test_unordered_list(self):
        md = "- Item one\n- Item two"
        result = md_to_keep_text(md)
        assert "• Item one" in result
        assert "• Item two" in result

    def test_callout_note(self):
        md = "> [!NOTE] This is a note"
        result = md_to_keep_text(md)
        assert "📌 NOTE: This is a note" in result

    def test_callout_warning(self):
        md = "> [!WARNING] Careful"
        result = md_to_keep_text(md)
        assert "⚠️ WARNING: Careful" in result

    def test_inline_link(self):
        md = "See [Google](https://google.com)"
        result = md_to_keep_text(md)
        assert "Google (https://google.com)" in result

    def test_wikilink(self):
        md = "See [[My Note]]"
        result = md_to_keep_text(md)
        assert "🔗 My Note" in result

    def test_horizontal_rule(self):
        md = "---"
        result = md_to_keep_text(md)
        assert "─────────────" in result

    def test_front_matter_stripped(self):
        md = "---\ntitle: Test\ntags: [a, b]\n---\n\n# Hello"
        result = md_to_keep_text(md)
        assert "Hello" in result
        assert "title:" not in result

    def test_empty_content(self):
        assert md_to_keep_text("") == ""

    def test_extract_title(self):
        md = "# Hello World\n\nSome text"
        assert extract_title(md) == "Hello World"

    def test_extract_tags_from_front_matter(self):
        md = "---\ntitle: Test\ntags: [tag1, tag2]\n---\n\n# Hello"
        assert extract_tags(md) == ["tag1", "tag2"]

    def test_extract_tasks(self):
        md = "- [ ] Task 1\n- [x] Task 2"
        tasks = extract_tasks(md)
        assert tasks == [(False, "Task 1"), (True, "Task 2")]


class TestKeepToMd:
    def test_basic_round_trip(self):
        original = "# Title\n\nSome **bold** text.\n\n- [ ] Task\n- [x] Done"
        keep_text = md_to_keep_text(original)
        result = keep_to_md("Title", keep_text)
        assert "Title" in result
        assert "- [ ] Task" in result
        assert "- [x] Done" in result
        assert "**bold**" in result

    def test_callout_round_trip(self):
        md = "# Note\n\n> [!NOTE] Important info"
        keep_text = md_to_keep_text(md)
        result = keep_to_md("Note", keep_text)
        assert "[!NOTE]" in result
        assert "Important info" in result

    def test_wikilink_round_trip(self):
        md = "# Links\n\nSee [[Other Note]]"
        keep_text = md_to_keep_text(md)
        result = keep_to_md("Links", keep_text)
        assert "[[Other Note]]" in result

    def test_code_block(self):
        md = "# Code\n\n```python\nprint('hello')\n```"
        keep_text = md_to_keep_text(md)
        result = keep_to_md("Code", keep_text)
        assert "```python" in result
        assert "print('hello')" in result

    def test_front_matter_generated(self):
        result = keep_to_md("My Note", "Some text", tags=["tag1"])
        assert "---" in result
        assert 'title: "My Note"' in result
        assert "keep_id: PLACEHOLDER" in result
        assert '"tag1"' in result

    def test_multiline_callout(self):
        md = "# Note\n\n> [!NOTE] Header\n> line 2\n> line 3"
        keep_text = md_to_keep_text(md)
        result = keep_to_md("Note", keep_text)
        assert "[!NOTE]" in result
        assert "Header" in result or "line 2" in result
