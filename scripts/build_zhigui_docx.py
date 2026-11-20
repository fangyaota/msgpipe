#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 待办/职规材料 下的 md 初稿转成 docx（中文排版：黑体标题、宋体正文、小四、1.5 倍行距）。"""
import io
import os
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, Cm

SRC = r"D:\Workspace\msgpipe\待办\职规材料"


def set_font(run, name="宋体", size=12, bold=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def add_para(doc, text, style=None, font="宋体", size=12, bold=False,
             first_indent=True, align=None, space_after=6):
    p = doc.add_paragraph(style=style)
    if first_indent:
        p.paragraph_format.first_line_indent = Pt(size * 2)
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(space_after)
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    set_font(run, font, size, bold)
    return p


def inline_runs(doc, text, size=12):
    """处理 **加粗** 片段。"""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Pt(size * 2)
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(6)
    for i, seg in enumerate(re.split(r"(\*\*[^*]+\*\*)", text)):
        if not seg:
            continue
        if seg.startswith("**") and seg.endswith("**"):
            run = p.add_run(seg[2:-2])
            set_font(run, "宋体", size, bold=True)
        else:
            run = p.add_run(seg)
            set_font(run, "宋体", size)
    return p


def build(md_path, docx_path, title):
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(3.17)

    # 文档标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(18)
    run = p.add_run(title)
    set_font(run, "黑体", 18, bold=True)

    lines = io.open(md_path, encoding="utf-8").read().splitlines()
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# "):
            continue  # 标题已单独加
        if line.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(line[3:].strip())
            set_font(run, "黑体", 14, bold=True)
            continue
        if line.startswith("> "):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(24)
            p.paragraph_format.line_spacing = 1.5
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(line[2:].strip().replace("**", ""))
            set_font(run, "楷体", 10.5)
            run.italic = True
            continue
        if line.startswith("---"):
            continue
        if re.match(r"^\d+\.\s", line.strip()) or line.strip().startswith("- "):
            body = re.sub(r"^\s*(-\s+|\d+\.\s)", "", line)
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(24)
            p.paragraph_format.line_spacing = 1.5
            p.paragraph_format.space_after = Pt(4)
            for i, seg in enumerate(re.split(r"(\*\*[^*]+\*\*)", body)):
                if not seg:
                    continue
                if seg.startswith("**") and seg.endswith("**"):
                    set_font(p.add_run(seg[2:-2]), "宋体", 12, bold=True)
                else:
                    set_font(p.add_run(seg), "宋体", 12)
            continue
        inline_runs(doc, line, 12)

    doc.save(docx_path)
    return docx_path


if __name__ == "__main__":
    jobs = [
        ("许绵星 26012768 职业生涯规划初步构想.md",
         "许绵星 26012768 职业生涯规划初步构想.docx", "职业生涯规划初步构想"),
        ("许绵星 26012768 生涯人物访谈报告01 彭老师.md",
         "许绵星 26012768 生涯人物访谈报告01 彭老师.docx", "生涯人物访谈报告（一）"),
        ("许绵星 26012768 生涯人物访谈报告02 张谷令老师.md",
         "许绵星 26012768 生涯人物访谈报告02 张谷令老师.docx", "生涯人物访谈报告（二）"),
    ]
    for md, dx, title in jobs:
        out = build(os.path.join(SRC, md), os.path.join(SRC, dx), title)
        print("[ok]", os.path.basename(out), os.path.getsize(out), "bytes")
