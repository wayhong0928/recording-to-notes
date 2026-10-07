"""check_names 的單元測試：字詞比對、docx 內文（一個詞拆在好幾段）、docx 作者欄位。"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from check_names import docx_authors, docx_text, find_terms, load_terms, read_text  # noqa: E402

CORE = ('<cp:coreProperties xmlns:cp="x" xmlns:dc="y"><dc:creator>{creator}</dc:creator>'
        '<cp:lastModifiedBy>{modified}</cp:lastModifiedBy></cp:coreProperties>')
APP = '<Properties><Company>{company}</Company></Properties>'
# Word 常把一個詞拆在好幾個 run 裡
BODY = ('<w:document><w:body><w:p><w:r><w:t>甲</w:t></w:r><w:r><w:t>乙公司</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>AT&amp;T</w:t></w:r></w:p></w:body></w:document>')


def make_docx(path: Path, creator="python-docx", modified="", company="") -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", BODY)
        z.writestr("docProps/core.xml", CORE.format(creator=creator, modified=modified))
        z.writestr("docProps/app.xml", APP.format(company=company))
    return path


def test_find_terms_ignores_case():
    assert find_terms("Report by ACME Corp", ["acme", "其他"]) == ["acme"]
    assert find_terms("沒有命中", ["acme"]) == []


def test_find_terms_whole_word_for_english():
    assert find_terms("for t in tabs:", ["ab"]) == []
    assert find_terms(r"D:\AB\notes", ["ab"]) == ["ab"]
    assert find_terms("甲乙公司的報告", ["甲乙"]) == ["甲乙"]


def test_read_text_falls_back_to_cp950(tmp_path):
    f = tmp_path / "a.bat"
    f.write_bytes("echo 甲乙公司".encode("cp950"))
    assert read_text(f) == "echo 甲乙公司"
    (tmp_path / "b.bin").write_bytes(b"\0\1\2")
    assert read_text(tmp_path / "b.bin") is None


def test_load_terms_skips_comments_and_blanks(tmp_path):
    f = tmp_path / "list.txt"
    f.write_text("# 註解\n\n甲乙公司\n  Acme  \n", encoding="utf-8")
    assert load_terms(f) == ["甲乙公司", "Acme"]


def test_docx_text_joins_split_runs(tmp_path):
    doc = make_docx(tmp_path / "a.docx")
    assert find_terms(docx_text(doc), ["甲乙公司", "AT&T"]) == ["甲乙公司", "AT&T"]


def test_docx_authors(tmp_path):
    assert docx_authors(make_docx(tmp_path / "ok.docx")) == []
    bad = docx_authors(make_docx(tmp_path / "bad.docx", creator="王小明", company="甲乙公司"))
    assert bad == ["dc:creator=王小明", "Company=甲乙公司"]
