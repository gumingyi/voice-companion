import re
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

VARIABLES = {"question", "history", "background", "style", "format", "length"}

def expand(text, values):
    unknown = set(re.findall(r"\{([a-z_]+)\}", text)) - VARIABLES
    if unknown:
        raise ValueError("未知模板变量：" + ", ".join(sorted(unknown)))
    return re.sub(r"\{([a-z_]+)\}", lambda m: values[m[1]], text)

def assemble(template, question, history, background, budget):
    # Character budget bounds the *whole* request, including duplicated template variables.
    values = {"question": question.strip(), "background": background, "history": "",
              "style": template["style"], "format": template["format"], "length": template["length"]}
    if not values["question"]:
        raise ValueError("问题不能为空")
    pairs = [(x["question"], x["answer"]) for x in history if x.get("status") == "done"]
    chosen = []
    def build():
        values["history"] = "\n".join(f"问：{q}\n答：{a}" for q, a in chosen)
        messages = [{"role": "system", "content": expand(template["system"], values)}]
        # History template variable is optional; avoid including it twice.
        if "{history}" not in template["system"] + template["user"]:
            for q, a in chosen:
                messages.extend([{"role": "user", "content": q}, {"role": "assistant", "content": a}])
        messages.append({"role": "user", "content": expand(template["user"], values)})
        return messages
    if sum(len(x["content"]) for x in build()) > budget:
        raise ValueError("当前问题与背景资料超过上下文字符预算，请精简资料或提高预算")
    for pair in reversed(pairs):
        chosen.insert(0, pair)
        if sum(len(x["content"]) for x in build()) > budget:
            chosen.pop(0)
            break
    return build()

def read_material(path):
    path = Path(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("资料文件上限10MB")
    if path.suffix.lower() in (".txt", ".md"):
        return path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > 20 * 1024 * 1024:
                raise ValueError("文档解压后过大")
            root = ET.fromstring(z.read(info))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            return "\n".join("".join(p.itertext()) for p in root.findall(".//w:p", ns))
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    raise ValueError("支持 UTF-8 TXT、MD、DOCX、文本型 PDF；扫描件不支持 OCR")
