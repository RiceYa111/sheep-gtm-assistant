from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys


from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)


from reportlab.pdfbase.cidfonts import UnicodeCIDFont
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


NAVY = colors.HexColor("#102742")
NAVY_DARK = colors.HexColor("#08192D")
BLUE = colors.HexColor("#3E72C5")
BLUE_LIGHT = colors.HexColor("#EAF2FC")
GOLD = colors.HexColor("#E8A93D")
TEXT = colors.HexColor("#21354C")
MUTED = colors.HexColor("#63788F")
LINE = colors.HexColor("#D7E2EF")
WHITE = colors.white


def _styles():
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=sample["Title"], fontName="STSong-Light", fontSize=25,
                                leading=34, textColor=WHITE, alignment=TA_LEFT, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName="STSong-Light", fontSize=10.5, leading=17,
                                   textColor=colors.HexColor("#BCD1E8")),
        "section": ParagraphStyle("section", fontName="STSong-Light", fontSize=15, leading=22,
                                  textColor=NAVY, spaceBefore=8, spaceAfter=8),
        "body": ParagraphStyle("body", fontName="STSong-Light", fontSize=10.5, leading=18,
                               textColor=TEXT, spaceAfter=6),
        "small": ParagraphStyle("small", fontName="STSong-Light", fontSize=8.5, leading=13, textColor=MUTED),
        "card_label": ParagraphStyle("card_label", fontName="STSong-Light", fontSize=8.5, leading=12,
                                     textColor=BLUE),
        "card_value": ParagraphStyle("card_value", fontName="STSong-Light", fontSize=14, leading=20,
                                     textColor=NAVY),
        "card_note": ParagraphStyle("card_note", fontName="STSong-Light", fontSize=8, leading=12, textColor=MUTED),
        "callout": ParagraphStyle("callout", fontName="STSong-Light", fontSize=10.5, leading=18, textColor=TEXT),
        "table": ParagraphStyle("table", fontName="STSong-Light", fontSize=8.2, leading=12, textColor=TEXT),
        "table_head": ParagraphStyle("table_head", fontName="STSong-Light", fontSize=8.2, leading=12,
                                     textColor=WHITE, alignment=TA_CENTER),
    }


def _header_footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(NAVY_DARK)
    canvas.rect(0, height - 15 * mm, width, 15 * mm, fill=1, stroke=0)
    canvas.setFont("STSong-Light", 8.5)
    canvas.setFillColor(colors.HexColor("#D9E8F7"))
    canvas.drawString(18 * mm, height - 9.5 * mm, "小羊分析助手 | GTM分析报告")
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.setFont("STSong-Light", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8 * mm, "模拟销量仅用于Demo框架验证")
    canvas.drawRightString(width - 18 * mm, 8 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def _p(text, style):
    safe = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def build_gtm_pdf(title, subtitle, meta_rows, sections, footnote="") -> bytes:
    styles = _styles()
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=23 * mm, bottomMargin=18 * mm, title=title,
                            author="小羊分析助手")
    story = []

    cover = Table([[Paragraph(title, styles["title"])], [Paragraph(subtitle, styles["subtitle"])]],
                  colWidths=[174 * mm])
    cover.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY_DARK), ("BOX", (0, 0), (-1, -1), 0, NAVY_DARK),
        ("LEFTPADDING", (0, 0), (-1, -1), 16), ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, 0), 16), ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 2), ("BOTTOMPADDING", (0, 1), (-1, 1), 16),
    ]))
    story += [cover, Spacer(1, 7 * mm)]

    meta_data = [[_p(label, styles["card_label"]), _p(value, styles["body"])] for label, value in meta_rows]
    meta = Table(meta_data, colWidths=[30 * mm, 144 * mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE_LIGHT), ("BOX", (0, 0), (-1, -1), .7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .35, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [meta, Spacer(1, 5 * mm)]

    for section in sections:
        blocks = [Paragraph(section["title"], styles["section"])]
        if section.get("cards"):
            cards = []
            for label, value, note in section["cards"]:
                cards.append(Table([
                    [_p(label, styles["card_label"])], [_p(value, styles["card_value"])],
                    [_p(note, styles["card_note"])]
                ], colWidths=[40.5 * mm], style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F8FC")),
                    ("BOX", (0, 0), (-1, -1), .65, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ])))
            while len(cards) % 4:
                cards.append("")
            for start in range(0, len(cards), 4):
                row = Table([cards[start:start + 4]], colWidths=[43.5 * mm] * 4)
                row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 1.5), ("RIGHTPADDING", (0, 0), (-1, -1), 1.5)]))
                blocks += [row, Spacer(1, 2.5 * mm)]
        if section.get("body"):
            body = Table([[_p(section["body"], styles["callout"])]], colWidths=[174 * mm])
            body.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F6FD")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, BLUE), ("BOX", (0, 0), (-1, -1), .5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]))
            blocks += [body, Spacer(1, 3 * mm)]
        if section.get("table"):
            table_spec = section["table"]
            table_data = [[_p(value, styles["table_head"]) for value in table_spec["headers"]]]
            table_data += [[_p(value, styles["table"]) for value in row] for row in table_spec["rows"]]
            widths = table_spec.get("widths") or [174 * mm / len(table_spec["headers"])] * len(table_spec["headers"])
            table = Table(table_data, colWidths=widths, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), .65, LINE),
                ("INNERGRID", (0, 0), (-1, -1), .35, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#F7F9FC")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            blocks += [table, Spacer(1, 3 * mm)]
        story.append(KeepTogether(blocks) if section.get("keep", True) else blocks[0])
        if not section.get("keep", True):
            story.extend(blocks[1:])

    if footnote:
        story += [Spacer(1, 4 * mm), _p(footnote, styles["small"])]
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return stream.getvalue()


def build_strategy_onepage_pdf(target_name, scope_text, version_name, generated_at, result, footnote="") -> bytes:
    """Render a compact, white-background A4 strategy one-pager."""
    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    width, height = A4
    margin = 15 * mm
    content_width = width - margin * 2

    def text_width(value, font="STSong-Light", size=9):
        return pdfmetrics.stringWidth(str(value), font, size)

    def wrap(value, max_width, font="STSong-Light", size=9, max_lines=None):
        lines=[]
        raw=str(value or "")
        for paragraph in raw.splitlines() or [""]:
            current=""
            for char in paragraph:
                candidate=current+char
                if current and text_width(candidate,font,size)>max_width:
                    lines.append(current); current=char
                    if max_lines and len(lines)>=max_lines: break
                else: current=candidate
            if max_lines and len(lines)>=max_lines: break
            lines.append(current)
        if max_lines and len(lines)>max_lines: lines=lines[:max_lines]
        if max_lines and len(lines)==max_lines and len("".join(lines))<len(raw.replace("\n","")):
            lines[-1]=(lines[-1][:-1]+"…") if lines[-1] else "…"
        return lines or [""]

    def draw_lines(value, x, y, max_width, font="STSong-Light", size=9, color=TEXT, leading=13, max_lines=None):
        page.setFont(font, size)
        page.setFillColor(color)
        lines = wrap(value, max_width, font, size, max_lines)
        for line in lines:
            page.drawString(x, y, line)
            y -= leading
        return y

    page.setFillColor(WHITE)
    page.rect(0, 0, width, height, fill=1, stroke=0)
    page.setFillColor(NAVY_DARK)
    page.roundRect(margin, height - 42 * mm, content_width, 27 * mm, 5 * mm, fill=1, stroke=0)
    page.setFont("STSong-Light", 21)
    page.setFillColor(WHITE)
    page.drawString(margin + 8 * mm, height - 27 * mm, f"{target_name} 策略一页纸")
    page.setFont("STSong-Light", 8.5)
    page.setFillColor(colors.HexColor("#C8DBEF"))
    page.drawString(margin + 8 * mm, height - 34 * mm, f"{version_name} | {scope_text}")
    page.drawRightString(width - margin - 8 * mm, height - 34 * mm, generated_at)

    y = height - 49 * mm
    page.setFont("STSong-Light", 13)
    page.setFillColor(NAVY)
    page.drawString(margin, y, "主结论")
    y -= 6 * mm
    verdict_height = 28 * mm
    page.setFillColor(colors.HexColor("#EEF4FC"))
    page.setStrokeColor(colors.HexColor("#BFD2E8"))
    page.roundRect(margin, y - verdict_height, content_width, verdict_height, 3.5 * mm, fill=1, stroke=1)
    draw_lines(result.get("主结论", ""), margin + 7 * mm, y - 9 * mm, content_width - 14 * mm,
               font="STSong-Light", size=11, color=NAVY, leading=16, max_lines=3)
    y -= verdict_height + 8 * mm

    page.setFont("STSong-Light", 13)
    page.setFillColor(NAVY)
    page.drawString(margin, y, "关键机会点")
    y -= 5 * mm
    card_gap = 3 * mm
    card_width = (content_width - card_gap * 2) / 3
    card_height = 64 * mm
    accents = [colors.HexColor("#3978C7"), colors.HexColor("#DA8A28"), colors.HexColor("#269978")]
    for index, item in enumerate((result.get("关键机会点") or [])[:3]):
        x = margin + index * (card_width + card_gap)
        page.setFillColor(colors.HexColor("#F8FAFD"))
        page.setStrokeColor(colors.HexColor("#D5E0EC"))
        page.roundRect(x, y - card_height, card_width, card_height, 3 * mm, fill=1, stroke=1)
        page.setFillColor(accents[index])
        page.roundRect(x, y - 3 * mm, card_width, 3 * mm, 1.5 * mm, fill=1, stroke=0)
        page.setFont("STSong-Light", 8.5)
        page.drawString(x + 5 * mm, y - 10 * mm, str(item.get("机会类型", "机会")))
        draw_lines(item.get("机会名称", ""), x + 5 * mm, y - 17 * mm, card_width - 10 * mm,
                   font="STSong-Light", size=9.2, color=NAVY, leading=11, max_lines=2)
        page.setFont("STSong-Light", 7.5)
        page.setFillColor(MUTED)
        page.drawString(x + 5 * mm, y - 29 * mm, "关键依据")
        draw_lines(item.get("关键依据", ""), x + 5 * mm, y - 34 * mm, card_width - 10 * mm,
                   size=7.2, color=TEXT, leading=8, max_lines=4)
        page.setFont("STSong-Light", 7.5)
        page.setFillColor(accents[index])
        page.drawString(x + 5 * mm, y - 50 * mm, "落地建议")
        draw_lines(item.get("落地建议", item.get("策略含义", "")), x + 5 * mm, y - 55 * mm, card_width - 10 * mm,
                   size=7.2, color=TEXT, leading=8, max_lines=3)
    y -= card_height + 8 * mm

    page.setFont("STSong-Light", 13)
    page.setFillColor(NAVY)
    page.drawString(margin, y, "核心策略")
    y -= 5 * mm
    strategies = (result.get("核心策略") or [])[:3]
    strategy_text = " ｜ ".join(f'{item.get("策略名称", "")}：{item.get("策略路径", "")}' for item in strategies)
    page.setFillColor(colors.HexColor("#EDF4FE"))
    page.setStrokeColor(colors.HexColor("#C9D9EA"))
    strategy_height=17*mm
    page.roundRect(margin, y - strategy_height, content_width, strategy_height, 2.5 * mm, fill=1, stroke=1)
    draw_lines(strategy_text, margin + 5 * mm, y - 6 * mm, content_width - 10 * mm,
               font="STSong-Light", size=7.8, color=NAVY, leading=9, max_lines=3)
    y -= strategy_height + 5 * mm
    stages = (result.get("阶段计划") or [])[:4]
    tasks = result.get("角色任务") or []
    role_names = []
    for task in tasks:
        if task.get("角色") and task.get("角色") not in role_names:
            role_names.append(task.get("角色"))
    role_names = role_names[:6]
    col_widths = [27 * mm] + [(content_width - 27 * mm) / 4] * 4
    row_height = 12.5 * mm
    head_height = 10 * mm
    x_positions = [margin]
    for item_width in col_widths:
        x_positions.append(x_positions[-1] + item_width)
    page.setFillColor(NAVY)
    page.roundRect(margin, y - head_height, content_width, head_height, 2 * mm, fill=1, stroke=0)
    headers = ["参与角色"] + [f'{item.get("阶段", "")}\n{item.get("时间", "")}' for item in stages]
    for index, label in enumerate(headers):
        page.setFont("STSong-Light", 7.7)
        page.setFillColor(WHITE)
        draw_lines(label, x_positions[index] + 2.5 * mm, y - 4.5 * mm, col_widths[index] - 5 * mm,
                   font="STSong-Light", size=7.2, color=WHITE, leading=8, max_lines=2)
    y -= head_height
    row_colors = [colors.HexColor("#EDF4FE"), colors.HexColor("#ECF8F5"), colors.HexColor("#FFF6E9"), colors.HexColor("#F3F0FD")]
    stage_names = [str(item.get("阶段", "")) for item in stages]
    for row_index, role in enumerate(role_names):
        page.setFillColor(row_colors[row_index % len(row_colors)])
        page.setStrokeColor(colors.HexColor("#D8E2ED"))
        page.rect(margin, y - row_height, content_width, row_height, fill=1, stroke=1)
        for boundary in x_positions[1:-1]:
            page.line(boundary, y, boundary, y - row_height)
        draw_lines(role, x_positions[0] + 3 * mm, y - 7 * mm, col_widths[0] - 6 * mm,
                   font="STSong-Light", size=8, color=NAVY, leading=10, max_lines=2)
        role_tasks = [item for item in tasks if str(item.get("角色", "")) == str(role)]
        for task_no, task in enumerate(role_tasks):
            try:
                start=stage_names.index(str(task.get("开始阶段","")))
                end=stage_names.index(str(task.get("结束阶段","")))
            except ValueError:
                start=end=0
            if end<start: start,end=end,start
            bar_x=x_positions[start+1]+1.5*mm
            bar_w=sum(col_widths[start+1:end+2])-3*mm
            bar_y=y-row_height+2.2*mm
            bar_h=row_height-4.4*mm
            bar_colors=[colors.HexColor("#4F7DE8"),colors.HexColor("#43A29B"),colors.HexColor("#D48B31"),colors.HexColor("#765DCE")]
            page.setFillColor(bar_colors[row_index%len(bar_colors)])
            page.setStrokeColor(colors.HexColor("#9EC5F5"))
            page.roundRect(bar_x,bar_y,bar_w,bar_h,1.6*mm,fill=1,stroke=1)
            draw_lines(str(task.get("任务","")),bar_x+2.5*mm,bar_y+bar_h-4.2*mm,bar_w-5*mm,
                       font="STSong-Light",size=6.6,color=WHITE,leading=7.5,max_lines=2)
        y -= row_height

    page.setStrokeColor(LINE)
    page.line(margin, 13 * mm, width - margin, 13 * mm)
    page.setFont("STSong-Light", 7.3)
    page.setFillColor(MUTED)
    page.drawString(margin, 8 * mm, footnote or "策略仅基于当前市场、竞品与用户摘要生成，请结合真实经营数据复核。")
    page.drawRightString(width - margin, 8 * mm, "小羊分析助手 V0.5")
    page.showPage()
    page.save()
    return stream.getvalue()
