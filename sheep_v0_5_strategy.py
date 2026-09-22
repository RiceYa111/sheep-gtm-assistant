import re
import json
import io
import zipfile
import html
import importlib
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
from session_runtime import SessionFile, persist_upload, source_version, remaining_session_calls

st.set_page_config(page_title="小羊分析助手", page_icon="🐑", layout="wide", initial_sidebar_state="collapsed")
st.html("<style>" + Path(__file__).with_name("mobile.css").read_text(encoding="utf-8") + "</style>")
st.caption("🐑 公开体验版 · 销量与用户样本为演示数据，不代表真实调研结论。上传内容仅在当前会话中使用；点击 AI 分析会发送至 DeepSeek，请仅上传模拟或已脱敏资料。")

# The wrapper is neutral on desktop; mobile.css gives the chart its own scroll area.
_chart_index = 0

def render_responsive_chart(fig, **kwargs):
    global _chart_index
    compact = bool(fig.data) and all(trace.type == "pie" for trace in fig.data)
    kind = "compact" if compact else "wide"
    chart_key = f"mobile_chart_{kind}_{_chart_index}"
    _chart_index += 1
    with st.container(key=chart_key):
        st.plotly_chart(fig, **kwargs)

REGION_OPTIONS = ["全国","北京市","天津市","河北省","山西省","内蒙古自治区","辽宁省","吉林省","黑龙江省","上海市","江苏省","浙江省","安徽省","福建省","江西省","山东省","河南省","湖北省","湖南省","广东省","广西壮族自治区","海南省","重庆市","四川省","贵州省","云南省","西藏自治区","陕西省","甘肃省","青海省","宁夏回族自治区","新疆维吾尔自治区","台湾省"]
PRICE_SEGMENTS = ["5万以下","5-10万","10-20万","20-30万","30-40万","40-50万","50-60万","60-70万","70-80万","80-100万","100万以上"]
PRICE_BOUNDS = {"5万以下":(0,5),"5-10万":(5,10),"10-20万":(10,20),"20-30万":(20,30),"30-40万":(30,40),"40-50万":(40,50),"50-60万":(50,60),"60-70万":(60,70),"70-80万":(70,80),"80-100万":(80,100),"100万以上":(100,9999)}
ENERGY_OPTIONS = ["传统燃料","常规混合动力","纯电动","非增程式插混","增程式插混"]
ENERGY_GROUP_OPTIONS = ["ICE","BEV","PHEV"]
BODY_OPTIONS = ["轿车","SUV","MPV"]
APP_VERSION = "V0.5"
SAVED_SCENES_FILE = SessionFile("saved_analysis_scenes_v04.json")

TODAY=date.today()
REPORTING_MONTHS=[
    {"月份序号":index+1,"年份":year,"自然月":month,"月份":f"{year}年{month:02d}月"}
    for index,(year,month) in enumerate(
        [(TODAY.year-1,month) for month in range(1,13)]
        +[(TODAY.year,month) for month in range(1,TODAY.month)]
    )
]
PERIOD_LABELS=[item["月份"] for item in REPORTING_MONTHS]
LAST_PERIOD_INDEX=REPORTING_MONTHS[-1]["月份序号"]
FIRST_PERIOD_INDEXES=[item["月份序号"] for item in REPORTING_MONTHS[:3]]
PREVIOUS_PERIOD_INDEXES=[item["月份序号"] for item in REPORTING_MONTHS[-6:-3]]
RECENT_PERIOD_INDEXES=[item["月份序号"] for item in REPORTING_MONTHS[-3:]]
PERIOD_RANGE_TEXT=f"{PERIOD_LABELS[0]} 至 {PERIOD_LABELS[-1]}"

def merged_price_range(prices):
    valid=[PRICE_BOUNDS[price] for price in (prices or []) if price in PRICE_BOUNDS]
    if not valid: return "全部价格段"
    low=min(bound[0] for bound in valid)
    high=max(bound[1] for bound in valid)
    low_text=f"{low:g}"
    return f"{low_text}万以上" if high>=9999 else f"{low_text}-{high:g}万"

def target_price_range(target,prices):
    """Return the selected price span actually covered by the target object."""
    rows=target.get("matched_rows",pd.DataFrame())
    covered=[]
    if not rows.empty and "覆盖价格段" in rows.columns:
        covered=unique_list([segment for segments in rows["覆盖价格段"] for segment in segments])
    selected=[price for price in (prices or []) if price in covered]
    return merged_price_range(selected or covered or prices)

st.markdown("""
<style>
header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer, section[data-testid="stSidebar"], div[data-testid="collapsedControl"]{display:none!important;visibility:hidden!important}
.stApp{background:radial-gradient(circle at top left,rgba(41,91,180,.24),transparent 34%),radial-gradient(circle at top right,rgba(49,65,160,.20),transparent 32%),linear-gradient(135deg,#050B14 0%,#07111F 52%,#091A30 100%);color:#F5FAFF}
.block-container{max-width:100%!important;padding:1rem 1.2rem 2rem 1.2rem}
label,p,span,div{color:#F5FAFF}
input,textarea{color:#fff!important;background:rgba(16,36,61,.96)!important;border-radius:16px!important}
input::placeholder{color:#AFC3DC!important}
div[data-baseweb="select"]>div{background:rgba(16,36,61,.96)!important;color:#fff!important;border-color:rgba(255,255,255,.15)!important;border-radius:14px!important}
button[kind="secondary"]{background:rgba(38,96,170,.28)!important;color:#fff!important;border:1px solid rgba(120,190,255,.35)!important;border-radius:15px!important;font-weight:800!important}
.home-title{text-align:center;font-size:56px;font-weight:950;color:#fff;margin-top:16vh;margin-bottom:14px}
.home-subtitle{text-align:center;font-size:18px;color:#C7D8EF;margin-bottom:38px}
.home-module-card{display:block;text-decoration:none;background:rgba(16,36,61,.82);border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:22px;min-height:150px;box-shadow:0 12px 34px rgba(0,0,0,.28);transition:.18s ease}.home-module-card:hover{transform:translateY(-3px);border-color:rgba(98,172,245,.65);background:rgba(22,48,79,.94)}
.home-module-title{display:block;font-size:25px;font-weight:900;color:#fff;margin-bottom:12px}.home-module-desc{display:block;font-size:13px;color:#BCD1EA;line-height:1.65}
.side-card,.side-target,.hero-card,.kpi-card,.chart-card,.ai-card{border:1px solid rgba(120,190,255,.18);box-shadow:0 14px 36px rgba(0,0,0,.25);background:linear-gradient(135deg,rgba(22,48,78,.96),rgba(16,35,60,.92))}
.side-card{padding:18px 13px;border-radius:22px;margin-bottom:14px}.side-title{font-size:16px;font-weight:950;color:#fff;white-space:nowrap}.side-desc,.side-footer{font-size:11px;color:#9DB2CD;line-height:1.6}
.side-section{font-size:12px;color:#7F96B3;margin:8px 0}.side-target{margin-top:14px;padding:15px 13px;border-radius:18px}.side-target-name{font-size:19px;font-weight:950;color:#fff;margin-bottom:7px}.side-target-meta{font-size:11px;color:#BFD0E6;line-height:1.65}
.active-nav{display:flex;gap:9px;align-items:center;padding:13px;border-radius:16px;background:linear-gradient(135deg,rgba(70,126,255,.42),rgba(37,78,143,.26));border:1px solid rgba(120,190,255,.30);margin-bottom:8px}
.main-title-row{display:flex;align-items:center;gap:14px;margin-bottom:6px}.page-icon{width:42px;height:42px;border-radius:15px;background:rgba(81,130,255,.20);border:1px solid rgba(120,190,255,.26);display:flex;align-items:center;justify-content:center;font-size:24px}.main-title{font-size:42px;font-weight:950;color:#fff}.sub-title{font-size:15px;color:#C7D8EF;margin-bottom:24px}
.hero-card{min-height:116px;padding:24px 28px;border-radius:24px;display:flex;align-items:center}.hero-title{font-size:32px;font-weight:950;color:#fff;margin-bottom:7px}.hero-label{font-size:13px;color:#B8CCE6;font-weight:800;margin-bottom:7px}.hero-meta{font-size:13px;color:#BFD0E6;line-height:1.75}.hero-icon{width:68px;height:68px;border-radius:24px;background:radial-gradient(circle,rgba(94,147,255,.95),rgba(42,80,170,.45));display:flex;align-items:center;justify-content:center;font-size:34px}.multi-hint{color:#FF5C5C!important;font-size:13px;font-weight:900;margin-left:8px}
.kpi-card{min-height:122px;padding:20px;border-radius:22px}.kpi-row{display:flex;justify-content:space-between}.kpi-label{font-size:12px;color:#BFD0E6;font-weight:800;margin-bottom:9px}.kpi-value{font-size:25px;line-height:1.15;font-weight:950;color:#fff;margin-bottom:10px;white-space:nowrap}.kpi-delta{display:inline-block;padding:4px 9px;border-radius:999px;background:rgba(42,218,136,.13);color:#9AF4C7;font-size:12px;font-weight:800}.kpi-icon{font-size:22px}
.chart-card{padding:22px 24px;border-radius:24px;margin-top:18px}.chart-title{font-size:22px;font-weight:950;color:#fff;margin-bottom:10px}.ai-card{border-radius:22px;padding:22px 24px;line-height:1.85;margin-top:18px;margin-bottom:18px}.tag{display:inline-block;padding:5px 10px;border-radius:999px;background:rgba(85,158,255,.16);color:#B8DBFF;border:1px solid rgba(85,158,255,.28);font-size:12px;margin-right:6px;margin-bottom:6px;font-weight:650}.green-tag{color:#9AF4C7}.orange-tag{color:#FFD590}.red-tag{color:#FFBABA}.small-note{font-size:13px;color:#B6C8DF;line-height:1.6}
div[data-testid="stForm"]{background:linear-gradient(145deg,rgba(15,38,66,.98),rgba(8,24,44,.98))!important;border:1px solid rgba(120,190,255,.30)!important;border-radius:18px!important;padding:16px 18px!important;box-shadow:0 18px 50px rgba(0,0,0,.35)!important;margin-top:14px!important;margin-bottom:16px!important;overflow:visible!important}
div[data-testid="stForm"] *,div[data-testid="stForm"] label,div[data-testid="stForm"] p,div[data-testid="stForm"] span{color:#F4F8FF!important}
div[data-testid="stForm"] input{color:#F4F8FF!important;background:#102A48!important}
div[data-testid="stForm"] div[data-baseweb="select"]>div{background:#102A48!important;color:#F4F8FF!important;border:1px solid rgba(122,181,239,.38)!important;border-radius:12px!important;min-height:38px!important}
div[data-testid="stForm"] div[data-baseweb="tag"]{background:#234D86!important;border:1px solid rgba(143,193,255,.38)!important;border-radius:8px!important}
div[data-testid="stForm"] div[data-baseweb="tag"] span{color:#F4F8FF!important;font-weight:700!important}
div[data-testid="stForm"] button{background:#2563EB!important;color:#fff!important;border-radius:14px!important}
div[data-testid="stForm"] button *{color:#fff!important}
div[data-baseweb="popover"]{z-index:1000000!important}div[data-baseweb="popover"]>div{z-index:1000001!important}
div[data-baseweb="menu"],ul[role="listbox"]{background:#0C2038!important;border:1px solid rgba(126,181,238,.38)!important;border-radius:12px!important;z-index:1000002!important;max-height:300px!important;overflow-y:auto!important;box-shadow:0 18px 44px rgba(0,0,0,.48)!important}
li[role="option"],li[role="option"] *{color:#EAF3FF!important;background:#0C2038!important}li[role="option"]:hover,li[role="option"][aria-selected="true"]{background:#244C7D!important}li[role="option"]:hover *{background:transparent!important;color:#FFFFFF!important}
.series-card-wrap{display:flex;flex-wrap:wrap;gap:14px;margin-top:6px}
.series-card{flex:1 1 220px;min-width:210px;min-height:138px;background:linear-gradient(135deg,rgba(22,48,78,.96),rgba(16,35,60,.92));border:1px solid rgba(120,190,255,.18);box-shadow:0 12px 30px rgba(0,0,0,.22);border-radius:18px;padding:14px 16px}
.series-card-title{font-size:18px;font-weight:900;color:#fff;margin-bottom:2px}
.series-card-price{font-size:13px;color:#9AF4C7;font-weight:800;margin-bottom:8px}
.series-card-meta{font-size:12.5px;color:#BFD0E6;line-height:1.7}
.series-card-meta b{color:#E8F1FF}
.data-status{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:rgba(16,36,61,.72);border:1px solid rgba(120,190,255,.18);border-radius:16px;padding:12px 16px;margin:10px 0 4px}
.status-pill{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:850}
.status-real{background:rgba(42,218,136,.13);color:#9AF4C7;border:1px solid rgba(42,218,136,.25)}
.status-sim{background:rgba(255,181,71,.13);color:#FFD590;border:1px solid rgba(255,181,71,.25)}
.status-pending{background:rgba(160,174,192,.12);color:#C7D8EF;border:1px solid rgba(160,174,192,.22)}
.filter-group-label{font-size:13px;font-weight:900;color:#B8DBFF;margin:4px 0 8px}
.filter-selected-row{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:8px 0 14px;padding:10px 12px;border-top:1px solid rgba(120,190,255,.14);border-bottom:1px solid rgba(120,190,255,.14)}
.filter-selected-row b{color:#B8DBFF!important;margin-right:3px}.filter-selected-count{color:#93AACA!important;font-size:12px;margin-left:auto}
.metric-formula{font-size:12px;color:#AFC3DC;line-height:1.65;margin:8px 2px 2px}
.section-title-line{display:flex;align-items:center;justify-content:flex-start;gap:7px;margin:22px 2px 10px}.section-title-text{font-size:24px;font-weight:950;color:#fff}.mini-help{position:relative;display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:5px;background:rgba(82,98,119,.18);color:#71839A!important;font-size:11px;font-weight:900;cursor:help;flex:0 0 auto;box-shadow:inset 0 0 0 1px rgba(136,155,179,.25)}.mini-help:hover{color:#B8C8DA!important;background:rgba(82,98,119,.34)}.mini-help:after{content:attr(data-tooltip);position:absolute;left:50%;top:calc(100% + 9px);transform:translateX(-50%);width:max-content;max-width:340px;min-width:210px;padding:10px 12px;border-radius:10px;background:#132943;color:#EAF3FF!important;border:1px solid rgba(122,177,233,.34);box-shadow:0 12px 30px rgba(0,0,0,.40);font-size:12px;font-weight:650;line-height:1.55;white-space:normal;opacity:0;visibility:hidden;pointer-events:none;z-index:10000;transition:.12s ease}.mini-help:before{content:"";position:absolute;left:50%;top:calc(100% + 4px);transform:translateX(-50%);border:5px solid transparent;border-bottom-color:#132943;opacity:0;visibility:hidden;z-index:10001}.mini-help:hover:after,.mini-help:hover:before{opacity:1;visibility:visible}.field-help-row{display:flex;align-items:center;gap:7px;margin:2px 0 8px}.field-help-row b{font-size:13px;color:#EAF3FF}.strategy-help-overlay{position:relative;z-index:20;height:0;display:flex;justify-content:flex-end;padding-right:13px;top:12px}
.objective-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:8px 0 18px}.objective-kpi{min-height:105px;padding:18px 19px;border-radius:18px;background:linear-gradient(145deg,rgba(26,55,91,.97),rgba(16,36,62,.95));border:1px solid rgba(120,190,255,.20);box-shadow:0 12px 28px rgba(0,0,0,.18)}.objective-kpi-label{font-size:12px;color:#AFC3DC;font-weight:800}.objective-kpi-value{font-size:25px;color:#fff;font-weight:950;margin:9px 0}.objective-kpi-delta{font-size:11px;color:#9AF4C7;font-weight:850}
.series-scope-shell{background:linear-gradient(145deg,rgba(18,43,72,.96),rgba(9,26,47,.95));border:1px solid rgba(120,190,255,.22);border-radius:20px;padding:18px;margin:12px 0}.series-scope-head{font-size:20px;font-weight:950;color:#fff;margin-bottom:12px}.series-click-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.series-click-card{display:block;text-decoration:none!important;background:linear-gradient(145deg,rgba(26,55,91,.94),rgba(18,39,67,.94));border:1px solid rgba(120,190,255,.20);border-radius:14px;padding:13px 14px;min-height:112px;transition:.16s ease}.series-click-card:hover{transform:translateY(-2px);border-color:#74B6FF}.series-click-card b{display:block;font-size:16px;color:#fff;margin-bottom:6px}.series-click-card span{display:block;font-size:11px;color:#BFD0E6;line-height:1.55}.series-click-card em{font-style:normal;color:#86E6B8;font-weight:850}.series-chip-link{text-decoration:none!important}.series-chip-link .series-mini-chip:hover{border-color:#74B6FF;background:rgba(77,124,186,.38)}
.build-badge{display:inline-block;padding:4px 9px;border-radius:999px;background:rgba(160,174,192,.13);border:1px solid rgba(160,174,192,.24);color:#C7D8EF;font-size:11px;font-weight:800;margin-left:8px}
.competitor-card{min-height:205px;background:linear-gradient(145deg,rgba(22,48,78,.98),rgba(12,28,50,.96));border:1px solid rgba(120,190,255,.20);border-radius:20px;padding:16px 17px 14px;margin:8px 0;box-shadow:0 12px 28px rgba(0,0,0,.22)}
.competitor-card.core{border-color:rgba(80,220,160,.38);box-shadow:0 12px 30px rgba(30,160,115,.10)}
.competitor-card.secondary{border-color:rgba(85,158,255,.34)}
.competitor-card.cross{border-color:rgba(255,181,71,.34)}
.competitor-tier{display:inline-block;padding:4px 9px;border-radius:999px;background:rgba(85,158,255,.14);color:#B8DBFF;font-size:11px;font-weight:850;margin-bottom:12px}
.competitor-score{float:right;color:#9AF4C7;font-size:12px;font-weight:900}
.competitor-name{font-size:21px;font-weight:950;color:#fff;margin-bottom:3px}.competitor-brand{font-size:12px;color:#91A8C5;margin-bottom:10px}
.competitor-price{font-size:15px;font-weight:850;color:#FFD590;margin-bottom:8px}.competitor-meta{font-size:12px;color:#C6D6E9;line-height:1.7}
.competitor-rationale{margin:10px 0;padding:12px 13px;border-radius:10px;background:rgba(87,151,229,.12);border-left:3px solid #76ADEF;color:#E8F2FD;font-size:14px;font-weight:750;line-height:1.72}.competitor-rationale b{color:#9CCBFF;font-size:15px}.competitor-card.core .competitor-rationale{background:rgba(44,190,130,.13);border-left-color:#59D99B;color:#EFFFF6}.competitor-card.core .competitor-rationale b{color:#83F1B8;font-size:16px}.evidence-highlight{color:#FF7777!important;font-weight:950}.rationale-rule{display:block;margin-top:7px;color:#AFC4DC;font-size:11px;font-weight:650}.competitor-reason{margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,.08);font-size:12px;color:#B8CBE1;line-height:1.62}
.evidence-conclusion{display:block;margin:7px 0 6px;color:#FFF1B8;font-size:15px;font-weight:900;line-height:1.6}
.competitor-section-title{font-size:20px;font-weight:950;color:#fff;margin:22px 0 4px}.competitor-section-note{font-size:12px;color:#91A8C5;margin-bottom:10px}
.competitor-brand-header{display:flex;justify-content:space-between;align-items:center;background:rgba(70,126,255,.12);border:1px solid rgba(120,190,255,.18);border-radius:14px;padding:11px 15px;margin:14px 0 4px}
.competitor-brand-name{font-size:16px;font-weight:900;color:#DCEAFF}.competitor-brand-count{font-size:11px;color:#91A8C5}
.brand-series-strip{background:rgba(15,34,59,.82);border:1px solid rgba(120,190,255,.18);border-radius:16px;padding:12px 15px;margin:10px 0 4px;color:#EAF3FF}
.brand-series-count{font-size:11px;color:#91A8C5;margin-left:10px}.series-mini-row{display:flex;flex-wrap:nowrap;gap:7px;overflow:hidden;margin-top:9px;align-items:center}
.series-mini-chip{display:inline-flex;flex:0 0 auto;padding:5px 9px;border-radius:999px;background:rgba(77,124,186,.20);border:1px solid rgba(132,180,235,.20);font-size:11px;color:#DDEBFA}
.series-mini-more{color:#91A8C5;font-weight:900}.cr-table{width:100%;border-collapse:collapse;margin-top:8px}.cr-table th,.cr-table td{padding:14px 15px;border-bottom:1px solid rgba(255,255,255,.09);text-align:center;vertical-align:middle}.cr-table th{color:#9BC7F5;font-size:14px}.cr-table td{color:#F0F5FC;font-size:14px;line-height:1.65}.cr-table td b{color:#FFD166;font-size:16px}.cr-conclusion{margin-top:12px;padding:13px 16px;text-align:center;border-radius:12px;background:rgba(73,105,201,.16);border-left:3px solid #72A8FF;color:#EAF3FF;font-size:14px;line-height:1.7}.cr-conclusion b{color:#FFD166}
.competitor-summary{clear:both;height:auto;overflow:visible;background:linear-gradient(145deg,rgba(22,52,86,.99),rgba(10,27,49,.98));border:1px solid rgba(116,176,235,.34);border-radius:22px;padding:24px 26px 28px;margin:18px 0 22px;box-shadow:0 16px 36px rgba(0,0,0,.25)}.competitor-summary h4{margin:0 0 16px;color:#fff;font-size:24px}.summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.summary-card{background:rgba(7,20,37,.58);border:1px solid rgba(132,185,239,.22);border-radius:14px;padding:15px 16px;color:#D6E3F1;line-height:1.75;font-size:15px;min-height:86px}.summary-card.core-summary{background:rgba(38,156,112,.16);border-color:rgba(75,224,160,.38)}.summary-card.secondary-summary{background:rgba(54,116,210,.17);border-color:rgba(102,169,255,.40)}.summary-card.potential-summary{background:rgba(222,153,55,.16);border-color:rgba(255,191,91,.40)}.summary-card.wide{grid-column:1/-1;min-height:auto}.summary-label{display:block;color:#9CCBFF;font-weight:900;margin-bottom:5px}.core-summary .summary-label{color:#8DF0BF}.secondary-summary .summary-label{color:#9CCBFF}.potential-summary .summary-label{color:#FFD18A}.summary-key{color:#FFF2BD;font-weight:900}@media(max-width:900px){.summary-grid{grid-template-columns:1fr}.summary-card.wide{grid-column:auto}}
div[data-testid="stVerticalBlockBorderWrapper"]{background:rgba(15,34,59,.82);border-color:rgba(120,190,255,.18)!important;border-radius:16px!important}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-baseweb="select"]>div{background:#0D2038!important;color:#F4F8FF!important;border:1px solid rgba(120,190,255,.34)!important;border-radius:12px!important}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-baseweb="select"] input{color:#DCEBFA!important;-webkit-text-fill-color:#DCEBFA!important}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-baseweb="select"] input::placeholder{color:#B8CBE0!important;-webkit-text-fill-color:#B8CBE0!important;opacity:1!important}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-baseweb="select"]>div>div{color:#B8CBE0!important}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-baseweb="tag"]{background:#234D86!important;border:1px solid rgba(143,193,255,.38)!important;border-radius:8px!important}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-baseweb="tag"] span{color:#F4F8FF!important;font-weight:700!important}
.insight-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:10px}
.insight-panel{background:linear-gradient(145deg,rgba(22,48,78,.96),rgba(13,30,52,.94));border:1px solid rgba(120,190,255,.18);border-radius:18px;padding:18px 19px;min-height:150px;margin-top:16px}
.insight-kicker{font-size:11px;font-weight:900;color:#7FB7FF;letter-spacing:.08em;margin-bottom:8px}.insight-title{font-size:18px;font-weight:950;color:#fff;margin-bottom:8px}
.insight-text{font-size:12.5px;color:#C6D6E9;line-height:1.75}.insight-number{color:#9AF4C7;font-weight:900}.insight-risk{color:#FFD590;font-weight:900}
.module-chart-head{padding:4px 4px 10px}.module-chart-title{font-size:20px;font-weight:950;color:#FFFFFF;margin-bottom:5px}.module-chart-note{font-size:12px;color:#AFC4DD;line-height:1.6}.opportunity-callout{margin:10px 2px 4px;padding:16px 18px;border-radius:14px;background:linear-gradient(135deg,rgba(40,92,154,.22),rgba(22,48,78,.58));border-left:4px solid #63A9F5}.opportunity-title{color:#9CCBFF;font-size:18px;font-weight:950;margin-bottom:7px}.opportunity-text{color:#ECF5FF;font-size:16px;font-weight:750;line-height:1.8}.opportunity-panel .insight-title{color:#9CCBFF}.opportunity-panel .insight-text{font-size:15px;font-weight:700;color:#E7F2FF;line-height:1.8}
.series-card-spacer{height:14px}
.insight-summary{margin-top:14px;background:linear-gradient(135deg,rgba(63,104,255,.18),rgba(22,48,78,.92));border:1px solid rgba(100,160,255,.28);border-radius:20px;padding:20px 22px;color:#DDEAFF;line-height:1.8}
.overview-shell{margin:10px 0 20px;padding:22px 24px;border:1px solid rgba(104,160,222,.28);border-radius:22px;background:linear-gradient(145deg,rgba(17,40,69,.97),rgba(8,23,43,.98));box-shadow:0 16px 36px rgba(0,0,0,.20)}
.overview-title{font-size:22px;font-weight:900;color:#F4F8FF;margin-bottom:5px}.overview-subtitle{font-size:12px;color:#8FAAC8;margin-bottom:16px}
.overview-section-label{font-size:13px;font-weight:850;color:#9CCBFF;letter-spacing:.04em;margin:4px 0 9px}.overview-core-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}
.overview-core-card{min-height:90px;padding:13px 14px;border-radius:14px;background:linear-gradient(150deg,rgba(38,71,112,.86),rgba(18,43,74,.92));border:1px solid rgba(112,177,240,.28)}
.overview-core-name{font-size:15px;font-weight:900;color:#FFFFFF;margin-bottom:7px}.overview-core-note{font-size:12px;line-height:1.55;color:#C8D8EA}
.overview-concentration{padding:15px 17px;border-radius:15px;background:rgba(10,27,49,.72);border:1px solid rgba(112,163,219,.23);color:#D9E6F4;font-size:14px;line-height:1.7}.overview-concentration b{color:#FFD27A;font-size:15px}
.overview-verdict{margin-top:12px;padding:16px 18px;border-radius:15px;background:linear-gradient(135deg,rgba(73,105,201,.19),rgba(33,81,130,.18));border-left:4px solid #72A8FF;color:#EAF3FF;font-size:15px;line-height:1.75}.overview-verdict-label{display:block;color:#A8CDFF;font-size:12px;font-weight:900;margin-bottom:3px}
.tier-core-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 14px;align-items:stretch}.tier-core-grid .competitor-card{height:100%;box-sizing:border-box;margin:0}@media(max-width:800px){.tier-core-grid{grid-template-columns:1fr}}
[class*="_prev"] button,[class*="_next"] button{width:44px!important;height:44px!important;min-height:44px!important;border-radius:50%!important;padding:0!important;margin:auto!important}
@media(max-width:1000px){.objective-kpi-grid,.series-click-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.competition-legend{margin:-92px 16px 20px;padding-top:8px;position:relative;z-index:3}.competition-legend-row{display:grid;gap:7px 10px;margin-top:7px}.competition-legend-single{grid-template-columns:repeat(16,minmax(0,1fr))}.competition-legend-multi{grid-template-columns:repeat(8,minmax(0,1fr))}.competition-legend-item{display:flex;align-items:center;gap:5px;min-width:0;color:#DCE8F6;font-size:11px}.competition-legend-swatch{width:10px;height:10px;flex:0 0 auto;border-radius:2px}.competition-legend-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.competition-legend-rank{color:#7995B5;font-size:9px}.competition-insight{margin:10px 2px 4px;padding:17px 18px;border-radius:15px;background:linear-gradient(135deg,rgba(39,82,137,.28),rgba(11,29,51,.90));border:1px solid rgba(111,173,235,.25)}.competition-insight-title{color:#A8D0FF;font-size:16px;font-weight:950;margin-bottom:11px}.competition-insight-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.competition-insight-card{padding:12px 13px;border-radius:11px;background:rgba(7,22,41,.64);border:1px solid rgba(112,169,228,.18);color:#D7E5F4;font-size:12px;line-height:1.72}.competition-insight-label{display:block;color:#8DBDF2;font-size:11px;font-weight:900;margin-bottom:4px}.competition-insight-card b{color:#FFF0B2}.competition-insight-delta{color:#FF8A8A!important}.region-compare-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:10px 0 18px}.region-compare-card{padding:18px;border-radius:18px;background:linear-gradient(145deg,rgba(22,48,78,.97),rgba(11,29,52,.96));border:1px solid rgba(120,190,255,.23);box-shadow:0 12px 28px rgba(0,0,0,.18)}.region-compare-name{font-size:18px;font-weight:950;color:#FFFFFF;margin-bottom:13px}.region-metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.region-metric{padding:11px 12px;border-radius:11px;background:rgba(7,22,41,.62);border:1px solid rgba(112,169,228,.16)}.region-metric-label{font-size:11px;color:#91AAC7;margin-bottom:5px}.region-metric-value{font-size:17px;color:#F4F8FF;font-weight:950}.region-metric-accent{color:#9CCBFF}.region-compare-note{margin-top:10px;padding-top:9px;border-top:1px solid rgba(120,190,255,.16);color:#9EB6D1;font-size:11px;line-height:1.6}.region-compare-note b{color:#FFD590}@media(max-width:900px){.competition-legend-single,.competition-legend-multi{grid-template-columns:repeat(4,minmax(0,1fr))}.competition-insight-grid,.region-compare-grid{grid-template-columns:1fr}.competition-legend{margin-top:-82px}}
html{scroll-behavior:smooth}.section-nav{position:sticky;top:8px;z-index:20;margin:12px 0 18px;padding:14px 16px 15px;border-radius:16px;background:linear-gradient(135deg,rgba(15,38,68,.96),rgba(8,24,45,.97));border:1px solid rgba(104,160,222,.30);box-shadow:0 12px 28px rgba(0,0,0,.22);backdrop-filter:blur(10px)}.section-nav-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:11px}.section-nav-heading{display:flex;align-items:center;gap:9px;color:#F4F8FF;font-size:16px;font-weight:950}.section-nav-icon{display:inline-flex;width:27px;height:27px;align-items:center;justify-content:center;border-radius:8px;background:linear-gradient(145deg,#547FE5,#2D55A6);color:#fff}.section-nav-note{color:#9AB2CE;font-size:11px}.section-nav-links{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.section-nav a{display:flex;align-items:center;gap:8px;min-height:46px;color:#DCEBFA!important;text-decoration:none!important;padding:8px 10px;border-radius:10px;background:rgba(58,103,160,.20);border:1px solid rgba(110,166,224,.16);transition:transform .24s ease,background .24s ease,border-color .24s ease,box-shadow .24s ease}.section-nav a:hover{transform:translateY(-2px);background:rgba(68,124,194,.34);border-color:rgba(120,190,255,.48);box-shadow:0 8px 18px rgba(0,0,0,.18)}.section-nav-index{display:inline-flex;flex:0 0 auto;width:22px;height:22px;align-items:center;justify-content:center;border-radius:7px;background:rgba(91,143,218,.28);color:#BFD9FA;font-size:10px;font-weight:900}.section-nav-copy{min-width:0}.section-nav-label{display:block;color:#F2F7FF;font-size:12px;font-weight:900}.section-nav-desc{display:block;margin-top:2px;color:#94ABC5;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.section-anchor{scroll-margin-top:118px}.section-anchor:target{animation:section-arrive 1.1s ease}@keyframes section-arrive{0%{filter:drop-shadow(0 0 0 rgba(105,169,255,0))}35%{filter:drop-shadow(0 0 12px rgba(105,169,255,.72))}100%{filter:drop-shadow(0 0 0 rgba(105,169,255,0))}}@media(max-width:900px){.section-nav-links{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:620px){.section-nav-links{grid-template-columns:1fr 1fr}.section-nav-note{display:none}}
.quick-scope-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin:18px 0 10px}.quick-scope-title{display:flex;align-items:center;gap:8px;color:#F4F8FF;font-size:20px;font-weight:950}.quick-scope-title-icon{display:inline-flex;width:28px;height:28px;align-items:center;justify-content:center;border-radius:9px;background:linear-gradient(145deg,#4A75D8,#274D9B);box-shadow:0 6px 16px rgba(61,107,210,.25)}.quick-scope-sub{color:#9EB6D1;font-size:12px;margin-top:5px}.quick-scope-recommend{padding:5px 9px;border-radius:999px;background:rgba(67,211,151,.13);border:1px solid rgba(67,211,151,.30);color:#8EF0C0;font-size:11px;font-weight:900}.quick-card-kicker{display:inline-flex;padding:4px 8px;border-radius:999px;background:rgba(77,124,186,.18);color:#A9CEFA;font-size:11px;font-weight:900}.quick-card-title{color:#FFFFFF;font-size:17px;font-weight:950;margin:10px 0 6px}.quick-card-desc{color:#B7C9DE;font-size:12px;line-height:1.65;min-height:40px}.quick-card-tags{display:flex;flex-wrap:wrap;gap:5px;margin:11px 0 8px}.quick-card-tag{padding:3px 7px;border-radius:999px;background:rgba(126,167,218,.11);border:1px solid rgba(126,167,218,.17);color:#C9DBEF;font-size:10px}.quick-scope-preview{display:flex;justify-content:space-between;gap:14px;align-items:center;padding:13px 15px;margin:12px 0 3px;border-radius:13px;background:linear-gradient(135deg,rgba(36,77,129,.35),rgba(13,33,58,.86));border:1px solid rgba(105,166,228,.25)}.quick-preview-label{color:#91A9C5;font-size:11px;font-weight:800;margin-bottom:3px}.quick-preview-value{color:#F2F7FF;font-size:14px;font-weight:900}.quick-preview-note{color:#8EA8C4;font-size:11px;text-align:right}@media(max-width:760px){.quick-scope-preview{align-items:flex-start;flex-direction:column}.quick-preview-note{text-align:left}}
div[data-testid="stExpander"] details{background:linear-gradient(145deg,rgba(15,38,66,.98),rgba(8,24,44,.98))!important;border:1px solid rgba(112,169,228,.28)!important;border-radius:15px!important;overflow:hidden!important}div[data-testid="stExpander"] summary{background:#132D4D!important;color:#EAF3FF!important;border-radius:13px!important;padding:10px 14px!important}div[data-testid="stExpander"] summary:hover{background:#193A61!important;color:#FFFFFF!important}div[data-testid="stExpander"] summary p,div[data-testid="stExpander"] summary span,div[data-testid="stExpander"] summary svg{color:#EAF3FF!important;fill:#EAF3FF!important}div[data-testid="stExpander"] div[data-baseweb="select"]>div{background:#102A48!important;color:#F4F8FF!important;border-color:rgba(122,181,239,.38)!important}div[data-testid="stExpander"] div[data-baseweb="select"] svg{fill:#BFD8F4!important}div[data-testid="stExpander"] div[data-baseweb="select"]>div>div:last-child{background:#173655!important;color:#DCEBFA!important}
@media(max-width:1050px){.overview-core-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.overview-core-grid{grid-template-columns:1fr}}
@media(max-width:900px){.insight-grid{grid-template-columns:1fr}}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
.user-upload-shell{margin:14px 0 18px;padding:20px 22px;border-radius:20px;background:linear-gradient(145deg,rgba(20,46,78,.97),rgba(10,27,49,.97));border:1px solid rgba(120,190,255,.25);box-shadow:0 14px 34px rgba(0,0,0,.22)}
.user-upload-title{font-size:20px;font-weight:950;color:#FFFFFF;margin-bottom:5px}.user-upload-note{font-size:12px;color:#9FB5CF;margin-bottom:12px}.user-source-row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 3px}.user-source-pill{padding:5px 9px;border-radius:999px;background:rgba(83,142,213,.16);border:1px solid rgba(120,190,255,.20);color:#CFE3FA;font-size:11px;font-weight:800}
[data-testid="stFileUploaderDropzone"]{background:linear-gradient(145deg,#142A48,#10233E)!important;border:1px dashed rgba(116,185,255,.55)!important;border-radius:16px!important;color:#EAF3FF!important}
[data-testid="stFileUploaderDropzone"] small,[data-testid="stFileUploaderDropzone"] span,[data-testid="stFileUploaderDropzone"] div{color:#AFC3DC!important}
[data-testid="stFileUploaderDropzone"] button{background:#244A7B!important;color:#F6FAFF!important;border:1px solid rgba(130,195,255,.42)!important;border-radius:12px!important}
[data-testid="stFileUploaderDropzone"] button:hover{background:#2F5F9B!important;border-color:#7EC5FF!important}
.user-section-title{font-size:24px;font-weight:950;color:#FFFFFF;margin:26px 0 5px}.user-section-note{font-size:12px;color:#91A8C5;margin-bottom:12px}.user-profile-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px}.user-profile-card{min-height:102px;padding:15px;border-radius:15px;background:linear-gradient(145deg,rgba(25,55,91,.95),rgba(12,31,54,.95));border:1px solid rgba(118,181,238,.20)}.user-profile-label{font-size:11px;color:#8FAAC8;margin-bottom:8px}.user-profile-value{font-size:16px;color:#F5F9FF;font-weight:900;line-height:1.55}.user-profile-wide{grid-column:span 2}
.user-persona-hero{min-height:260px;padding:30px 34px;border-radius:20px;background:linear-gradient(135deg,rgba(29,63,104,.98),rgba(9,27,49,.98));border:1px solid rgba(118,181,238,.30);display:grid;grid-template-columns:150px minmax(0,1fr);align-items:center;gap:30px}.user-persona-hero-icon{width:128px;height:128px;border-radius:32px;display:flex;align-items:center;justify-content:center;font-size:62px;background:radial-gradient(circle at 35% 25%,#507ee7,#19345d 64%,#0c213c);box-shadow:0 18px 46px rgba(34,91,176,.30);border:1px solid rgba(142,200,255,.25)}.user-persona-copy{width:100%;padding:4px 0;display:flex;flex-direction:column;justify-content:center}.user-persona-kicker{color:#80BFFF;font-size:14px;font-weight:900;letter-spacing:.10em;margin-bottom:9px}.user-persona-name{font-size:35px;line-height:1.2;color:#FFFFFF;font-weight:950;margin-bottom:22px}.user-persona-tags{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr));gap:11px;width:100%}.user-persona-tag{min-height:68px;padding:12px 14px;border-radius:13px;background:rgba(70,124,190,.20);border:1px solid rgba(120,190,255,.27);color:#F1F7FF;font-size:14px;line-height:1.5}.user-persona-tag b{display:block;color:#91C6F5;font-size:11px;margin-bottom:4px}.user-survey-meta{margin-top:17px;font-size:13px;color:#9DB7D4}.user-profile-evidence{margin:18px 0 6px;font-size:17px;font-weight:950;color:#F7FAFF}.user-profile-chart-note{font-size:11px;color:#8FA7C2;margin-top:-3px;margin-bottom:8px}
.user-persona-visual{position:relative;min-height:300px;border-radius:20px;overflow:hidden;background:radial-gradient(circle at 50% 25%,rgba(98,154,235,.32),transparent 32%),linear-gradient(145deg,#173B67,#07192D 72%);border:1px solid rgba(118,181,238,.28);display:flex;flex-direction:column;align-items:center;justify-content:center}.user-persona-visual:before,.user-persona-visual:after{content:"";position:absolute;border:1px solid rgba(112,184,255,.18);border-radius:50%;width:280px;height:280px}.user-persona-visual:after{width:190px;height:190px;border-color:rgba(112,184,255,.12)}.user-persona-icon{position:relative;z-index:2;font-size:76px;filter:drop-shadow(0 12px 24px rgba(0,0,0,.35));margin-bottom:14px}.user-persona-label{position:relative;z-index:2;padding:8px 14px;border-radius:999px;background:rgba(82,137,211,.24);border:1px solid rgba(134,199,255,.32);font-size:15px;font-weight:950;color:#FFFFFF}.user-profile-summary{margin:15px 0 17px;padding:17px 19px;border-radius:15px;background:linear-gradient(135deg,rgba(28,65,108,.72),rgba(11,31,55,.92));border-left:4px solid #68A7F0;color:#E5F1FD;font-size:14px;line-height:1.8}.user-profile-summary b{color:#FFFFFF}.user-survey-meta{color:#8FA8C5;font-size:11px;margin-top:8px}
.user-need-layout{display:grid;grid-template-columns:1.15fr .85fr;gap:13px}.user-need-panel{padding:17px 18px;border-radius:17px;background:rgba(13,33,58,.86);border:1px solid rgba(116,176,235,.20)}.user-need-row{display:grid;grid-template-columns:28px minmax(88px,1fr) 2fr 42px;gap:9px;align-items:center;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.08)}.user-need-row:last-child{border-bottom:0}.user-need-rank{color:#7EADDF;font-size:12px;font-weight:900}.user-need-name{color:#F2F7FF;font-size:13px;font-weight:850}.user-need-bar{height:8px;border-radius:999px;background:rgba(132,153,180,.16);overflow:hidden}.user-need-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#4779D7,#7EB6F4)}.user-need-score{color:#FFD58E;font-size:12px;font-weight:900;text-align:right}.user-reason-list{display:grid;gap:8px}.user-reason-item{padding:11px 12px;border-radius:11px;background:rgba(75,126,187,.11);border-left:3px solid #6CA8E6;color:#D8E7F6;font-size:12.5px;line-height:1.65}.user-reason-item b{color:#FFFFFF}.user-concern-item{border-left-color:#E6A35C;background:rgba(196,125,47,.10)}
.user-competitor-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:11px}.user-competitor-card{padding:16px;border-radius:16px;background:linear-gradient(145deg,rgba(24,52,86,.96),rgba(11,29,51,.96));border:1px solid rgba(116,176,235,.22)}.user-competitor-name{font-size:18px;color:#FFFFFF;font-weight:950;margin-bottom:11px}.user-competitor-block{padding:9px 0;border-top:1px solid rgba(255,255,255,.08);color:#C9D9EA;font-size:12.5px;line-height:1.65}.user-competitor-block b{display:block;color:#9CCBFF;margin-bottom:3px}
.user-script-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.user-script-card{min-height:112px;padding:18px 19px;border-radius:16px;background:rgba(12,31,55,.88);border:1px solid rgba(111,173,235,.21)}.user-script-stage{color:#8FC0F2;font-size:11px;font-weight:900;margin-bottom:7px}.user-script-title{color:#FFFFFF;font-size:16px;font-weight:950;margin-bottom:8px}.user-script-text{color:#D9E8F7;font-size:13px;line-height:1.78}.user-quote{margin-top:9px;padding:9px 11px;border-left:3px solid #FFD166;background:rgba(255,209,102,.08);color:#FFF0C4;font-size:12px;line-height:1.6}
@media(max-width:1050px){.user-profile-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.user-competitor-grid{grid-template-columns:1fr 1fr}.user-need-layout{grid-template-columns:1fr}.user-persona-tags{grid-template-columns:repeat(3,minmax(120px,1fr))}}@media(max-width:700px){.user-profile-grid,.user-competitor-grid,.user-script-grid{grid-template-columns:1fr}.user-profile-wide{grid-column:auto}.user-need-row{grid-template-columns:24px minmax(80px,1fr) 1.4fr 36px}.user-persona-hero{grid-template-columns:1fr;padding:24px}.user-persona-hero-icon{width:88px;height:88px;font-size:42px}.user-persona-tags{grid-template-columns:1fr 1fr}.user-persona-name{font-size:29px}}
</style>
""",unsafe_allow_html=True)


st.markdown("""
<style>
/* 深色主题：修改目标弹框 */
div[data-testid="stPopoverBody"] {
    background: linear-gradient(135deg, rgba(14, 30, 52, 0.98), rgba(18, 40, 68, 0.98)) !important;
    border: 1px solid rgba(120, 190, 255, 0.28) !important;
    border-radius: 18px !important;
    box-shadow: 0 18px 50px rgba(0,0,0,0.45) !important;
    padding: 14px !important;
}
div[data-testid="stPopoverBody"] *,
div[data-testid="stPopoverBody"] label,
div[data-testid="stPopoverBody"] p,
div[data-testid="stPopoverBody"] span {
    color: #F5FAFF !important;
}
div[data-testid="stPopoverBody"] input,
div[data-testid="stPopoverBody"] textarea {
    color: #FFFFFF !important;
    background: rgba(9, 18, 34, 0.95) !important;
}
div[data-testid="stPopoverBody"] div[data-baseweb="input"],
div[data-testid="stPopoverBody"] div[data-baseweb="select"] > div {
    background: rgba(9, 18, 34, 0.95) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(120,190,255,.30) !important;
    border-radius: 12px !important;
}
div[data-testid="stDialog"]{display:flex!important;align-items:center!important;justify-content:center!important;padding:24px!important}
div[data-testid="stDialog"] [role="dialog"],[role="dialog"]{margin:auto!important;background:linear-gradient(145deg,#102A48,#081A30)!important;color:#F3F8FF!important;border:1px solid rgba(126,185,243,.38)!important;border-radius:20px!important;box-shadow:0 26px 70px rgba(0,0,0,.58)!important}
[role="dialog"] h1,[role="dialog"] h2,[role="dialog"] h3,[role="dialog"] p,[role="dialog"] label,[role="dialog"] span{color:#F3F8FF!important}
[role="dialog"] input{background:#0C223D!important;color:#FFFFFF!important;-webkit-text-fill-color:#FFFFFF!important;border-color:rgba(126,185,243,.38)!important}
[role="dialog"] input::placeholder{color:#AFC4DC!important;-webkit-text-fill-color:#AFC4DC!important;opacity:1!important}
[role="dialog"] button[aria-label="Close"]{color:#DCEBFA!important;background:rgba(89,139,201,.16)!important;border-radius:9px!important}
div[data-testid="stPopoverBody"] button {
    background: rgba(38, 96, 170, 0.42) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(120, 190, 255, 0.38) !important;
    border-radius: 14px !important;
}
div[data-testid="stPopoverBody"] button * {
    color: #FFFFFF !important;
}

/* 深色主题：高级筛选面板 */
.filter-panel-card {
    background: linear-gradient(135deg, rgba(14, 30, 52, 0.98), rgba(18, 40, 68, 0.98));
    border: 1px solid rgba(120, 190, 255, 0.22);
    box-shadow: 0 16px 42px rgba(0,0,0,0.28);
    border-radius: 22px;
    padding: 18px 22px;
    margin-top: 16px;
    margin-bottom: 12px;
}
.filter-panel-title {
    font-size: 22px;
    font-weight: 950;
    color: #FFFFFF;
    margin-bottom: 6px;
}
.filter-panel-desc {
    font-size: 12px;
    color: #AFC3DC;
    line-height: 1.6;
}
.filter-panel-gap {
    height: 8px;
}
div[data-testid="stForm"] {
    background: linear-gradient(135deg, rgba(14, 30, 52, 0.98), rgba(18, 40, 68, 0.98)) !important;
    border: 1px solid rgba(120, 190, 255, 0.22) !important;
    box-shadow: 0 16px 42px rgba(0,0,0,0.28) !important;
    border-radius: 22px !important;
    padding: 18px 22px 10px !important;
}
div[data-testid="stForm"] label,
div[data-testid="stForm"] p {
    color: #EAF3FF !important;
}
div[data-testid="stForm"] div[data-baseweb="select"] > div,
div[data-testid="stForm"] div[data-baseweb="select"] > div > div {
    background: #0D2038 !important;
    color: #F4F8FF !important;
}
div[data-baseweb="popover"] ul,
div[data-baseweb="popover"] [role="listbox"],
div[data-baseweb="popover"] [role="option"] {
    background: #0A192B !important;
    color: #F4F8FF !important;
}
div[data-baseweb="popover"] [role="option"]:hover,
div[data-baseweb="popover"] [aria-selected="true"] {
    background: #17395F !important;
    color: #FFFFFF !important;
}
div[data-baseweb="popover"] li[role="option"],
div[data-baseweb="popover"] li[role="option"] > div {
    background: #0A192B !important;
    color: #F4F8FF !important;
}
div[data-baseweb="popover"] li[role="option"]:hover,
div[data-baseweb="popover"] li[role="option"]:hover > div {
    background: #17395F !important;
}
div[data-baseweb="popover"],
div[data-baseweb="popover"] [role="listbox"],
div[data-baseweb="popover"] ul {
    background:#081728!important;
    color:#F4F8FF!important;
}
div[data-baseweb="popover"] [role="option"],
div[data-baseweb="popover"] [role="option"] *,
div[data-baseweb="popover"] ul li,
div[data-baseweb="popover"] ul li * {
    background:#0A192B!important;
    color:#F4F8FF!important;
}
div[data-baseweb="popover"] [role="option"]:hover,
div[data-baseweb="popover"] [role="option"]:hover * {
    background:#17395F!important;
    color:#FFFFFF!important;
}
li[role="option"][aria-label="Select all"],
li[role="option"][aria-label="Select All"],
li[role="option"][id$="val-0"],
div[data-baseweb="popover"] [role="listbox"]>[role="option"]:first-child,
div[data-baseweb="popover"] [role="listbox"] li[role="option"]:first-child,
div[data-baseweb="popover"] [role="listbox"]>li:first-child,
div[data-baseweb="popover"] ul>li:first-child {display:none!important}

/* 深色多选框：去掉输入区前方突兀白块 */
div[data-baseweb="select"] input,
div[data-baseweb="select"] input:focus,
div[data-baseweb="select"] input:active {
    background: transparent !important;
    color: #FFFFFF !important;
    box-shadow: none !important;
}
div[data-baseweb="select"] [data-baseweb="tag"] {
    background: rgba(70, 126, 255, 0.26) !important;
    border: 1px solid rgba(120, 190, 255, 0.28) !important;
    border-radius: 8px !important;
}
div[data-baseweb="select"] [data-baseweb="tag"] span {
    color: #FFFFFF !important;
    font-weight: 760 !important;
}
div[data-baseweb="select"] [data-baseweb="tag"] svg {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
}

/* 下拉菜单置顶，选项字体黑色 */
div[data-baseweb="popover"] {
    z-index: 2147483000 !important;
}
@media(max-width:1180px){
  .block-container{padding-left:.75rem!important;padding-right:.75rem!important}
  .hero-card{padding:20px!important}.hero-title{font-size:27px!important}
  .section-nav-links{grid-template-columns:repeat(3,minmax(0,1fr))!important}
}
@media(max-width:760px){
  .section-nav-links{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}
  div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{min-width:300px!important;flex:1 1 100%!important}
}
div[data-baseweb="popover"] > div {
    z-index: 2147483001 !important;
}
div[data-baseweb="menu"],
ul[role="listbox"] {
    background: #FFFFFF !important;
    border: 1px solid #D0D5DD !important;
    border-radius: 12px !important;
    z-index: 2147483002 !important;
    max-height: 320px !important;
    overflow-y: auto !important;
    box-shadow: 0 18px 50px rgba(0,0,0,0.28) !important;
}
li[role="option"],
li[role="option"] *,
div[role="option"],
div[role="option"] * {
    color: #101828 !important;
    background: #FFFFFF !important;
}
li[role="option"]:hover,
div[role="option"]:hover {
    background: #EAF2FF !important;
}

/* 全局运行提示：仅在 Streamlit 正在重新计算页面时显示。 */
.stApp[data-test-script-state="running"]::before{
    content:"";
    position:fixed;
    inset:0;
    z-index:2147483600;
    background:rgba(3,10,20,.38);
    backdrop-filter:blur(1.5px);
    pointer-events:none;
}
.stApp[data-test-script-state="running"]::after{
    content:"正在更新分析结果…";
    position:fixed;
    left:50%;
    top:50%;
    transform:translate(-50%,-50%);
    z-index:2147483601;
    min-width:250px;
    padding:18px 28px 18px 58px;
    border-radius:18px;
    border:1px solid rgba(124,190,255,.42);
    background:linear-gradient(145deg,rgba(18,45,76,.98),rgba(8,25,46,.98));
    box-shadow:0 24px 70px rgba(0,0,0,.48);
    color:#F5FAFF;
    font-size:15px;
    font-weight:850;
    letter-spacing:.02em;
    pointer-events:none;
}

/* 正文统一采用沟通策略建议的字号，标题、标签、KPI 与图表刻度保持原层级。 */
:root{--app-body-font-size:13px}
.home-module-desc,.side-desc,.side-footer,.side-target-meta,.hero-meta,
.small-note,.metric-formula,.series-card-meta,.series-click-card span,
.competitor-meta,.competitor-reason,.competitor-section-note,
.summary-card,.cr-conclusion,.ai-card,.ai-card .insight-text,.ai-card li,
.user-profile-summary,.user-reason-item,.user-competitor-block,
.user-script-text,.user-quote,.user-section-note,.user-source-note,
.competition-insight-card,.module-chart-note,.overview-verdict,
.strategy-opportunity-evidence,.strategy-opportunity-action,
.strategy-core-copy,.strategy-stage-copy{
    font-size:var(--app-body-font-size)!important;
    line-height:1.75!important;
}
/* 结论层级略高于普通正文，便于快速扫读。 */
.cr-conclusion,.overview-verdict,.overview-core-note,
.opportunity-text,.summary-card.wide,.ai-card .insight-text{
    font-size:15px!important;
    line-height:1.78!important;
    font-weight:650!important;
}
</style>
""", unsafe_allow_html=True)

def read_csv_safely(path):
    for enc in ["utf-8-sig","utf-8","gbk","gb18030"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            pass
    raise ValueError(f"无法读取文件：{path}")

def find_data_file():
    # 同时在“当前运行目录”和“脚本自身所在目录”下查找，避免因终端启动路径不同导致读不到文件
    search_dirs = [Path.cwd(), Path(__file__).resolve().parent]
    filenames = ["data/car_info.csv","car_info.csv","data/car_info(1).csv","car_info(1).csv",
                 "data/car_info.xlsx","car_info.xlsx","data/car_info(1).xlsx","car_info(1).xlsx"]
    for base in search_dirs:
        for name in filenames:
            p = base / name
            if p.exists():
                return p
    return None

def clean_price_value(value):
    if pd.isna(value): return np.nan
    nums = re.findall(r"\d+\.?\d*", str(value).replace("万元","").replace("万","").replace(",",""))
    return float(nums[0]) if nums else np.nan

def normalize_energy(value):
    text=str(value).strip()
    mapping={"汽油":"传统燃料","柴油":"传统燃料","燃油":"传统燃料","传统燃料":"传统燃料","油电混合":"常规混合动力","油混":"常规混合动力","轻混":"常规混合动力","48V轻混":"常规混合动力","常规混合动力":"常规混合动力","纯电":"纯电动","纯电动":"纯电动","EV":"纯电动","插混":"非增程式插混","插电混动":"非增程式插混","插电式混合动力":"非增程式插混","非增程式插混":"非增程式插混","非增程插混":"非增程式插混","PHEV":"非增程式插混","增程":"增程式插混","增程式":"增程式插混","增程式插混":"增程式插混","REEV":"增程式插混"}
    return mapping.get(text, text if text in ENERGY_OPTIONS else "传统燃料")

def energy_group(value):
    if value in ["传统燃料","常规混合动力"]: return "ICE"
    if value=="纯电动": return "BEV"
    if value in ["非增程式插混","增程式插混"]: return "PHEV"
    return "ICE"

def normalize_body(value):
    text=str(value).strip().upper()
    if "SUV" in text: return "SUV"
    if "MPV" in text: return "MPV"
    return "轿车"

def get_segments_for_range(price_min, price_max):
    if pd.isna(price_min) and pd.isna(price_max): return []
    if pd.isna(price_min): price_min=price_max
    if pd.isna(price_max): price_max=price_min
    return [seg for seg,(low,high) in PRICE_BOUNDS.items() if price_max>=low and price_min<high]

def get_main_price_segment(price_min, price_max):
    segs=get_segments_for_range(price_min,price_max)
    if not segs: return "待判断"
    mid = price_max if pd.isna(price_min) else price_min if pd.isna(price_max) else (price_min+price_max)/2
    for seg,(low,high) in PRICE_BOUNDS.items():
        if low<=mid<high: return seg
    return segs[0]

def price_text(price_min, price_max):
    if pd.isna(price_min) and pd.isna(price_max): return "待补充"
    if pd.isna(price_min): price_min=price_max
    if pd.isna(price_max): price_max=price_min
    return f"{float(price_min):.2f}万" if float(price_min)==float(price_max) else f"{float(price_min):.2f}-{float(price_max):.2f}万"

@st.cache_data
def load_car_info():
    file_path=find_data_file()
    if file_path is None:
        st.session_state["_data_source_info"]="⚠️ 未找到 car_info 数据文件，当前使用内置示例数据（仅奥迪A6L 3条）"
        df=pd.DataFrame([["一汽奥迪","奥迪A6L","",32.89,49.98,"","汽油","轿车","中大型","5座"],["一汽奥迪","奥迪A6L","",38.79,46.27,"","油电混合","轿车","中大型","5座"],["一汽奥迪","奥迪A6L","",55.89,55.89,"","轻混","轿车","中大型","5座"]],columns=["品牌","车系","分析对象名称","价格下限","价格上限","价格段","能源形式","车身形式","级别","座位数"])
    else:
        st.session_state["_data_source_info"]=f"✅ 已加载数据文件：{file_path.resolve()}"
        df=read_csv_safely(file_path) if file_path.suffix.lower()==".csv" else pd.read_excel(file_path)
    rename={}
    for c in df.columns:
        n=str(c).strip().replace(" ","")
        if n in ["分析字段名称","分析对象","分析对象名称"]: rename[c]="分析对象名称"
        elif n in ["品牌","车系","价格段","能源形式","车身形式","级别","座位数"]: rename[c]=n
        elif n in ["价格下限","指导价下限","厂商指导价下限"]: rename[c]="价格下限"
        elif n in ["价格上限","指导价上限","厂商指导价上限"]: rename[c]="价格上限"
    df=df.rename(columns=rename)
    required=["品牌","车系","分析对象名称","价格下限","价格上限","价格段","能源形式","车身形式","级别","座位数"]
    for c in required:
        if c not in df.columns: df[c]=""
    df=df[required].copy()
    for c in ["品牌","车系","分析对象名称","级别","座位数"]:
        df[c]=df[c].astype(str).str.strip()
    df["品牌"]=(df["品牌"].str.replace("(","（",regex=False).str.replace(")","）",regex=False)
                 .replace({"理想汽车":"理想"}))
    df=df.drop_duplicates(subset=required,keep="first").reset_index(drop=True)
    df["原始能源形式"]=df["能源形式"].astype(str).str.strip()
    df["能源形式"]=df["原始能源形式"].apply(normalize_energy)
    df["能源大类"]=df["能源形式"].apply(energy_group)
    df["价格下限"]=df["价格下限"].apply(clean_price_value)
    df["价格上限"]=df["价格上限"].apply(clean_price_value)
    df["价格上限"]=df["价格上限"].fillna(df["价格下限"])
    df["价格下限"]=df["价格下限"].fillna(df["价格上限"])
    df["车身形式"]=df["车身形式"].apply(normalize_body)
    df["级别"]=df["级别"].replace({"nan":"待补充","":"待补充"})
    df["座位数"]=df["座位数"].replace({"nan":"-","":"-"})
    duplicated=df["车系"].duplicated(keep=False)
    df["分析对象名称"]=df.apply(lambda r: r["分析对象名称"] if r["分析对象名称"] and r["分析对象名称"]!="nan" else (f"{r['车系']}（{r['原始能源形式']}）" if duplicated.loc[r.name] else r["车系"]), axis=1)
    df["覆盖价格段"]=df.apply(lambda r:get_segments_for_range(r["价格下限"],r["价格上限"]), axis=1)
    df["覆盖价格段文本"]=df["覆盖价格段"].apply(lambda x:"；".join(x) if x else "待判断")
    df["主价格段"]=df.apply(lambda r:get_main_price_segment(r["价格下限"],r["价格上限"]), axis=1)
    df["价格段"]=df.apply(lambda r:r["价格段"] if str(r["价格段"]).strip() not in ["","nan","NaN"] else r["主价格段"], axis=1)
    df["价格展示"]=df.apply(lambda r:price_text(r["价格下限"],r["价格上限"]), axis=1)
    df["核心标签"]=df["能源大类"]+"｜"+df["车身形式"]+"｜"+df["级别"]
    return df

car_df=load_car_info()

def find_project_data_file(names):
    search_dirs=[Path.cwd(),Path(__file__).resolve().parent]
    for base in search_dirs:
        for name in names:
            path=base/name
            if path.exists(): return path
    return None

@st.cache_data
def load_user_materials():
    path=find_project_data_file([
        "user_materials.csv","data/user_materials.csv","user_materials.xlsx","data/user_materials.xlsx",
        "user_materials_public_demo_v01.csv","data/user_materials_public_demo_v01.csv"])
    if path is None: return pd.DataFrame()
    frame=read_csv_safely(path) if path.suffix.lower()==".csv" else pd.read_excel(path)
    frame.columns=[str(col).strip() for col in frame.columns]
    for col in ["品牌","车系","用户原文","年龄段","职业","家庭结构","是否已购","购车阶段","决策周期","主要决策人","决策影响人","来源类型"]:
        if col not in frame.columns: frame[col]=""
        frame[col]=frame[col].fillna("").astype(str).str.strip()
    frame=frame[frame["车系"].ne("") & frame["用户原文"].ne("")].copy()
    return frame

@st.cache_data
def load_user_profile_survey():
    path=find_project_data_file([
        "user_profile_survey.csv","data/user_profile_survey.csv","user_profile_survey.xlsx","data/user_profile_survey.xlsx",
        "user_profile_survey_demo_v01.csv","data/user_profile_survey_demo_v01.csv"])
    if path is None: return pd.DataFrame(),None
    try:
        frame=read_csv_safely(path) if path.suffix.lower()==".csv" else pd.read_excel(path)
    except Exception:
        return pd.DataFrame(),path
    frame.columns=[str(col).strip() for col in frame.columns]
    required=["品牌","车系","分析对象名称","年龄段","职业","购车预算","家庭结构","首购/增购/换购","决策周期","购车动因"]
    for col in required:
        if col not in frame.columns: frame[col]=""
        frame[col]=frame[col].fillna("").astype(str).str.strip()
    return frame,path

user_material_df=pd.DataFrame()
user_profile_survey_df=pd.DataFrame()
user_profile_survey_path=None

def stable_seed(text): return sum((idx+1)*ord(ch) for idx,ch in enumerate(str(text)))%100000

def regional_volume_factor(region):
    if region=="全国": return 1.0
    large={"广东省","江苏省","浙江省","山东省","河南省","四川省"}
    medium={"北京市","上海市","河北省","安徽省","湖北省","湖南省","福建省","辽宁省","重庆市","广西壮族自治区"}
    small={"天津市","山西省","内蒙古自治区","吉林省","黑龙江省","江西省","陕西省","云南省","贵州省","新疆维吾尔自治区"}
    if region in large: return .072
    if region in medium: return .047
    if region in small: return .030
    return .016

def regional_market_preference(region,energy,body,brand=""):
    if region=="全国": return 1.0
    factor=.94+(stable_seed(f"market-pref-{region}-{energy}-{body}-{brand}")%13)/100
    high_bev={"北京市","上海市","江苏省","浙江省","福建省","广东省","广西壮族自治区","海南省"}
    phev_growth={"重庆市","四川省","湖北省","河南省","湖南省","陕西省","安徽省"}
    fuel_suv={"内蒙古自治区","辽宁省","吉林省","黑龙江省","西藏自治区","甘肃省","青海省","宁夏回族自治区","新疆维吾尔自治区"}
    if energy=="BEV": factor*=1.22 if region in high_bev else .86 if region in fuel_suv else 1.0
    elif energy=="PHEV": factor*=1.18 if region in phev_growth else 1.04
    elif energy=="ICE": factor*=1.18 if region in fuel_suv else .86 if region in high_bev else 1.0
    if body=="SUV" and region in fuel_suv|phev_growth: factor*=1.12
    if body=="轿车" and region in high_bev: factor*=1.07
    if body=="MPV" and region in {"福建省","广东省","浙江省","海南省"}: factor*=1.12
    local_brand_rules={
        "广东省":["比亚迪","广汽","小鹏"],"浙江省":["吉利","领克","极氪","零跑"],
        "上海市":["上汽","荣威","智己","大众"],"湖北省":["东风","岚图"],
        "重庆市":["长安","深蓝","阿维塔","赛力斯"],"吉林省":["一汽","红旗"],
        "辽宁省":["华晨","宝马"],"安徽省":["奇瑞","蔚来","江淮"],
        "北京市":["北京","北汽","奔驰","理想"],"四川省":["凯翼","一汽丰田"],
    }
    if any(token in str(brand) for token in local_brand_rules.get(region,[])): factor*=1.24
    return factor

def simulated_product_profile(brand,series,region,month_index,series_rank_factor=1.0):
    """Create deterministic but recognisable product and regional sales patterns."""
    product_seed=stable_seed(f"{brand}-{series}")
    brand_factor=.72+(stable_seed(brand)%57)/100
    # Keep simulated volumes broadly aligned with recognisable market tiers.
    tier_rules={"特斯拉":1.35,"比亚迪":1.28,"理想":1.12,"吉利":1.12,"大众":1.08,
                "一汽丰田":1.02,"广汽丰田":1.02,"奥迪":.92,"奔驰":.90,"宝马":.92,
                "蔚来":.82,"岚图":.78,"雷克萨斯":.66,"捷豹路虎":.48,"路虎":.48}
    for token,multiplier in tier_rules.items():
        if token in str(brand):
            brand_factor*=multiplier
            break
    series_factor=series_rank_factor*(.94+(product_seed%13)/100)
    profile=product_seed%4
    start=3+(product_seed%7)
    if profile==0:
        if month_index<start: trend=.94
        elif month_index<=start+2: trend=.94+(month_index-start+1)*.11
        else: trend=1.27*(1+.006*(month_index-start-2))
    elif profile==1:
        trend=1.10*(1+.012*month_index) if month_index<10 else 1.22*(1-.008*(month_index-10))
    elif profile==2:
        trend=.96*(1-.010*min(month_index,7)) if month_index<=7 else .90*(1+.022*(month_index-7))
    else:
        trend=.94*(1+.011*month_index)
    # Month-to-month changes make cumulative leaders stable without freezing monthly ranks.
    phase=(product_seed%628)/100
    amplitude=.14+(product_seed%12)/100
    fluctuation=1+amplitude*np.sin(month_index*1.17+phase)+.07*np.cos(month_index*.63+phase/2)
    # A small share of products launch during the observed period: pre-launch months are absent,
    # launch month spikes, then sales settle into a normal ramp.
    new_model_tokens=("钛7","YU7","岚图泰山")
    is_new_model=any(token in str(series) for token in new_model_tokens)
    if is_new_model:
        launch_month=4+(product_seed%max(5,len(REPORTING_MONTHS)-5))
        if month_index<launch_month: launch_factor=0
        elif month_index==launch_month: launch_factor=1.85
        elif month_index==launch_month+1: launch_factor=1.38
        else: launch_factor=1.0+.012*(month_index-launch_month)
    else:
        launch_factor=1.0
    # Occasional product hand-off / supply interruption creates a temporary unlisted month.
    handoff_month=6+(product_seed%max(4,len(REPORTING_MONTHS)-6))
    handoff_factor=.55 if product_seed%9==0 and month_index==handoff_month else 1.0
    if region=="全国":
        region_affinity=1.0
        regional_pulse=1.0
    else:
        # Every region has a recognisable product preference and its own monthly
        # rank movement.  This changes share structure, not merely market volume.
        affinity_seed=stable_seed(f"{region}-{brand}-{series}")
        region_affinity=.72+(affinity_seed%64)/100
        regional_phase=(affinity_seed%628)/100
        regional_amplitude=.08+(affinity_seed%11)/100
        regional_pulse=1+regional_amplitude*np.sin(month_index*.91+regional_phase)
        if (affinity_seed+month_index*7)%41==0:
            regional_pulse*=1.28
        elif (affinity_seed+month_index*11)%47==0:
            regional_pulse*=.72
    return brand_factor*series_factor*trend*fluctuation*launch_factor*handoff_factor*region_affinity*regional_pulse

@st.cache_data
def create_market_data(period_key, regions, periods):
    rows=[]
    pf={"5万以下":1.90,"5-10万":1.70,"10-20万":1.38,"20-30万":1.05,"30-40万":0.72,"40-50万":0.48,"50-60万":0.30,"60-70万":0.22,"70-80万":0.16,"80-100万":0.12,"100万以上":0.06}
    ef={"ICE":1.00,"BEV":0.74,"PHEV":0.58}; bf={"轿车":1.06,"SUV":1.18,"MPV":0.34}
    for region in regions:
        for period in periods:
            month=period["自然月"]
            month_index=period["月份序号"]
            month_label=period["月份"]
            season=1+.08*np.sin(month/12*2*np.pi)
            for price in PRICE_SEGMENTS:
                for energy in ENERGY_GROUP_OPTIONS:
                    for body in BODY_OPTIONS:
                        rng=np.random.default_rng(stable_seed(f"market-{region}-{month_label}-{price}-{energy}-{body}"))
                        base=42000
                        trend_step=month_index-1
                        preference=regional_market_preference(region,energy,body)
                        sales=int(base*pf.get(price,.5)*ef.get(energy,.7)*bf.get(body,.8)*regional_volume_factor(region)*preference*season*(1+trend_step*rng.uniform(-.003,.009))*rng.uniform(.90,1.10))
                        rows.append({"月份":month_label,"月份序号":month_index,"地区":region,"价格段":price,"能源大类":energy,"车身形式":body,"销量":max(sales,10 if region!="全国" else 120)})
    return pd.DataFrame(rows)

market_df=pd.DataFrame()

@st.cache_data
def create_target_data(car_data,period_key,regions,periods):
    rows=[]
    pf={"5万以下":1.90,"5-10万":1.70,"10-20万":1.38,"20-30万":1.05,"30-40万":0.72,"40-50万":0.48,"50-60万":0.30,"60-70万":0.22,"70-80万":0.16,"80-100万":0.12,"100万以上":0.06}
    ef={"ICE":.85,"BEV":.70,"PHEV":.62}; bf={"轿车":.72,"SUV":.84,"MPV":.36}
    series_rank_factors={}
    for brand,brand_rows in car_data.groupby("品牌"):
        series_names=sorted(brand_rows["车系"].dropna().astype(str).unique(),key=lambda value:stable_seed(f"{brand}-{value}"))
        raw_weights=np.array([max(.22,1.0-rank*.16) for rank in range(len(series_names))],dtype=float)
        normalized_weights=raw_weights/max(raw_weights.sum(),1)
        for rank,series_name in enumerate(series_names):
            version_count=max(int((brand_rows["车系"].astype(str)==series_name).sum()),1)
            # Brand sales are distributed across its series instead of being inflated by series count.
            # The main series carries the largest share; version rows share that series allocation.
            series_rank_factors[(brand,series_name)]=float(normalized_weights[rank])/version_count
    for _,row in car_data.iterrows():
        segs=[s for s in row["覆盖价格段"] if s in PRICE_SEGMENTS] or [row["主价格段"]]
        for seg in segs:
            for region in regions:
                for period in periods:
                    month=period["自然月"]
                    month_index=period["月份序号"]
                    month_label=period["月份"]
                    rng=np.random.default_rng(stable_seed(f"target-{row['分析对象名称']}-{seg}-{region}-{month_label}"))
                    season=1+.08*np.sin(month/12*2*np.pi)
                    base=39000
                    product_profile=simulated_product_profile(row["品牌"],row["车系"],region,month_index,series_rank_factors.get((row["品牌"],row["车系"]),1.0))
                    preference=regional_market_preference(region,row["能源大类"],row["车身形式"],row["品牌"])
                    sales=int(base*pf.get(seg,.5)*ef.get(row["能源大类"],.6)*bf.get(row["车身形式"],.6)*regional_volume_factor(region)*preference*season*product_profile*rng.uniform(.91,1.09)/max(len(segs),1))
                    rows.append({"月份":month_label,"月份序号":month_index,"地区":region,"品牌":row["品牌"],"车系":row["车系"],"分析对象名称":row["分析对象名称"],"价格段":seg,"能源形式":row["能源形式"],"能源大类":row["能源大类"],"车身形式":row["车身形式"],"级别":row["级别"],"座位数":row["座位数"],"销量":max(sales,0)})
    return pd.DataFrame(rows)

@st.cache_data
def calibrate_target_sales_to_market(target_data,market_data,max_covered_share=.72):
    """Keep all simulated products inside the matching market capacity."""
    keys=["月份序号","地区","价格段","能源大类","车身形式"]
    capacity=market_data[keys+["销量"]].rename(columns={"销量":"市场容量"})
    calibrated=target_data.merge(capacity,on=keys,how="left")
    totals=calibrated.groupby(keys,as_index=False)["销量"].sum().rename(columns={"销量":"产品合计"})
    calibrated=calibrated.merge(totals,on=keys,how="left")
    ceiling=calibrated["市场容量"].fillna(0)*max_covered_share
    scale=np.minimum(1.0,ceiling/np.maximum(calibrated["产品合计"],1))
    calibrated["销量"]=(calibrated["销量"]*scale).round().clip(lower=0).astype(int)
    return calibrated.drop(columns=["市场容量","产品合计"])

# Homepage only needs the small vehicle catalogue. Sales data is loaded below
# after routing and target validation, never during initial homepage rendering.
target_df_all=pd.DataFrame()

@st.cache_data(show_spinner=False, max_entries=4)
def load_sales_bundle(catalogue_json, period_key, summary_only=False):
    catalogue=pd.read_json(io.StringIO(catalogue_json), orient="split")
    regions=("全国",) if summary_only else tuple(REGION_OPTIONS)
    periods=(REPORTING_MONTHS[-1],) if summary_only else tuple(REPORTING_MONTHS)
    market=create_market_data(period_key, regions, periods)
    products=create_target_data(catalogue, period_key, regions, periods)
    products=calibrate_target_sales_to_market(products,market,.72)
    latest=(products[(products["地区"]=="全国")&(products["月份序号"]==LAST_PERIOD_INDEX)]
            .groupby("分析对象名称",as_index=False)["销量"].sum().rename(columns={"销量":"近月销量"}))
    catalogue=catalogue.merge(latest,on="分析对象名称",how="left")
    catalogue["近月销量"]=catalogue["近月销量"].fillna(0).astype(int)
    catalogue["趋势"]="稳定"
    return market,products,catalogue

def prepare_page_data(page):
    global market_df,target_df_all,car_df,user_material_df,user_profile_survey_df,user_profile_survey_path
    global px,go,make_subplots,build_gtm_pdf,build_strategy_onepage_pdf,dsui,dstrategy,mm
    if page=="首页":
        return
    query=str(st.session_state.get("target_query", "")).strip()
    if page!="市场大盘" and not has_explicit_analysis_target():
        return
    if query and query!="自定义分析目标" and not target_info(query)["found"]:
        return
    label=query or "整体市场"
    with st.spinner(f"正在分析{label} · 加载{page}所需数据……"):
        import plotly.express as px
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        from pdf_report import build_gtm_pdf, build_strategy_onepage_pdf
        from reportlab.lib.units import mm
        import deepseek_user_insight as dsui
        import deepseek_strategy as dstrategy
        # User charts need only a national latest-month snapshot for vehicle cards.
        # Market/competitor/strategy share one full cached bundle so denominators
        # and cross-brand competitor rankings retain their existing definitions.
        summary_only=page=="用户洞察"
        market_df,target_df_all,car_df=load_sales_bundle(
            car_df.to_json(orient="split",force_ascii=False),
            f"{PERIOD_RANGE_TEXT}|regional-v4-capacity",summary_only)
        if page in {"用户洞察","策略生成"}:
            user_material_df,_,material_error=dsui.load_source_table("materials")
            user_profile_survey_df,user_profile_survey_path,survey_error=dsui.load_source_table("survey")
            if material_error: st.warning(material_error)
            if survey_error: st.warning(survey_error)


def default_target_name(): return str(car_df.iloc[0]["车系"]) if len(car_df) else "奥迪A6L"
if "current_page" not in st.session_state: st.session_state.current_page="首页"
if "target_query" not in st.session_state: st.session_state.target_query=""
if "home_query" not in st.session_state: st.session_state.home_query=""

def norm_search(text): return str(text).lower().replace(" ","").replace("al6","a6l")
def unique_list(values, allowed=None):
    result=[]
    for value in values:
        items=value if isinstance(value,list) else re.split(r"[；;,/、]+",str(value))
        for item in items:
            item=str(item).strip()
            if item and item!="nan" and (allowed is None or item in allowed) and item not in result:
                result.append(item)
    if allowed: result.sort(key=lambda x: allowed.index(x) if x in allowed else 999)
    return result

def format_options(values, fallback="全部"):
    values=values or []
    if not values: return fallback
    return " / ".join(values) if len(values)<=4 else " / ".join(values[:4])+f" 等{len(values)}项"

def title_prefix(values, fallback="全部"): return format_options(values,fallback)
def region_title_text(regions):
    if not regions or set(regions)=={"全国"}: return "全国销量趋势"
    shown=[r for r in regions if r!="全国"]
    return "全国销量趋势" if not shown else f"{format_options(shown)}销量趋势"

def get_base_series_matches(query):
    q=norm_search(query or default_target_name())
    series_mask=car_df["车系"].astype(str).apply(norm_search).str.contains(q,na=False)
    series_df=car_df[series_mask].copy()
    if len(series_df)>0:
        names=series_df["车系"].dropna().astype(str).unique().tolist()
        return car_df[car_df["车系"].isin(names)].copy().reset_index(drop=True)
    brand_mask=car_df["品牌"].astype(str).apply(norm_search).str.contains(q,na=False)
    brand_df=car_df[brand_mask].copy()
    if len(brand_df)>0: return brand_df.reset_index(drop=True)
    obj_mask=car_df["分析对象名称"].astype(str).apply(norm_search).str.contains(q,na=False)
    obj_df=car_df[obj_mask].copy()
    if len(obj_df)>0:
        names=obj_df["车系"].dropna().astype(str).unique().tolist()
        return car_df[car_df["车系"].isin(names)].copy().reset_index(drop=True)
    return pd.DataFrame()

def build_series_breakdown(matched):
    rows=[]
    for name in matched["车系"].dropna().astype(str).unique().tolist():
        sub=matched[matched["车系"]==name]
        segs_i=unique_list(sub["覆盖价格段"],PRICE_SEGMENTS)
        rows.append({
            "车系":name,
            "品牌":format_options(unique_list(sub["品牌"]),"待补充"),
            "价格展示":price_text(sub["价格下限"].min(),sub["价格上限"].max()),
            "覆盖价格段":"；".join(segs_i) if segs_i else "待判断",
            "能源形式":format_options(unique_list(sub["能源形式"]),"待补充"),
            "车身形式":format_options(unique_list(sub["车身形式"]),"待补充"),
            "级别":format_options(unique_list(sub["级别"]),"待补充"),
            "座位数":format_options(unique_list(sub["座位数"]),"-"),
            "近月销量":int(sub["近月销量"].sum()) if "近月销量" in sub.columns else 0,
        })
    return rows

def target_info(query):
    raw=str(query).strip() or default_target_name()
    if raw=="自定义分析目标":
        matched=car_df.copy()
        brands=st.session_state.get("brands_market",[])
        series_filter=st.session_state.get("series_market",[])
        prices=st.session_state.get("prices_market",[])
        energies=st.session_state.get("energies_market",[])
        bodies=st.session_state.get("bodies_market",[])
        if brands: matched=matched[matched["品牌"].isin(brands)]
        if series_filter: matched=matched[matched["车系"].isin(series_filter)]
        if prices and not matched.empty:
            matched=matched[matched["覆盖价格段"].map(lambda values:bool(set(values)&set(prices)))]
        if energies: matched=matched[matched["能源形式"].isin(energies)]
        if bodies: matched=matched[matched["车身形式"].isin(bodies)]
    else:
        matched=get_base_series_matches(query)
    if len(matched)==0:
        return {"found":False,"query":raw,"品牌":raw,"车系":raw,"价格展示":"待补充","覆盖价格段":[],"覆盖价格段文本":"待补充","能源形式":"待补充","能源形式列表":[],"能源大类":"待补充","车身形式":"待补充","车身形式列表":[],"级别":"待补充","座位数":"-","matched_rows":matched,"is_multi":False,"is_brand_query":False,"series_breakdown":[]}
    segs=unique_list(matched["覆盖价格段"],PRICE_SEGMENTS)
    energies_list=unique_list(matched["能源形式"],ENERGY_OPTIONS)
    bodies_list=unique_list(matched["车身形式"],BODY_OPTIONS)
    series_names=matched["车系"].dropna().astype(str).unique().tolist()
    is_brand_query=len(series_names)>1
    target_name="自定义分析目标" if raw=="自定义分析目标" else (series_names[0] if len(series_names)==1 else raw)
    breakdown=build_series_breakdown(matched) if is_brand_query else []
    return {"found":True,"query":raw,"品牌":format_options(unique_list(matched["品牌"]),"待补充"),"车系":target_name,"价格展示":price_text(matched["价格下限"].min(),matched["价格上限"].max()),"覆盖价格段":segs,"覆盖价格段文本":"；".join(segs) if segs else "待判断","能源形式":format_options(energies_list,"待补充"),"能源形式列表":energies_list,"能源大类":format_options(unique_list(matched["能源大类"]),"待补充"),"车身形式":format_options(bodies_list,"待补充"),"车身形式列表":bodies_list,"级别":format_options(unique_list(matched["级别"]),"待补充"),"座位数":format_options(unique_list(matched["座位数"]),"-"),"matched_rows":matched,"is_multi":len(matched)>1,"is_brand_query":False if raw=="自定义分析目标" else is_brand_query,"series_breakdown":[] if raw=="自定义分析目标" else breakdown}

def set_page(page_name): st.session_state.current_page=page_name

def reset_view_state():
    for page_key in ["market","competitor","user","strategy"]:
        st.session_state[f"show_filter_{page_key}"]=False

def submit_search():
    query=st.session_state.get("home_query","").strip()
    if not query:
        st.session_state["_home_search_error"]="请输入想查找的车型或品牌。"
        return
    st.session_state.pop("_home_search_error",None)
    st.session_state.target_query=query
    st.session_state.current_page="市场大盘"
    reset_view_state()

def open_home_module(page_name):
    query=st.session_state.get("home_query","").strip()
    if not query:
        st.session_state["_home_search_error"]="请先输入车型或品牌，再进入分析模块。"
        return
    st.session_state.pop("_home_search_error",None)
    st.session_state.target_query=query
    set_page(page_name)
    reset_view_state()

def quick_search(query):
    st.session_state.home_query=query
    st.session_state.target_query=query
    st.session_state.current_page="市场大盘"
    st.session_state.pop("_home_search_error",None)
    reset_view_state()

def widget_to_actual(values, options, field_name=""):
    values=values or []
    if "全部" in values:
        return ["全国"] if field_name=="地区" else list(options)
    return [v for v in values if v in options]

def actual_to_widget(actual_values, options, field_name=""):
    actual_values=actual_values or []
    if field_name=="地区" and actual_values==["全国"]: return ["全国"]
    if actual_values and set(actual_values)==set(options): return ["全部"]
    return [v for v in actual_values if v in options]

def brand_options_from_data():
    return unique_list(car_df["品牌"])

def series_options_from_data(selected_brands=None):
    df = car_df.copy()
    selected_brands = selected_brands or []
    if selected_brands:
        df = df[df["品牌"].isin(selected_brands)]
    return unique_list(df["车系"])

def sync_pending_series_with_brand(page_key, brand_actual):
    series_options = series_options_from_data(brand_actual)
    pending_key = f"pending_series_{page_key}"
    current = st.session_state.get(pending_key, [])
    st.session_state[pending_key] = [v for v in current if v in ["全部"] + series_options]
    return series_options

def reset_filters(page_key,target):
    regions=["全国"]
    prices=target.get("覆盖价格段",[]) or PRICE_SEGMENTS
    energies=ENERGY_OPTIONS.copy() if page_key=="competitor" else (target.get("能源形式列表",[]) or ENERGY_OPTIONS.copy())
    bodies=target.get("车身形式列表",[]) or BODY_OPTIONS.copy()

    if page_key=="competitor":
        brands=[]
        series_filter=[]
    elif target.get("query")!="自定义分析目标" and target.get("found") and len(target.get("matched_rows",[]))>0:
        brands=unique_list(target["matched_rows"]["品牌"])
        series_filter=unique_list(target["matched_rows"]["车系"])
    else:
        brands=[]
        series_filter=[]

    brand_options=brand_options_from_data()
    series_options=series_options_from_data(brands)

    st.session_state[f"brands_{page_key}"]=brands
    st.session_state[f"series_{page_key}"]=series_filter
    st.session_state[f"regions_{page_key}"]=regions
    st.session_state[f"prices_{page_key}"]=prices
    st.session_state[f"energies_{page_key}"]=energies
    st.session_state[f"bodies_{page_key}"]=bodies

    st.session_state[f"pending_brands_{page_key}"]=actual_to_widget(brands,brand_options,"品牌")
    st.session_state[f"pending_series_{page_key}"]=actual_to_widget(series_filter,series_options,"车系")
    st.session_state[f"pending_regions_{page_key}"]=actual_to_widget(regions,REGION_OPTIONS,"地区")
    st.session_state[f"pending_prices_{page_key}"]=actual_to_widget(prices,PRICE_SEGMENTS,"价格段")
    st.session_state[f"pending_energies_{page_key}"]=actual_to_widget(energies,ENERGY_OPTIONS,"能源形式")
    st.session_state[f"pending_bodies_{page_key}"]=actual_to_widget(bodies,BODY_OPTIONS,"车身形式")

def ensure_filters(page_key,target):
    if st.session_state.get(f"sync_target_{page_key}")!=st.session_state.target_query:
        reset_filters(page_key,target); st.session_state[f"sync_target_{page_key}"]=st.session_state.target_query

def apply_target_change(edit_key,page_key=None):
    query=st.session_state.get(edit_key,"").strip()
    if query:
        st.session_state.target_query=query; st.session_state.home_query=query
        reset_view_state()
        if page_key:
            new_target=target_info(query); reset_filters(page_key,new_target); st.session_state[f"sync_target_{page_key}"]=query

def normalize_all_selection(key):
    values=list(st.session_state.get(key,[]))
    previous=list(st.session_state.get(f"{key}_previous",[]))
    if "全部" in values and len(values)>1:
        values=[value for value in values if value!="全部"] if "全部" in previous else ["全部"]
        st.session_state[key]=values
    st.session_state[f"{key}_previous"]=values

def multiselect_dropdown(label, options, key, max_selections=None):
    if not options:
        st.selectbox(label,["无"],disabled=True,key=f"{key}_none")
        st.session_state[key]=[]
        return []
    options_with_all=["全部"]+options
    current=[v for v in st.session_state.get(key,[]) if v in options_with_all]
    if key not in st.session_state:
        st.session_state[key]=current
    if max_selections and len(current)>max_selections:
        current=current[:max_selections]
        st.session_state[key]=current
    if f"{key}_previous" not in st.session_state:
        st.session_state[f"{key}_previous"]=current
    values=st.multiselect(label,options_with_all,key=key,placeholder=f"点击展开并选择{label}",max_selections=max_selections,on_change=normalize_all_selection,args=(key,))
    return widget_to_actual(values,options,label)

def pending_values(key,allowed):
    return [v for v in st.session_state.get(key,[]) if v!="全部" and v in allowed]

def commit_filter_selection(page_key,is_competitor=False):
    st.session_state[f"brands_{page_key}"]=widget_to_actual(
        st.session_state.get(f"pending_brands_{page_key}",[]),brand_options_from_data(),"品牌")
    st.session_state[f"series_{page_key}"]=widget_to_actual(
        st.session_state.get(f"pending_series_{page_key}",[]),unique_list(car_df["车系"]),"车系")
    selected_regions=widget_to_actual(
        st.session_state.get(f"pending_regions_{page_key}",[]),REGION_OPTIONS,"地区")
    st.session_state[f"regions_{page_key}"]=selected_regions or ["全国"]
    st.session_state[f"prices_{page_key}"]=widget_to_actual(
        st.session_state.get(f"pending_prices_{page_key}",[]),PRICE_SEGMENTS,"价格段")
    st.session_state[f"energies_{page_key}"]=widget_to_actual(
        st.session_state.get(f"pending_energies_{page_key}",[]),ENERGY_OPTIONS,"能源形式")
    st.session_state[f"bodies_{page_key}"]=widget_to_actual(
        st.session_state.get(f"pending_bodies_{page_key}",[]),BODY_OPTIONS,"车身形式")
    st.session_state[f"show_filter_{page_key}"]=False
    st.session_state[f"normalize_pending_{page_key}"]=True

def normalize_pending_from_applied(page_key,is_competitor=False):
    if not st.session_state.pop(f"normalize_pending_{page_key}",False):
        return
    st.session_state[f"pending_brands_{page_key}"]=actual_to_widget(
        st.session_state.get(f"brands_{page_key}",[]),brand_options_from_data(),"品牌")
    st.session_state[f"pending_series_{page_key}"]=actual_to_widget(
        st.session_state.get(f"series_{page_key}",[]),unique_list(car_df["车系"]),"车系")
    st.session_state[f"pending_regions_{page_key}"]=actual_to_widget(
        st.session_state.get(f"regions_{page_key}",[]),REGION_OPTIONS,"地区")
    st.session_state[f"pending_prices_{page_key}"]=actual_to_widget(
        st.session_state.get(f"prices_{page_key}",[]),PRICE_SEGMENTS,"价格段")
    st.session_state[f"pending_energies_{page_key}"]=actual_to_widget(
        st.session_state.get(f"energies_{page_key}",[]),ENERGY_OPTIONS,"能源形式")
    st.session_state[f"pending_bodies_{page_key}"]=actual_to_widget(
        st.session_state.get(f"bodies_{page_key}",[]),BODY_OPTIONS,"车身形式")

def available_car_options(brands=None,series_filter=None,prices=None,energies=None,bodies=None,exclude=None):
    df=car_df.copy()
    if exclude!="品牌" and brands: df=df[df["品牌"].isin(brands)]
    if exclude!="车系" and series_filter: df=df[df["车系"].isin(series_filter)]
    if exclude!="价格段" and prices and not df.empty:
        price_mask=df["覆盖价格段"].map(lambda segs: bool(set(segs)&set(prices))).astype(bool)
        df=df.loc[price_mask]
    if exclude!="能源形式" and energies: df=df[df["能源形式"].isin(energies)]
    if exclude!="车身形式" and bodies: df=df[df["车身形式"].isin(bodies)]
    return {
        "品牌":unique_list(df["品牌"]),
        "车系":unique_list(df["车系"]),
        "价格段":[p for p in PRICE_SEGMENTS if any(p in segs for segs in df["覆盖价格段"])],
        "能源形式":[e for e in ENERGY_OPTIONS if e in set(df["能源形式"])],
        "车身形式":[b for b in BODY_OPTIONS if b in set(df["车身形式"])],
    }

def sanitize_pending(key,options):
    current=st.session_state.get(key,[])
    st.session_state[key]=[v for v in current if v=="全部" or v in options]

def filter_target_rows_for_context(target_rows, brands=None, series_filter=None, prices=None, energies=None, bodies=None):
    if brands or series_filter:
        df=car_df.copy()
        if brands:
            df=df[df["品牌"].isin(brands)]
        if series_filter:
            df=df[df["车系"].isin(series_filter)]
    else:
        df=target_rows.copy()

    if prices and not df.empty:
        price_mask=df["覆盖价格段"].map(lambda segs: bool(set(segs)&set(prices))).astype(bool)
        df=df.loc[price_mask]
    if energies:
        df=df[df["能源形式"].isin(energies)]
    if bodies:
        df=df[df["车身形式"].isin(bodies)]

    return df

def filter_market_data(regions=None,prices=None,energy_groups=None,bodies=None):
    df=market_df.copy()
    if regions: df=df[df["地区"].isin(regions)]
    if prices: df=df[df["价格段"].isin(prices)]
    if energy_groups: df=df[df["能源大类"].isin(energy_groups)]
    if bodies: df=df[df["车身形式"].isin(bodies)]
    return df

def filter_target_data(regions=None,prices=None,energies=None,bodies=None,names=None,brands=None,series_filter=None):
    df=target_df_all.copy()
    if regions: df=df[df["地区"].isin(regions)]
    if prices: df=df[df["价格段"].isin(prices)]
    if energies: df=df[df["能源形式"].isin(energies)]
    if bodies: df=df[df["车身形式"].isin(bodies)]
    if names: df=df[df["分析对象名称"].isin(names)]
    if brands: df=df[df["品牌"].isin(brands)]
    if series_filter: df=df[df["车系"].isin(series_filter)]
    return df

def build_competitor_pool(target, brands=None, series_filter=None, prices=None, energies=None, bodies=None):
    target_rows=target.get("matched_rows",pd.DataFrame())
    target_series=set(target_rows["车系"].astype(str)) if len(target_rows) else set()
    target_prices=set(prices or target.get("覆盖价格段",[]))
    target_bodies=set(bodies or target.get("车身形式列表",[]))
    target_levels=set(target_rows["级别"].astype(str)) if len(target_rows) else set()
    target_energy_groups=set(target_rows["能源大类"].astype(str)) if len(target_rows) else set()

    source=car_df[~car_df["车系"].astype(str).isin(target_series)].copy()
    if brands: source=source[source["品牌"].isin(brands)]
    if series_filter: source=source[source["车系"].isin(series_filter)]
    if prices and not source.empty:
        price_mask=source["覆盖价格段"].map(lambda segs: bool(set(segs)&set(prices))).astype(bool)
        source=source.loc[price_mask]
    if energies: source=source[source["能源形式"].isin(energies)]
    if bodies: source=source[source["车身形式"].isin(bodies)]
    if source.empty: return pd.DataFrame()

    rows=[]
    max_sales=max(float(source.groupby(["品牌","车系"])["近月销量"].sum().max()),1.0)
    for (brand,series),sub in source.groupby(["品牌","车系"],sort=False):
        candidate_prices=set(sum(sub["覆盖价格段"].tolist(),[]))
        candidate_bodies=set(sub["车身形式"].astype(str))
        candidate_levels=set(sub["级别"].astype(str))
        candidate_energy_groups=set(sub["能源大类"].astype(str))
        price_overlap=len(candidate_prices&target_prices)/max(len(target_prices),1)
        body_match=bool(candidate_bodies&target_bodies)
        level_match=bool(candidate_levels&target_levels)
        energy_match=bool(candidate_energy_groups&target_energy_groups)
        sales=int(sub["近月销量"].sum())
        score=round(min(price_overlap,1)*35+(25 if body_match else 0)+(20 if level_match else 0)+(10 if energy_match else 0)+min(sales/max_sales,1)*10)
        rows.append({
            "匹配分":score,
            "品牌":brand,
            "车系":series,
            "价格展示":price_text(sub["价格下限"].min(),sub["价格上限"].max()),
            "覆盖价格段":"；".join([p for p in PRICE_SEGMENTS if p in candidate_prices]),
            "能源大类":format_options(unique_list(sub["能源大类"])),
            "能源形式":format_options(unique_list(sub["能源形式"])),
            "车身形式":format_options(unique_list(sub["车身形式"])),
            "级别":format_options(unique_list(sub["级别"])),
            "座位数":format_options(unique_list(sub["座位数"]),"-"),
            "模拟近月销量":sales,
            "入选原因":"、".join([x for x,ok in [("价格带重叠",price_overlap>0),("同车身",body_match),("同级别",level_match),("同能源大类",energy_match)] if ok]),
        })
    result=pd.DataFrame(rows)
    result=result.sort_values(["匹配分","模拟近月销量"],ascending=[False,False]).reset_index(drop=True)
    core=result[result["匹配分"]>=70].head(5).copy()
    if core.empty:
        core=result.head(min(3,len(result))).copy()
    remaining=result.drop(index=core.index)
    secondary=remaining.head(5).copy()
    core["竞品层级"]="核心竞品"
    secondary["竞品层级"]="次级竞品"
    return pd.concat([core,secondary],ignore_index=True)

def render_competitor_card_grid(df,key_prefix):
    if df.empty: return
    columns=st.columns(min(3,len(df)))
    for card_index,(_,row) in enumerate(df.iterrows()):
        with columns[card_index%len(columns)]:
            css_class="core" if row["竞品层级"]=="核心竞品" else "secondary"
            st.markdown(
                f'<div class="competitor-card {css_class}">'
                f'<span class="competitor-tier">{row["竞品层级"]}</span><span class="competitor-score">规则相似度 {row["匹配分"]}</span>'
                f'<div class="competitor-name">{row["车系"]}</div><div class="competitor-brand">{row["品牌"]}</div>'
                f'<div class="competitor-price">{row["价格展示"]}</div>'
                f'<div class="competitor-meta">能源：{row["能源形式"]}<br>车身 / 级别：{row["车身形式"]} / {row["级别"]}<br>'
                f'座位：{row["座位数"]}｜模拟近月销量：{row["模拟近月销量"]:,}</div>'
                f'<div class="competitor-reason">入选依据：{row["入选原因"] or "综合替代关系"}</div></div>',
                unsafe_allow_html=True,
            )

def render_competitor_results(competitor_df,is_brand_query):
    for tier in ["核心竞品","次级竞品"]:
        tier_df=competitor_df[competitor_df["竞品层级"]==tier]
        if tier_df.empty: continue
        note="优先用于产品对标与销售拦截" if tier=="核心竞品" else "用于补充观察潜在替代关系"
        display_df=tier_df
        if tier=="次级竞品" and len(tier_df)>3:
            expand_key=f"show_all_secondary_{norm_search(st.session_state.target_query)}"
            expanded=st.session_state.get(expand_key,False)
            display_df=tier_df if expanded else tier_df.head(3)
        st.markdown(f'<div class="competitor-section-title">{tier}（{len(tier_df)}个）</div><div class="competitor-section-note">{note}，最多保留5个车型。</div>',unsafe_allow_html=True)
        if is_brand_query:
            for brand,brand_df in display_df.groupby("品牌",sort=False):
                brand_sales=int(brand_df["模拟近月销量"].sum())
                brand_score=int(brand_df["匹配分"].max())
                brand_prices=" / ".join(unique_list(brand_df["覆盖价格段"]))
                st.markdown(f'<div class="competitor-brand-header"><span class="competitor-brand-name">{brand}</span><span class="competitor-brand-count">涉及 {len(brand_df)} 个车型｜最高相似度 {brand_score}｜模拟近月销量 {brand_sales:,}｜{brand_prices}</span></div>',unsafe_allow_html=True)
                render_competitor_card_grid(brand_df,f"{tier}_{brand}")
        else:
            render_competitor_card_grid(display_df,tier)
        if tier=="次级竞品" and len(tier_df)>3:
            button_text="收起次级竞品" if st.session_state.get(expand_key,False) else f"查看全部 {len(tier_df)} 个次级竞品"
            if st.button(button_text,key=f"toggle_{expand_key}",use_container_width=True):
                st.session_state[expand_key]=not st.session_state.get(expand_key,False)
                st.rerun()

def competitor_sales_scope(target,regions,prices,energies,bodies,brands=None,series_filter=None,new_energy_only=False):
    df=target_df_all.copy()
    if regions: df=df[df["地区"].isin(regions)]
    if prices: df=df[df["价格段"].isin(prices)]
    if bodies: df=df[df["车身形式"].isin(bodies)]
    if new_energy_only:
        df=df[df["能源大类"].isin(["BEV","PHEV"])]
    elif energies:
        df=df[df["能源形式"].isin(energies)]
    target_brands=unique_list(target.get("matched_rows",pd.DataFrame()).get("品牌",[])) if target.get("found") else []
    target_series=unique_list(target.get("matched_rows",pd.DataFrame()).get("车系",[])) if target.get("found") else []
    if brands:
        df=df[df["品牌"].isin(set(brands)|set(target_brands))]
    if series_filter:
        df=df[df["车系"].isin(set(series_filter)|set(target_series))]
    return calibrate_regional_ranking(df,target.get("is_brand_query",False),regions)

def calibrate_regional_ranking(df,is_brand_query,regions):
    """Keep comparable regional structures while allowing controlled CR5 rotation."""
    if df.empty or "全国" not in regions or len(regions)<2: return df
    result=df.copy()
    result["_产品"]=result["品牌"].astype(str) if is_brand_query else result["品牌"].astype(str)+"-"+result["车系"].astype(str)
    national=(result[result["地区"]=="全国"].groupby("_产品")["销量"].mean().sort_values(ascending=False))
    if len(national)<10: return result.drop(columns="_产品")
    national_order=national.index.tolist()
    national_shares=national/max(national.sum(),1)
    for region in [value for value in regions if value!="全国"]:
        region_mask=result["地区"]==region
        regional=result[region_mask].groupby("_产品")["销量"].mean()
        regional_total=max(regional.sum(),1)
        relative_affinity=(regional/regional_total)/(national_shares.replace(0,np.nan))
        national_mid=national_order[5:10]
        promoted=sorted(national_mid,key=lambda product:float(relative_affinity.get(product,0)),reverse=True)[:2]
        remaining_mid=[product for product in national_mid if product not in promoted]
        retained_mid=sorted(remaining_mid,key=lambda product:float(relative_affinity.get(product,0)),reverse=True)[:2]
        outsiders=sorted(national_order[10:15],key=lambda product:float(relative_affinity.get(product,0)),reverse=True)[:1]
        # 全国1-3保持；各省依据自身偏好从全国6-10中选两席进入4-5；
        # 全国4-5退至6-7，CR5-10再保留两名全国腰部品并加入一个区域特色品。
        desired_order=national_order[:3]+promoted+national_order[3:5]+retained_mid+outsiders
        target_rank_shares=national_shares.iloc[:len(desired_order)].to_numpy()
        for rank,product in enumerate(desired_order):
            current=float(regional.get(product,0))
            if current<=0: continue
            desired_average=regional_total*float(target_rank_shares[rank])
            factor=np.clip(desired_average/current,.45,2.40)
            product_mask=region_mask&(result["_产品"]==product)
            result.loc[product_mask,"销量"]=(result.loc[product_mask,"销量"]*factor).round().clip(lower=1).astype(int)
    return result.drop(columns="_产品")

def add_competitor_product_label(df,is_brand_query):
    result=df.copy()
    result["竞品对象"]=result["品牌"].astype(str) if is_brand_query else result["品牌"].astype(str)+"-"+result["车系"].astype(str)
    return result

def latest_top_products(df,is_brand_query,limit=15):
    labeled=add_competitor_product_label(df,is_brand_query)
    positive=labeled[labeled["销量"]>0]
    if positive.empty: return []
    latest_index=int(positive["月份序号"].max())
    latest=(positive[positive["月份序号"]==latest_index].groupby("竞品对象",as_index=False)["销量"].sum().sort_values("销量",ascending=False))
    return latest.head(limit)["竞品对象"].tolist()

def sort_products_by_latest(labeled,products):
    positive=labeled[labeled["销量"]>0]
    latest_index=int(positive["月份序号"].max()) if not positive.empty else LAST_PERIOD_INDEX
    latest=(positive[positive["月份序号"]==latest_index].groupby("竞品对象")["销量"].sum())
    return sorted(products,key=lambda product:float(latest.get(product,0)),reverse=True)

def compact_legend_name(product,is_brand_query,is_target=False,dense=False):
    text=str(product) if is_brand_query else str(product).split("-",1)[-1]
    if dense:
        text=text[:5] if text.isascii() else text[-3:]
    elif len(text)>9:
        text=text[:8]+"…"
    return f"◇ {text}" if is_target and not dense else text

def render_top15_share_chart(df,is_brand_query,region,target_products=None,multi_region=False):
    target_products=set(target_products or [])
    labeled=add_competitor_product_label(df[df["地区"]==region],is_brand_query)
    top_products=latest_top_products(labeled,is_brand_query,15)
    available_targets=[product for product in target_products if product in set(labeled["竞品对象"])]
    if any(product not in top_products for product in available_targets):
        non_targets=[product for product in top_products if product not in available_targets]
        top_products=non_targets[:max(0,15-len(available_targets))]+available_targets[:15]
    top_products=sort_products_by_latest(labeled,top_products)
    market_month=labeled.groupby(["月份","月份序号"],as_index=False)["销量"].sum().rename(columns={"销量":"市场销量"})
    product_month=labeled[labeled["竞品对象"].isin(top_products)].groupby(["月份","月份序号","竞品对象"],as_index=False)["销量"].sum()
    chart=product_month.merge(market_month,on=["月份","月份序号"],how="left")
    chart["份额"]=np.where(chart["市场销量"]>0,chart["销量"]/chart["市场销量"]*100,0)
    palette=["#4F7FE8","#E46C54","#43B581","#F0A33A","#8B6FD6","#26A7B8","#D45F9A","#6B9FD3","#D18A54","#70A84F","#C95F68","#4F91A8","#B69A45","#5E78C8","#A86FB1"]
    fig=go.Figure()
    for index,product in enumerate(top_products):
        sub=chart[chart["竞品对象"]==product].sort_values("月份序号")
        is_target=product in target_products
        marker=dict(color=palette[index%len(palette)],line=dict(color="#FFD166",width=3)) if is_target else dict(color=palette[index%len(palette)])
        fig.add_trace(go.Bar(x=sub["月份"],y=sub["份额"],name=compact_legend_name(product,is_brand_query,is_target,multi_region),meta=product,marker=marker,customdata=sub["销量"],hovertemplate="%{x}<br>%{meta}<br>份额：%{y:.2f}%<br>销量：%{customdata:,.0f}辆<extra></extra>"))
    shown_share=chart.groupby(["月份","月份序号"],as_index=False)["份额"].sum().sort_values("月份序号")
    shown_share["其他份额"]=(100-shown_share["份额"]).clip(lower=0)
    fig.add_trace(go.Bar(x=shown_share["月份"],y=shown_share["其他份额"],name="其他",showlegend=False,marker=dict(color="rgba(148,163,184,.48)",line=dict(color="rgba(190,203,219,.65)",width=1)),hovertemplate="%{x}<br>其他份额：%{y:.2f}%<extra></extra>"))
    fig=plotly_layout(fig,455)
    fig.update_layout(barmode="stack",showlegend=False,margin=dict(l=24,r=12,t=8,b=115))
    fig.update_yaxes(title_text="TOP15占细分市场份额",ticksuffix="%")
    return fig

def render_new_energy_share_chart(df,is_brand_query,region,target_products=None,multi_region=False):
    target_products=set(target_products or [])
    labeled=add_competitor_product_label(df[df["地区"]==region],is_brand_query)
    top_products=latest_top_products(labeled,is_brand_query,15)
    available_targets=[product for product in target_products if product in set(labeled["竞品对象"])]
    if any(product not in top_products for product in available_targets):
        non_targets=[product for product in top_products if product not in available_targets]
        top_products=non_targets[:max(0,15-len(available_targets))]+available_targets[:15]
    top_products=sort_products_by_latest(labeled,top_products)
    market_month=labeled.groupby(["月份","月份序号"],as_index=False)["销量"].sum().rename(columns={"销量":"市场销量"})
    product_month=labeled[labeled["竞品对象"].isin(top_products)].groupby(["月份","月份序号","竞品对象"],as_index=False)["销量"].sum()
    chart=product_month.merge(market_month,on=["月份","月份序号"],how="left")
    chart["份额"]=np.where(chart["市场销量"]>0,chart["销量"]/chart["市场销量"]*100,0)
    palette=["#4F7FE8","#E46C54","#43B581","#F0A33A","#8B6FD6","#26A7B8","#D45F9A","#6B9FD3","#D18A54","#70A84F","#C95F68","#4F91A8","#B69A45","#5E78C8","#A86FB1"]
    fig=go.Figure()
    for index,product in enumerate(top_products):
        sub=chart[chart["竞品对象"]==product].sort_values("月份序号")
        is_target=product in target_products
        marker=dict(color=palette[index%len(palette)],line=dict(color="#FFD166",width=3)) if is_target else dict(color=palette[index%len(palette)])
        fig.add_trace(go.Bar(x=sub["月份"],y=sub["份额"],name=compact_legend_name(product,is_brand_query,is_target,multi_region),meta=product,marker=marker,customdata=sub["销量"],hovertemplate="%{x}<br>%{meta}<br>新能源市场份额：%{y:.2f}%<br>销量：%{customdata:,.0f}辆<extra></extra>"))
    shown_share=chart.groupby(["月份","月份序号"],as_index=False)["份额"].sum().sort_values("月份序号")
    shown_share["其他份额"]=(100-shown_share["份额"]).clip(lower=0)
    fig.add_trace(go.Bar(x=shown_share["月份"],y=shown_share["其他份额"],name="其他",showlegend=False,marker=dict(color="rgba(148,163,184,.48)",line=dict(color="rgba(190,203,219,.65)",width=1)),hovertemplate="%{x}<br>其他新能源SUV份额：%{y:.2f}%<extra></extra>"))
    fig=plotly_layout(fig,455)
    fig.update_layout(barmode="stack",showlegend=False,margin=dict(l=24,r=12,t=8,b=115))
    fig.update_yaxes(title_text="TOP15占新能源市场份额",ticksuffix="%")
    return fig

def competition_legend_markup(df,is_brand_query,region,target_products=None,multi_chart=False):
    target_products=set(target_products or [])
    labeled=add_competitor_product_label(df[df["地区"]==region],is_brand_query)
    products=latest_top_products(labeled,is_brand_query,15)
    available_targets=[product for product in target_products if product in set(labeled["竞品对象"])]
    if any(product not in products for product in available_targets):
        non_targets=[product for product in products if product not in available_targets]
        products=non_targets[:max(0,15-len(available_targets))]+available_targets[:15]
    products=sort_products_by_latest(labeled,products)
    palette=["#4F7FE8","#E46C54","#43B581","#F0A33A","#8B6FD6","#26A7B8","#D45F9A","#6B9FD3","#D18A54","#70A84F","#C95F68","#4F91A8","#B69A45","#5E78C8","#A86FB1"]
    items=[]
    for index,product in enumerate(products):
        target_mark="◇ " if product in target_products else ""
        name=compact_legend_name(product,is_brand_query,False,False)
        items.append(f'<span class="competition-legend-item" title="第{index+1}名｜{product}"><span class="competition-legend-rank">{index+1}</span><span class="competition-legend-swatch" style="background:{palette[index%len(palette)]}"></span><span class="competition-legend-name">{target_mark}{name}</span></span>')
    items.append('<span class="competition-legend-item" title="TOP15以外"><span class="competition-legend-rank">—</span><span class="competition-legend-swatch" style="background:rgba(148,163,184,.65)"></span><span class="competition-legend-name">其他</span></span>')
    row_class="competition-legend-multi" if multi_chart else "competition-legend-single"
    if multi_chart:
        rows=[items[:8],items[8:16]]
    else:
        rows=[items]
    row_markup="".join(f'<div class="competition-legend-row {row_class}">{"".join(row)}</div>' for row in rows)
    return f'<div class="competition-legend">{row_markup}</div>'

def competition_coverage_note(df,is_brand_query,region):
    latest=df[(df["地区"]==region)&(df["月份序号"]==LAST_PERIOD_INDEX)].copy()
    if latest.empty: return ""
    labeled=add_competitor_product_label(latest,is_brand_query)
    product_sales=labeled.groupby("竞品对象")["销量"].sum().sort_values(ascending=False)
    total=float(product_sales.sum())
    coverage=float(product_sales.head(15).sum()/total) if total else 0
    judgment="头部代表性较强" if coverage>=.75 else "市场仍较分散" if coverage<.55 else "市场呈中度分散"
    return (f'<div class="metric-formula">TOP15覆盖当前市场 <b>{coverage:.1%}</b>，其他对象合计 '
            f'<b>{1-coverage:.1%}</b>；{judgment}。</div>')

def render_competition_opportunity_insight(df,is_brand_query,regions,scope_name):
    latest=df[df["月份序号"]==LAST_PERIOD_INDEX].copy()
    if latest.empty: return
    latest=add_competitor_product_label(latest,is_brand_query)
    grouped=latest.groupby(["地区","竞品对象"],as_index=False)["销量"].sum()
    benchmark="全国" if "全国" in regions else regions[0]

    def region_profile(region):
        sub=grouped[grouped["地区"]==region].sort_values("销量",ascending=False).copy()
        total=float(sub["销量"].sum())
        sub["份额"]=np.where(total>0,sub["销量"]/total,0)
        return sub,total

    base,base_total=region_profile(benchmark)
    if base.empty: return
    leader=base.iloc[0]
    base_top3="、".join(base.head(3)["竞品对象"].astype(str))
    base_text=f'<b>{leader["竞品对象"]}</b>近月销量最高（{leader["销量"]:,.0f}辆，份额{leader["份额"]:.1%}）；TOP3为{base_top3}。'
    comparison_regions=[region for region in regions if region!=benchmark]
    if not comparison_regions:
        recent=add_competitor_product_label(df[df["地区"]==benchmark],is_brand_query).groupby(["竞品对象","月份序号"],as_index=False)["销量"].sum()
        momentum=[]
        for product,sub in recent.groupby("竞品对象"):
            sub=sub.sort_values("月份序号")
            if len(sub)>=3:
                early=float(sub.tail(3).head(1)["销量"].iloc[0]); end=float(sub.tail(1)["销量"].iloc[0])
                momentum.append((product,(end/early-1) if early>0 else 0))
        rising=max(momentum,key=lambda item:item[1]) if momentum else ("暂无稳定对象",0)
        local_text=f'当前仅选择{benchmark}，<b>{rising[0]}</b>近三个月增幅相对突出（{rising[1]:+.1%}），建议加入目标省份判断区域增量是否成立。'
        diff_text="加入省份后，系统将自动识别相对全国高配与低配品牌/车系。"
    else:
        region=comparison_regions[0]
        local,local_total=region_profile(region)
        local_leader=local.iloc[0] if not local.empty else None
        local_text=(f'<b>{local_leader["竞品对象"]}</b>在{region}近月排名第一（{local_leader["销量"]:,.0f}辆，份额{local_leader["份额"]:.1%}）。' if local_leader is not None else f'{region}当前样本不足。')
        shares=base[["竞品对象","份额"]].rename(columns={"份额":"全国份额"}).merge(local[["竞品对象","份额"]].rename(columns={"份额":"省份份额"}),on="竞品对象",how="outer").fillna(0)
        shares["差异"]=shares["省份份额"]-shares["全国份额"]
        over=shares.sort_values("差异",ascending=False).iloc[0]
        under=shares.sort_values("差异",ascending=True).iloc[0]
        diff_text=(f'<b>{over["竞品对象"]}</b>在{region}份额较全国<span class="competition-insight-delta">高{over["差异"]*100:.1f}pct</span>，区域接受度更强；'
                   f'<b>{under["竞品对象"]}</b>较全国<span class="competition-insight-delta">低{abs(under["差异"])*100:.1f}pct</span>，存在替代或补位空间。')
    st.markdown(f'<div class="competition-insight"><div class="competition-insight-title">机会点｜{scope_name}</div><div class="competition-insight-grid"><div class="competition-insight-card"><span class="competition-insight-label">{benchmark}特征</span>{base_text}</div><div class="competition-insight-card"><span class="competition-insight-label">选定省份特征</span>{local_text}</div><div class="competition-insight-card"><span class="competition-insight-label">区域差异与动作</span>{diff_text}</div></div></div>',unsafe_allow_html=True)

def competitor_product_stats(df,is_brand_query,region):
    labeled=add_competitor_product_label(df[df["地区"]==region],is_brand_query)
    monthly=labeled.groupby(["竞品对象","月份序号"],as_index=False)["销量"].sum()
    rows=[]
    last_six_indexes=[item["月份序号"] for item in REPORTING_MONTHS[-6:]]
    for product,sub in monthly.groupby("竞品对象"):
        values=sub.set_index("月份序号")["销量"]
        recent=float(values.reindex(RECENT_PERIOD_INDEXES).fillna(0).mean())
        previous_indexes=[max(1,index-3) for index in RECENT_PERIOD_INDEXES]
        previous=float(values.reindex(previous_indexes).fillna(0).mean())
        rows.append({"竞品对象":product,"月均销量":float(values.mean()),"近月销量":float(values.get(LAST_PERIOD_INDEX,0)),"近6月月均":float(values.reindex(last_six_indexes).fillna(0).mean()),"近期月均":recent,"近期增幅":safe_change(recent,previous)})
    return pd.DataFrame(rows)

def describe_product_trend(values):
    series=values.reindex([item["月份序号"] for item in REPORTING_MONTHS]).fillna(0).astype(float)
    labels={item["月份序号"]:item["月份"] for item in REPORTING_MONTHS}
    positive=series[series>0]
    launch_text=""
    if not positive.empty and int(positive.index.min())>int(series.index.min()):
        first_index=int(positive.index.min())
        launch_text=f'{labels[first_index]}开始进入销量统计，首月放量较明显；'
    interruption_text=""
    median_positive=float(positive.median()) if not positive.empty else 0
    if median_positive>0:
        low_months=series[(series.index>int(positive.index.min()))&(series<median_positive*.12)]
        if not low_months.empty:
            low_index=int(low_months.index[0])
            interruption_text=f'{labels[low_index]}出现短期让位或供应扰动、当月接近未上榜；'
    rolling=series.rolling(3).mean()
    change=rolling.pct_change(3).replace([np.inf,-np.inf],np.nan).dropna()
    if change.empty: return launch_text+interruption_text+"月度销量整体保持平稳"
    end_index=int(change.idxmax())
    start_index=max(int(series.index.min()),end_index-2)
    surge=float(change.loc[end_index])
    later=series.loc[end_index:]
    later_change=safe_change(float(later.iloc[-1]),float(later.iloc[0])) if len(later)>1 else 0
    first=f'{labels[start_index]}至{labels[end_index]}销量'+("明显上升" if surge>=.15 else "温和上升")+f' {surge:+.1%}'
    second=(f'，此后延续上升 {later_change:+.1%}' if later_change>.05 else
            f'，此后回落 {later_change:+.1%}' if later_change<-.05 else "，此后进入相对平稳阶段")
    return launch_text+interruption_text+first+second

def attach_competition_evidence(tiers,df,target,is_brand_query,benchmark,comparison):
    if tiers.empty: return tiers
    labeled=add_competitor_product_label(df,is_brand_query)
    target_products=set(unique_list(target["matched_rows"]["品牌"] if is_brand_query else target["matched_rows"]["品牌"].astype(str)+"-"+target["matched_rows"]["车系"].astype(str)))
    result=tiers.copy()
    evidence=[]
    for _,row in result.iterrows():
        region=comparison if row["竞品层级"]=="次级竞品" and comparison else benchmark
        monthly=(labeled[labeled["地区"]==region].groupby(["竞品对象","月份序号"],as_index=False)["销量"].sum())
        product_values=monthly[monthly["竞品对象"]==row["竞品对象"]].set_index("月份序号")["销量"]
        target_values=monthly[monthly["竞品对象"].isin(target_products)].groupby("月份序号")["销量"].sum()
        indexes=[item["月份序号"] for item in REPORTING_MONTHS]
        product_values=product_values.reindex(indexes).fillna(0)
        target_values=target_values.reindex(indexes).fillna(0)
        recent_indexes=indexes[-6:]
        product_recent_mean=float(product_values.loc[recent_indexes].mean())
        target_recent_mean=float(target_values.loc[recent_indexes].mean())
        recent_gap=safe_change(product_recent_mean,target_recent_mean)
        recent_ratio=product_recent_mean/target_recent_mean if target_recent_mean>0 else 0
        ratios=(product_values/target_values.replace(0,np.nan)-1).replace([np.inf,-np.inf],np.nan).dropna()
        if not ratios.empty:
            strongest_months=ratios.nlargest(min(2,len(ratios))).sort_index()
            month_evidence="、".join(
                f'{PERIOD_LABELS[int(index)-1]}较本品高 {float(gap):+.1%}' if float(gap)>=0
                else f'{PERIOD_LABELS[int(index)-1]}较本品低 {abs(float(gap)):.1%}'
                for index,gap in strongest_months.items()
            )
            comparison_text=(f'近6个月月均销量较本品高 {recent_gap:+.1%}；{month_evidence}'
                             if recent_gap>=0 else f'近6个月月均销量较本品低 {abs(recent_gap):.1%}，但{month_evidence}')
        else:
            comparison_text="当前口径下本品对照销量不足，暂以自身趋势判断"
        trend_text=describe_product_trend(product_values)
        if target_recent_mean<=0:
            conclusion="当前缺少稳定的本品对照基准，主要依据该竞品自身销量趋势判断竞争压力。"
        elif recent_ratio>=1.10:
            conclusion=f'近6个月月均销量达到本品的 {recent_ratio:.2f} 倍，并持续形成直接领先压力。'
        elif recent_ratio>=.80:
            conclusion=f'近6个月月均销量达到本品的 {recent_ratio:.2f} 倍，整体接近本品并在部分月份形成反超。'
        elif recent_ratio>=.50:
            conclusion=f'近6个月月均销量达到本品的 {recent_ratio:.2f} 倍，规模暂低但阶段性放量值得持续防守。'
        else:
            conclusion=f'近6个月月均销量为本品的 {recent_ratio:.2f} 倍，当前规模有限，但近期波动可能形成潜在威胁。'
        evidence.append(f'{conclusion}|||{comparison_text}；{trend_text}')
    result["竞争表现"]=evidence
    return result

def emphasize_competitor_text(text):
    escaped=str(text)
    pattern=r"(20\d{2}年\d{2}月|[+-]?\d+(?:\.\d+)?%|[\d,]+\s*辆)"
    return re.sub(pattern,r'<span class="evidence-highlight">\1</span>',escaped)

def classify_competitors(df,target,is_brand_query,regions):
    benchmark="全国" if "全国" in regions else regions[0]
    comparison=next((region for region in regions if region!=benchmark),None)
    base=competitor_product_stats(df,is_brand_query,benchmark)
    if base.empty: return pd.DataFrame()
    target_brands=set(unique_list(target["matched_rows"]["品牌"]))
    target_brand_keys={norm_search(brand).replace("汽车","").replace("集团","") for brand in target_brands}
    target_products=set(unique_list(target["matched_rows"]["品牌"] if is_brand_query else target["matched_rows"]["品牌"].astype(str)+"-"+target["matched_rows"]["车系"].astype(str)))
    target_latest=float(base[base["竞品对象"].isin(target_products)]["近月销量"].sum())
    target_six=float(base[base["竞品对象"].isin(target_products)]["近6月月均"].sum())/max(len(target_products),1)
    own_products=target_products if is_brand_query else set(base[base["竞品对象"].apply(lambda value:norm_search(str(value).split("-",1)[0]).replace("汽车","").replace("集团","") in target_brand_keys)]["竞品对象"])
    candidates=base[~base["竞品对象"].isin(own_products)].copy()
    candidates["竞争强度"]=candidates["月均销量"]*.45+candidates["近月销量"]*.55
    core_mask=((candidates["近6月月均"]>=target_six*.90)|
               ((candidates["近月销量"]>=target_latest*1.05)&(candidates["近6月月均"]>=target_six*.75)))
    core=candidates[core_mask].sort_values("竞争强度",ascending=False).head(4).copy()
    core["竞品层级"]="核心竞品"
    core["入选原因"]=core["近6月月均"].apply(lambda value:f'近6个月月均销量较本品高 {safe_change(value,target_six):+.1%}，持续形成直接竞争压力' if value>=target_six else f'近6个月月均销量达到本品的 {value/max(target_six,1):.2f} 倍，且近月具备阶段性反超能力')
    used=set(core["竞品对象"])
    tier_frames=[core]
    secondary=candidates[(~candidates["竞品对象"].isin(used))&(candidates["近期增幅"]>0)].sort_values(["近期增幅","近期月均"],ascending=False).head(3).copy()
    secondary["竞品层级"]="次级竞品"
    secondary["入选原因"]=secondary["近期增幅"].apply(lambda value:f"近三个月销量增长 {value:+.1%}，正在形成新增竞争压力")
    tier_frames.append(secondary)
    result=pd.concat(tier_frames,ignore_index=True,sort=False)
    return attach_competition_evidence(result,df,target,is_brand_query,benchmark,comparison)

def concentration_table(df,target,is_brand_query,regions):
    target_products=set(unique_list(target["matched_rows"]["品牌"] if is_brand_query else target["matched_rows"]["品牌"].astype(str)+"-"+target["matched_rows"]["车系"].astype(str)))
    rows=[]
    for region in regions:
        stats=competitor_product_stats(df,is_brand_query,region).sort_values("月均销量",ascending=False).reset_index(drop=True)
        total=stats["月均销量"].sum()
        top3=stats.head(3); top5=stats.head(5)
        target_mask=stats["竞品对象"].isin(target_products)
        target_rank=int(stats.index[target_mask][0])+1 if target_mask.any() else None
        target_share=stats.loc[target_mask,"月均销量"].sum()/total if total else 0
        target_average=float(stats.loc[target_mask,"月均销量"].sum())
        fifth_average=float(top5.iloc[-1]["月均销量"]) if len(top5)>=5 else 0
        gap_to_cr5=max(0,fifth_average-target_average) if not target_rank or target_rank>5 else 0
        rows.append({"地区":region,"CR3":top3["月均销量"].sum()/total if total else 0,"CR3成员":"、".join(top3["竞品对象"].astype(str)),"CR5":top5["月均销量"].sum()/total if total else 0,"CR5成员":"、".join(top5["竞品对象"].astype(str)),"本品头部位置":f"第{target_rank}名｜市占率 {target_share:.2%}" if target_rank else "未进入当前市场排名","进入CR5月均差距":gap_to_cr5,"提升1pct所需月销":total*.01})
    return pd.DataFrame(rows)

def render_concentration_table(cr_df):
    rows="".join([
        f'<tr><td>{row["地区"]}</td><td><b>{row["CR3"]:.2%}</b><br>{row["CR3成员"]}</td><td><b>{row["CR5"]:.2%}</b><br>{row["CR5成员"]}</td><td>{row["本品头部位置"]}</td><td><b>{row["进入CR5月均差距"]:,.0f} 辆</b><br>提升1pct约需 {row["提升1pct所需月销"]:,.0f} 辆/月</td></tr>'
        for _,row in cr_df.iterrows()
    ])
    base=cr_df.iloc[0]
    level="高度集中" if base["CR5"]>=.65 else "中度集中" if base["CR5"]>=.45 else "相对分散"
    chance=("头部壁垒较强，应围绕CR3核心对象开展一对一替代。" if base["CR5"]>=.65 else "头部格局尚未完全固化，本品仍有通过差异化切入CR5的机会。" if base["CR5"]>=.45 else "份额较分散，本品可优先争取腰部与游离用户扩大份额。")
    conclusion=f'{base["地区"]}市场属于 <b>{level}</b>：CR3为 <b>{base["CR3"]:.2%}</b>、CR5为 <b>{base["CR5"]:.2%}</b>。{base["本品头部位置"]}；{chance}'
    st.markdown(f'<div class="chart-card"><table class="cr-table"><thead><tr><th>地区/对照组</th><th>CR3</th><th>CR5</th><th>本品头部位置</th><th>进入CR5所需增量</th></tr></thead><tbody>{rows}</tbody></table><div class="cr-conclusion">{conclusion}</div></div>',unsafe_allow_html=True)

def render_competitor_overview(tiers,cr_df,regions):
    core_rows=tiers[tiers["竞品层级"]=="核心竞品"].head(4) if not tiers.empty else pd.DataFrame()
    core_names=core_rows["竞品对象"].astype(str).tolist() if not core_rows.empty else []
    core_cards=[]
    for _,row in core_rows.iterrows():
        evidence=str(row.get("竞争表现","暂无稳定竞争结论"))
        conclusion=evidence.split("|||",1)[0]
        core_cards.append(
            f'<div class="overview-core-card"><div class="overview-core-name">{row["竞品对象"]}</div>'
            f'<div class="overview-core-note">{conclusion}</div></div>'
        )
    core_cards_html="".join(core_cards) or '<div class="overview-core-card"><div class="overview-core-name">暂未形成稳定核心竞品</div><div class="overview-core-note">当前样本尚不足以识别持续领先或直接替代关系。</div></div>'
    verdict="当前口径样本不足，建议放宽筛选范围后再判断竞争强度与市场切入机会。"
    if cr_df.empty:
        concentration="当前口径暂无足够样本计算市场集中度。"
    else:
        benchmark="全国" if "全国" in set(cr_df["地区"]) else str(cr_df.iloc[0]["地区"])
        base=cr_df[cr_df["地区"]==benchmark].iloc[0]
        level="高度集中" if base["CR5"]>=.65 else "中度集中" if base["CR5"]>=.45 else "相对分散"
        concentration=f'{benchmark}市场{level}：CR3为 <b>{base["CR3"]:.2%}</b>、CR5为 <b>{base["CR5"]:.2%}</b>；{base["本品头部位置"]}。'
        comparisons=[]
        for _,row in cr_df[cr_df["地区"]!=benchmark].iterrows():
            gap=(row["CR5"]-base["CR5"])*100
            comparisons.append(f'{row["地区"]}较{benchmark} {gap:+.2f}pct')
        if comparisons:
            concentration+=f' 区域CR5差异：{"；".join(comparisons)}。'
        core_text="、".join(core_names) if core_names else "暂未形成稳定核心竞品"
        if base["CR5"]<.45:
            market_judgment="头部壁垒尚未固化，市场仍有从腰部车型和波动份额中切入的空间"
        elif base["CR5"]<.65:
            market_judgment="市场已有较明确头部，但尚未形成绝对垄断，需要围绕核心竞品建立一对一替代理由"
        else:
            market_judgment="份额高度向头部集中，应收缩攻击面并优先突破CR3竞品的核心用户"
        regional_rows=cr_df[cr_df["地区"]!=benchmark].copy()
        regional_note=""
        if not regional_rows.empty:
            regional_rows["CR5差值"]=regional_rows["CR5"]-base["CR5"]
            opportunity_row=regional_rows.sort_values("CR5差值").iloc[0]
            regional_note=f'；其中{opportunity_row["地区"]}CR5较{benchmark}{opportunity_row["CR5差值"]*100:+.2f}pct，可作为区域机会验证重点'
        verdict=f'当前主要竞争压力来自 {core_text}。{market_judgment}{regional_note}。结合本品位置，应优先监控核心竞品近月份额变化，并针对其强势月份、价格权益和主销场景制定攻防动作。'
    st.markdown(
        f'<div class="overview-shell"><div class="overview-title">竞争要点速览</div>'
        f'<div class="overview-section-label">核心竞品</div><div class="overview-core-grid">{core_cards_html}</div>'
        f'<div class="overview-section-label">集中度特征</div><div class="overview-concentration">{concentration}</div>'
        f'<div class="overview-verdict"><span class="overview-verdict-label">核心结论</span>{verdict}</div></div>',unsafe_allow_html=True)

def render_head_to_head(tiers,sales_scope,target,is_brand_query,regions):
    candidates=tiers[tiers["竞品层级"]=="核心竞品"]["竞品对象"].astype(str).head(4).tolist() if not tiers.empty else []
    if not candidates:
        return
    benchmark="全国" if "全国" in regions else regions[0]
    target_products=set(unique_list(target["matched_rows"]["品牌"] if is_brand_query else target["matched_rows"]["品牌"].astype(str)+"-"+target["matched_rows"]["车系"].astype(str)))
    labeled=add_competitor_product_label(sales_scope[sales_scope["地区"]==benchmark],is_brand_query)
    with st.expander("核心竞品对比工具｜选择竞品查看差距",expanded=True):
        competitor=st.selectbox("选择对比竞品",candidates,key="head_to_head_competitor")
        monthly=labeled.groupby(["竞品对象","月份","月份序号"],as_index=False)["销量"].sum()
        target_month=(monthly[monthly["竞品对象"].isin(target_products)].groupby(["月份","月份序号"],as_index=False)["销量"].sum().rename(columns={"销量":"本品"}))
        competitor_month=monthly[monthly["竞品对象"]==competitor][["月份","月份序号","销量"]].rename(columns={"销量":"竞品"})
        compare=target_month.merge(competitor_month,on=["月份","月份序号"],how="outer").fillna(0).sort_values("月份序号")
        recent_indexes=[item["月份序号"] for item in REPORTING_MONTHS[-6:]]
        recent=compare[compare["月份序号"].isin(recent_indexes)]
        own_avg=float(recent["本品"].mean()) if len(recent) else 0
        rival_avg=float(recent["竞品"].mean()) if len(recent) else 0
        gap=safe_change(rival_avg,own_avg)
        c1,c2,c3=st.columns(3)
        c1.metric("本品近6月月均",f"{own_avg:,.0f} 辆")
        c2.metric(f"{competitor}近6月月均",f"{rival_avg:,.0f} 辆")
        c3.metric("竞品相对本品",f"{gap:+.1%}")
        long=compare.melt(id_vars=["月份","月份序号"],value_vars=["本品","竞品"],var_name="对象",value_name="销量")
        long["对象"]=long["对象"].replace({"竞品":competitor})
        fig=px.line(long,x="月份",y="销量",color="对象",markers=True,category_orders={"月份":PERIOD_LABELS},color_discrete_map={"本品":"#FFD166",competitor:"#6EA8FE"})
        fig=plotly_layout(fig,320)
        fig.update_layout(legend=dict(orientation="h",x=.5,xanchor="center",y=1.08))
        render_responsive_chart(fig,use_container_width=True)

def render_competitor_tiers(tiers,is_brand_query):
    for tier,limit,note in [("核心竞品",4,"长期或近期销量领先，形成直接竞争压力"),("次级竞品",3,"近期销量增长，可能形成新增竞争压力")]:
        current=tiers[tiers["竞品层级"]==tier].head(limit)
        st.markdown(f'<div class="competitor-section-title">{tier}</div><div class="competitor-section-note">{note}</div>',unsafe_allow_html=True)
        if current.empty:
            st.markdown('<div class="competitor-card secondary"><div class="competitor-name">暂无显著对象</div><div class="competitor-reason">当前筛选范围内没有满足该层级量化条件的品牌或车系。</div></div>',unsafe_allow_html=True)
            continue
        def card_markup(row):
            detail=(f'近6月月均 {row.get("近6月月均",0):,.0f} 辆｜近月 {row.get("近月销量",0):,.0f} 辆'
                    if tier=="核心竞品" else
                    f'近期增幅 {row.get("近期增幅",0):+.1%}｜近期月均 {row.get("近期月均",0):,.0f} 辆')
            evidence_parts=str(row.get("竞争表现","暂无趋势说明")).split("|||",1)
            conclusion_html=emphasize_competitor_text(evidence_parts[0])
            evidence_html=emphasize_competitor_text(evidence_parts[1] if len(evidence_parts)>1 else evidence_parts[0])
            rule_html=emphasize_competitor_text(row["入选原因"])
            css_class="core" if tier=="核心竞品" else "secondary"
            return f'<div class="competitor-card {css_class}"><span class="competitor-tier">{tier}</span><div class="competitor-name">{row["竞品对象"]}</div><div class="competitor-rationale"><b>入选依据</b><span class="evidence-conclusion">{conclusion_html}</span>{evidence_html}<span class="rationale-rule">分级判定：{rule_html}</span></div><div class="competitor-price">{detail}</div></div>'

        if tier=="核心竞品" and len(current)==4:
            cards="".join(card_markup(row) for _,row in current.iterrows())
            st.markdown(f'<div class="tier-core-grid">{cards}</div>',unsafe_allow_html=True)
        else:
            columns=st.columns(min(3,len(current)))
            for index,(_,row) in enumerate(current.iterrows()):
                with columns[index%len(columns)]:
                    st.markdown(card_markup(row),unsafe_allow_html=True)

def render_competitor_summary(tiers,cr_df,target,is_brand_query,regions,prices,bodies,sales_scope):
    lists={tier:"、".join(tiers[tiers["竞品层级"]==tier]["竞品对象"].astype(str).tolist()) or "暂无显著对象" for tier in ["核心竞品","次级竞品"]}
    benchmark="全国" if "全国" in regions else regions[0]
    comparison=next((region for region in regions if region!=benchmark),None)
    concentration=""
    opportunity=""
    if comparison and not cr_df.empty:
        base=cr_df[cr_df["地区"]==benchmark].iloc[0]; region_row=cr_df[cr_df["地区"]==comparison].iloc[0]
        gap=(region_row["CR5"]-base["CR5"])*100
        concentration=f'{comparison}{format_options(prices)}{format_options(bodies)}市场CR5为 {region_row["CR5"]:.2%}，较{benchmark} {gap:+.2f}pct；'+("集中度更低，头部尚未完全固化。" if gap<0 else "集中度更高，头部竞争更充分。")
        if gap <= -3:
            opportunity=f'{comparison}市场比{benchmark}更分散，尚有争夺非头部份额的窗口；可优先利用本地渠道、区域权益和场景化传播扩大覆盖，而不是只与第一名正面对撞。'
        elif gap >= 3:
            opportunity=f'{comparison}市场份额更向头部集中，泛化投放的效率有限；应锁定CR3成员的主销车型，围绕价格权益、空间与补能体验建立明确的替代理由。'
        else:
            opportunity=f'{comparison}与{benchmark}的集中度接近，区域结构并未出现明显空档；机会主要来自对核心竞品优势区域的定向拦截，以及对次级竞品上升势头的提前防守。'
    else:
        row=cr_df.iloc[0]
        level="高" if row["CR5"]>=0.65 else "中等" if row["CR5"]>=0.45 else "较低"
        concentration=f'{row["地区"]}市场CR3为 {row["CR3"]:.2%}、CR5为 {row["CR5"]:.2%}，市场集中度{level}；{row["本品头部位置"]}。'
        if row["CR5"] < 0.45:
            opportunity="市场格局较分散、尚未形成稳固的五强壁垒，新增产品仍有切入空间；应先争取腰部车型的游离用户，再逐步冲击CR5。"
        elif row["CR5"] < 0.65:
            opportunity="市场已有头部但格局尚未完全固化，机会在于从核心竞品手中争夺换购与横向比较用户，并通过差异化产品利益点进入CR5。"
        else:
            opportunity="市场份额高度集中，单纯依赖市场自然增长难以突围；需要针对CR3车型形成清晰的一对一攻防，并集中资源打透高贡献区域与渠道。"
    target_energy=format_options(unique_list(target["matched_rows"]["能源大类"]))
    target_price_low=float(target["matched_rows"]["价格下限"].min())
    core_products=tiers[tiers["竞品层级"]=="核心竞品"]["竞品对象"].astype(str).tolist()
    representative=[]
    latest_scope=sales_scope[sales_scope["月份序号"]==LAST_PERIOD_INDEX]
    for product in core_products[:3]:
        if is_brand_query:
            sub=latest_scope[latest_scope["品牌"].astype(str)==product].groupby(["品牌","车系"],as_index=False)["销量"].sum().sort_values("销量",ascending=False)
            if len(sub): representative.append(f'{sub.iloc[0]["品牌"]}-{sub.iloc[0]["车系"]}')
        else:
            representative.append(product)
    comp_rows=car_df[(car_df["品牌"].astype(str)+"-"+car_df["车系"].astype(str)).isin(representative)]
    comp_price_low=float(comp_rows["价格下限"].median()) if len(comp_rows) else target_price_low
    price_point=(f'本品起售价较核心竞品代表车型低约 {max(comp_price_low-target_price_low,0):.1f} 万元，可强化价格价值与配置获得感。' if target_price_low<comp_price_low else '核心竞品价格进入门槛不高，本品需要用配置、空间和使用成本建立跨品替代理由。')
    representative_text="、".join(representative) or lists["核心竞品"]
    core_rows=tiers[tiers["竞品层级"]=="核心竞品"]
    pressure=""
    if not core_rows.empty:
        strongest=core_rows.sort_values("近6月月均",ascending=False).iloc[0]
        pressure=f'{strongest["竞品对象"]}近6个月月均销量约 {strongest["近6月月均"]:,.0f} 辆，是当前最需要优先拦截的稳定压力源。'
    potential_rows=tiers[tiers["竞品层级"]=="次级竞品"]
    threat=""
    if not potential_rows.empty:
        rising=potential_rows.sort_values("近期增幅",ascending=False).iloc[0]
        threat=f'同时关注{rising["竞品对象"]}近期 {rising["近期增幅"]:+.1%} 的增长动能，避免其次级竞争压力升级为直接竞品。'
    attack=f'优先围绕 {representative_text} 展开车型级对标。{pressure}{price_point} 本品可突出{target_energy}补能路线与{format_options(bodies)}场景适配；{threat}防守上持续监控近月份额、区域增速、降价及权益变化。'
    st.markdown(f'<div class="competitor-summary"><h4>攻防建议</h4><div class="summary-grid">'
                f'<div class="summary-card wide potential-summary"><span class="summary-label">市场切入机会</span><span class="summary-key">核心结论：</span>{opportunity}</div>'
                f'<div class="summary-card wide core-summary"><span class="summary-label">竞品攻防动作</span><span class="summary-key">核心动作：</span>{attack}</div>'
                f'</div></div>',unsafe_allow_html=True)

def render_page_title(title,subtitle,icon="📈"):
    st.markdown(f'<div class="main-title-row"><div class="page-icon">{icon}</div><div class="main-title">{title}</div></div><div class="sub-title">{subtitle}</div>',unsafe_allow_html=True)

def render_help_title(title,help_text,anchor=None):
    anchor_html=f'<span id="{html.escape(anchor)}"></span>' if anchor else ''
    st.markdown(
        f'{anchor_html}<div class="section-title-line"><div class="section-title-text">{html.escape(title)}</div>'
        f'<span class="mini-help" data-tooltip="{html.escape(help_text,quote=True)}">&#128279;&#65038;</span></div>',
        unsafe_allow_html=True,
    )

def render_section_nav(page_key):
    if page_key=="market":
        items=[("market-trend","市场走势","容量与份额"),("price-structure","价格结构","价格带机会"),("energy-structure","能源形式","能源渗透"),("body-structure","车身结构","车型偏好"),("market-opportunity","机会研判","结论汇总")]
    elif page_key=="user":
        items=[("user-profile","用户画像","人群结构"),("user-needs","核心需求","关注排序"),("user-concerns","顾虑提升","转化阻力"),("user-competitors","竞品比较","选择关系"),("user-scripts","沟通话术","转化表达"),("user-reviews","用户实评","原声证据")]
    else:
        items=[("competition-overview","要点速览","先看核心结论"),("competition-chart","竞争格局","份额与变化"),("concentration","市场集中度","CR3 / CR5"),("competitor-pool","竞品池","分级与依据"),("attack-summary","攻防建议","机会与动作")]
    links="".join(f'<a href="#{anchor}"><span class="section-nav-index">{index:02d}</span><span class="section-nav-copy"><span class="section-nav-label">{label}</span><span class="section-nav-desc">{desc}</span></span></a>' for index,(anchor,label,desc) in enumerate(items,1))
    note="点击卡片可跳转对应分析模块"
    st.markdown(f'<nav class="section-nav"><div class="section-nav-head"><div class="section-nav-heading"><span class="section-nav-icon">⌁</span>页面分析导览</div><div class="section-nav-note">{note}</div></div><div class="section-nav-links">{links}</div></nav>',unsafe_allow_html=True)

def render_market_quick_actions(target):
    scenes={
        "default":{"kicker":"基础","title":"恢复本品默认口径","desc":"回到车型天然覆盖的价格、能源与车身范围","tags":["本品范围","全国"]},
        "hubei":{"kicker":"区域对标","title":"全国 vs 湖北对比","desc":"快速识别目标省份相对全国的结构差异与机会点","tags":["全国","湖北","自动生成对比结论"]},
        "focus":{"kicker":"聚焦","title":"聚焦本品核心细分","desc":"收窄至本品主要价格、能源与车身市场","tags":["主销价格","目标能源","目标车身"]},
    }
    selected=st.session_state.get("selected_market_quick_scene","default")
    st.markdown('<div class="quick-scope-head"><div><div class="quick-scope-title"><span class="quick-scope-title-icon">✦</span>选择分析场景</div><div class="quick-scope-sub">一键套用常用筛选组合，确认前可查看即将改变的分析条件</div></div><span class="quick-scope-recommend">场景化分析</span></div>',unsafe_allow_html=True)
    cols=st.columns(3,gap="small")
    for col,(scene_key,scene) in zip(cols,scenes.items()):
        with col:
            with st.container(border=True):
                tags="".join(f'<span class="quick-card-tag">{tag}</span>' for tag in scene["tags"])
                st.markdown(f'<span class="quick-card-kicker">{scene["kicker"]}</span><div class="quick-card-title">{scene["title"]}</div><div class="quick-card-desc">{scene["desc"]}</div><div class="quick-card-tags">{tags}</div>',unsafe_allow_html=True)
                button_label="✓ 已选择" if selected==scene_key else "选择此场景"
                if st.button(button_label,use_container_width=True,key=f"select_quick_market_{scene_key}",type="primary" if selected==scene_key else "secondary"):
                    st.session_state["selected_market_quick_scene"]=scene_key
                    st.rerun()

    price_text=merged_price_range(target.get("覆盖价格段",[]) or PRICE_SEGMENTS)
    energy_text=format_options(target.get("能源形式列表",[]) or ENERGY_OPTIONS)
    body_text=format_options(target.get("车身形式列表",[]) or BODY_OPTIONS)
    region_text="全国 / 湖北省" if selected=="hubei" else "全国"
    st.markdown(f'<div class="quick-scope-preview"><div><div class="quick-preview-label">应用后分析口径</div><div class="quick-preview-value">{region_text}｜{price_text}｜{energy_text}｜{body_text}</div></div><div class="quick-preview-note">当前页面不会立即改变<br>点击“应用该场景”后生效</div></div>',unsafe_allow_html=True)
    if st.button("应用该场景",use_container_width=True,key="apply_market_quick_scene",type="primary"):
        reset_filters("market",target)
        if selected=="hubei":
            st.session_state["regions_market"]=["全国","湖北省"]
            st.session_state["pending_regions_market"]=["全国","湖北省"]
        st.rerun()

def build_analysis_export(target,regions,prices,energies,bodies,scope_map=None,cr_df=None,tiers=None):
    lines=[f'# {target.get("车系","目标对象")} GTM分析摘要','',f'- 分析版本：{APP_VERSION}',f'- 地区：{format_options(regions)}',f'- 价格段：{format_options(prices)}',f'- 能源形式：{format_options(energies)}',f'- 车身形式：{format_options(bodies)}','']
    if scope_map:
        lines.append('## 市场核心指标')
        for region,(market_scope,target_scope) in scope_map.items():
            metrics=region_metrics(market_scope,target_scope)
            lines.append(f'- {region}：近12月市场 {metrics["last12_market"]:,.0f} 辆，近3月月均 {metrics["recent_avg"]:,.0f} 辆，目标近月销量 {metrics["latest"]:,.0f} 辆，近月份额 {metrics["latest_share"]:.2%}。')
    if cr_df is not None and not cr_df.empty:
        lines+=['','## 市场集中度']
        for _,row in cr_df.iterrows():
            lines.append(f'- {row["地区"]}：CR3 {row["CR3"]:.2%}，CR5 {row["CR5"]:.2%}，{row["本品头部位置"]}。')
    if tiers is not None and not tiers.empty:
        lines+=['','## 竞品分级']
        for tier in ["核心竞品","次级竞品","潜在竞品"]:
            names="、".join(tiers[tiers["竞品层级"]==tier]["竞品对象"].astype(str).tolist()) or "暂无"
            lines.append(f'- {tier}：{names}')
    lines+=['','> 市场销量为模拟数据，仅用于Demo分析框架验证。']
    return '\n'.join(lines)

def build_market_pdf_report(target,regions,prices,energies,bodies,scope_map,energy_scope_map,body_scope_map):
    benchmark="全国" if "全国" in regions else regions[0]
    market_scope,target_scope=scope_map[benchmark]
    metrics=region_metrics(market_scope,target_scope)
    cards=[("近12月市场容量",f'{metrics["last12_market"]:,.0f} 辆',"滚动12个月"),
           ("近3月市场月均",f'{metrics["recent_avg"]:,.0f} 辆',f'较此前3个月 {metrics["growth"]:+.1%}'),
           ("目标近月销量",f'{metrics["latest"]:,.0f} 辆',PERIOD_LABELS[-1]),
           ("目标近月份额",f'{metrics["latest_share"]:.2%}',benchmark)]
    region_rows=[]
    for region in regions:
        region_metrics_value=region_metrics(*scope_map[region])
        region_rows.append([region,f'{region_metrics_value["last12_market"]:,.0f}',f'{region_metrics_value["growth"]:+.1%}',f'{region_metrics_value["latest"]:,.0f}',f'{region_metrics_value["latest_share"]:.2%}'])
    price_totals=market_scope.groupby("价格段")["销量"].sum().sort_values(ascending=False)
    energy_totals=energy_scope_map[benchmark][0].groupby("能源大类")["销量"].sum().sort_values(ascending=False)
    body_totals=body_scope_map[benchmark][0].groupby("车身形式")["销量"].sum().sort_values(ascending=False)
    leading_price=str(price_totals.index[0]) if len(price_totals) else "待判断"
    leading_energy=str(energy_totals.index[0]) if len(energy_totals) else "待判断"
    leading_body=str(body_totals.index[0]) if len(body_totals) else "待判断"
    direction="扩张" if metrics["growth"]>.03 else "收缩" if metrics["growth"]<-.03 else "基本稳定"
    core_judgment=(f'{benchmark}细分市场当前呈{direction}态势，主力价格带为{leading_price}，市场主导能源为{leading_energy}、主导车身为{leading_body}。'
                   f'目标对象近月市占率为{metrics["latest_share"]:.2%}。建议以主力价格带建立价值锚点，并结合目标能源在完整市场中的结构变化安排渠道和传播资源。')
    sections=[
        {"title":"核心指标", "cards":cards},
        {"title":"地区对比", "table":{"headers":["地区","近12月市场","目标近月销量","目标近月份额"],"rows":[[row[0],row[1],row[3],row[4]] for row in region_rows],"widths":[36*mm,48*mm,48*mm,48*mm]}},
        {"title":"结构判断", "cards":[("主力价格带",leading_price,"容量锚点"),("主导能源",leading_energy,"完整能源市场"),("主导车身",leading_body,"完整车身市场")]},
        {"title":"GTM核心结论", "body":core_judgment},
    ]
    return build_gtm_pdf(f'{target["车系"]} 市场大盘报告',f'{PERIOD_RANGE_TEXT} | GTM市场机会分析',
                         [("分析对象",target["车系"]),("分析地区",format_options(regions)),
                          ("分析口径",f'{format_options(prices)} / {format_options(energies)} / {format_options(bodies)}')],
                         sections,"数据说明：车型属性来自car_info基础表；市场与车型销量为模拟数据，仅用于验证分析框架。")

def build_competitor_pdf_report(target,regions,prices,energies,bodies,cr_df,tiers):
    core=tiers[tiers["竞品层级"]=="核心竞品"].head(4) if not tiers.empty else pd.DataFrame()
    cards=[]
    for _,row in core.iterrows():
        conclusion=str(row.get("竞争表现","暂无稳定结论")).split("|||",1)[0]
        cards.append((str(row["竞品对象"]),f'{row.get("近6月月均",0):,.0f} 辆/月',conclusion))
    concentration_rows=[]
    for _,row in cr_df.iterrows():
        concentration_rows.append([row["地区"],f'{row["CR3"]:.2%}',f'{row["CR5"]:.2%}',row["本品头部位置"],f'{row["进入CR5月均差距"]:,.0f} 辆/月'])
    tier_lines=[]
    for tier in ["核心竞品","次级竞品","潜在竞品"]:
        names="、".join(tiers[tiers["竞品层级"]==tier]["竞品对象"].astype(str).tolist()) or "暂无显著对象"
        tier_lines.append(f'{tier}：{names}')
    benchmark_row=cr_df.iloc[0] if not cr_df.empty else None
    if benchmark_row is not None:
        level="高度集中" if benchmark_row["CR5"]>=.65 else "中度集中" if benchmark_row["CR5"]>=.45 else "相对分散"
        opportunity=("应集中资源针对CR3车型形成一对一替代。" if benchmark_row["CR5"]>=.65 else
                     "已有头部但尚未完全固化，可从腰部及换购用户中争取份额。" if benchmark_row["CR5"]>=.45 else
                     "头部壁垒较弱，仍有较明显的新产品切入空间。")
        conclusion=f'{benchmark_row["地区"]}市场{level}，CR5为{benchmark_row["CR5"]:.2%}；{benchmark_row["本品头部位置"]}。{opportunity}'
    else:
        conclusion="当前筛选范围样本不足，暂无法形成稳定集中度判断。"
    sections=[
        {"title":"核心竞品", "cards":cards or [("暂无稳定核心竞品","-","建议放宽筛选范围后重新判断")]},
        {"title":"竞品分级", "body":"；".join(tier_lines)},
        {"title":"市场集中度", "table":{"headers":["地区","CR3","CR5","本品位置","进入CR5差距"],"rows":concentration_rows,"widths":[27*mm,24*mm,24*mm,52*mm,47*mm]}},
        {"title":"竞争格局结论", "body":conclusion},
    ]
    return build_gtm_pdf(f'{target["车系"]} 竞品格局报告',f'{PERIOD_RANGE_TEXT} | 竞品识别与集中度分析',
                         [("分析对象",target["车系"]),("分析地区",format_options(regions)),
                          ("竞争市场",f'{format_options(prices)} / {format_options(energies)} / {format_options(bodies)}')],
                         sections,"数据说明：竞品分级基于当前筛选市场的模拟销量关系；正式决策前需使用真实销量复核。")

def render_footer_note():
    st.markdown("---")
    st.markdown('<div class="small-note">销量与问卷画像含虚拟演示数据；用户口碑包含带来源链接的公开内容归纳，仅用于功能与分析框架演示。</div>',unsafe_allow_html=True)

def render_data_status():
    st.markdown('<div class="data-status"><span class="status-pill status-real">✓ 车型属性 · 真实基础表</span><span class="status-pill status-sim">△ 市场销量 · 模拟数据</span><span class="status-pill status-real">✓ 用户洞察 · 资料分析已接入</span></div>',unsafe_allow_html=True)

def render_kpi_card(label,value,unit,delta,icon):
    st.markdown(f'<div class="kpi-card"><div class="kpi-row"><div><div class="kpi-label">{label}</div><div class="kpi-value">{value} <span style="font-size:16px;">{unit}</span></div><div class="kpi-delta">{delta}</div></div><div class="kpi-icon">{icon}</div></div></div>',unsafe_allow_html=True)

def load_saved_analysis_scenes():
    if not SAVED_SCENES_FILE.exists():
        return {"market":{},"competitor":{}}
    try:
        data=json.loads(SAVED_SCENES_FILE.read_text(encoding="utf-8"))
        return {"market":data.get("market",{}),"competitor":data.get("competitor",{})}
    except (OSError,ValueError,TypeError):
        return {"market":{},"competitor":{}}

def persist_analysis_scenes(data):
    SAVED_SCENES_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

def built_in_analysis_scenes(page_key,target):
    target_brands=unique_list(target.get("matched_rows",pd.DataFrame()).get("品牌",pd.Series(dtype=str))) if target.get("found") else []
    target_series=unique_list(target.get("matched_rows",pd.DataFrame()).get("车系",pd.Series(dtype=str))) if target.get("found") else []
    default_scene={
        "regions":["全国"],
        "prices":target.get("覆盖价格段",[]) or PRICE_SEGMENTS,
        "energies":ENERGY_OPTIONS.copy() if page_key=="competitor" else (target.get("能源形式列表",[]) or ENERGY_OPTIONS.copy()),
        "bodies":target.get("车身形式列表",[]) or BODY_OPTIONS.copy(),
        "brands":target_brands,"series":target_series,
    }
    scenes={"系统｜本品默认口径":default_scene}
    if page_key=="market":
        scenes["系统｜全国 vs 湖北对比"]={**default_scene,"regions":["全国","湖北省"]}
    return scenes

def apply_scene_to_pending(page_key,scene):
    option_map={
        "regions":REGION_OPTIONS,"prices":PRICE_SEGMENTS,"energies":ENERGY_OPTIONS,"bodies":BODY_OPTIONS,
        "brands":brand_options_from_data(),"series":unique_list(car_df["车系"]),
    }
    for field,options in option_map.items():
        values=[item for item in scene.get(field,[]) if item in options]
        field_label={"regions":"地区","prices":"价格段","energies":"能源形式","bodies":"车身形式","brands":"品牌","series":"车系"}.get(field,field)
        st.session_state[f"pending_{field}_{page_key}"]=actual_to_widget(values,options,field_label)

def pending_scene_payload(page_key):
    payload={
        "regions":pending_values(f"pending_regions_{page_key}",REGION_OPTIONS),
        "prices":pending_values(f"pending_prices_{page_key}",PRICE_SEGMENTS),
        "energies":pending_values(f"pending_energies_{page_key}",ENERGY_OPTIONS),
        "bodies":pending_values(f"pending_bodies_{page_key}",BODY_OPTIONS),
    }
    payload["brands"]=pending_values(f"pending_brands_{page_key}",brand_options_from_data())
    payload["series"]=pending_values(f"pending_series_{page_key}",unique_list(car_df["车系"]))
    return payload

def clear_pending_filters(page_key):
    for field in ["brands","series","regions","prices","energies","bodies"]:
        st.session_state[f"pending_{field}_{page_key}"]=[]
    st.session_state[f"analysis_scene_picker_{page_key}"]=[]
    st.session_state.pop(f"analysis_scene_last_{page_key}",None)

def analysis_scene_picker_changed(page_key):
    picker_key=f"analysis_scene_picker_{page_key}"
    selected=st.session_state.get(picker_key,[])
    previous=st.session_state.get(f"analysis_scene_last_{page_key}")
    catalog=st.session_state.get(f"analysis_scene_catalog_{page_key}",{})
    if selected:
        label=selected[0]
        scene=catalog.get(label)
        if scene:
            apply_scene_to_pending(page_key,scene)
            st.session_state[f"analysis_scene_last_{page_key}"]=label
            st.session_state[f"scene_loaded_notice_{page_key}"]=label
    elif previous and previous.startswith("自定义｜"):
        st.session_state[f"confirm_delete_scene_{page_key}"]=previous.split("｜",1)[1]

def open_save_scene_dialog(page_key):
    st.session_state[f"show_save_scene_dialog_{page_key}"]=True

def save_scene_from_dialog(page_key):
    name=st.session_state.get(f"scene_dialog_name_{page_key}","").strip()
    if not name:
        st.session_state[f"scene_dialog_error_{page_key}"]="请输入场景名称。"
        return
    data=load_saved_analysis_scenes()
    data.setdefault(page_key,{})[name]=pending_scene_payload(page_key)
    persist_analysis_scenes(data)
    label=f"自定义｜{name}"
    st.session_state[f"analysis_scene_picker_{page_key}"]=[label]
    st.session_state[f"analysis_scene_last_{page_key}"]=label
    st.session_state[f"show_save_scene_dialog_{page_key}"]=False
    st.session_state.pop(f"scene_dialog_error_{page_key}",None)
    st.session_state[f"scene_saved_notice_{page_key}"]=name

def cancel_save_scene_dialog(page_key):
    st.session_state[f"show_save_scene_dialog_{page_key}"]=False
    st.session_state.pop(f"scene_dialog_error_{page_key}",None)

def delete_saved_scene(page_key,name):
    data=load_saved_analysis_scenes()
    data.get(page_key,{}).pop(name,None)
    persist_analysis_scenes(data)
    st.session_state[f"analysis_scene_picker_{page_key}"]=[]
    st.session_state.pop(f"analysis_scene_last_{page_key}",None)
    st.session_state.pop(f"confirm_delete_scene_{page_key}",None)
    st.session_state[f"scene_deleted_notice_{page_key}"]=name

def cancel_delete_saved_scene(page_key,name):
    label=f"自定义｜{name}"
    st.session_state[f"analysis_scene_picker_{page_key}"]=[label]
    st.session_state[f"analysis_scene_last_{page_key}"]=label
    st.session_state.pop(f"confirm_delete_scene_{page_key}",None)

@st.dialog("保存为自动分析场景")
def render_save_scene_dialog(page_key):
    st.caption("当前地区、价格、能源和车身筛选将作为一个组合保存，之后可从筛选面板快速调用。")
    st.text_input("场景名称",placeholder="例如：华中核心市场",key=f"scene_dialog_name_{page_key}")
    error=st.session_state.get(f"scene_dialog_error_{page_key}")
    if error: st.error(error)
    cancel_col,save_col=st.columns(2)
    cancel_col.button("取消",key=f"cancel_save_scene_{page_key}",use_container_width=True,on_click=cancel_save_scene_dialog,args=(page_key,))
    save_col.button("保存场景",key=f"confirm_save_scene_{page_key}",type="primary",use_container_width=True,on_click=save_scene_from_dialog,args=(page_key,))

@st.dialog("删除自定义场景？")
def render_delete_scene_dialog(page_key,name):
    st.warning(f'确定删除“{name}”吗？删除后无法恢复，但不会改变当前已经应用的分析结果。')
    cancel_col,delete_col=st.columns(2)
    cancel_col.button("取消",key=f"cancel_delete_scene_{page_key}",use_container_width=True,on_click=cancel_delete_saved_scene,args=(page_key,name))
    delete_col.button("确认删除",key=f"confirm_delete_scene_btn_{page_key}",type="primary",use_container_width=True,on_click=delete_saved_scene,args=(page_key,name))

def render_filter_panel(page_key):
    is_competitor=page_key=="competitor"
    normalize_pending_from_applied(page_key,is_competitor)
    panel_title="高级筛选"
    panel_desc=("分析品牌为单选；车系可多选，并以第一个车系作为本品，其余车系作为指定比较对象。地区、价格、能源和车身可多选，用于定义竞争市场。"
                if is_competitor else
                "品牌、车系、价格、能源和车身会相互约束可选项；未选择具体品牌或车系时，将以“自定义分析目标”展示当前筛选结果。")
    st.markdown(
        f'<div class="filter-panel-card"><div class="filter-panel-title">{panel_title}</div>'
        f'<div class="filter-panel-desc">{panel_desc}</div></div>',
        unsafe_allow_html=True,
    )

    raw_brands=pending_values(f"pending_brands_{page_key}",brand_options_from_data())
    raw_series=pending_values(f"pending_series_{page_key}",unique_list(car_df["车系"]))
    raw_prices=pending_values(f"pending_prices_{page_key}",PRICE_SEGMENTS)
    raw_energies=pending_values(f"pending_energies_{page_key}",ENERGY_OPTIONS)
    raw_bodies=pending_values(f"pending_bodies_{page_key}",BODY_OPTIONS)

    brand_options=available_car_options(raw_brands,raw_series,raw_prices,raw_energies,raw_bodies,exclude="品牌")["品牌"]
    series_options=available_car_options(raw_brands,raw_series,raw_prices,raw_energies,raw_bodies,exclude="车系")["车系"]
    price_options=available_car_options(raw_brands,raw_series,raw_prices,raw_energies,raw_bodies,exclude="价格段")["价格段"]
    energy_options=available_car_options(raw_brands,raw_series,raw_prices,raw_energies,raw_bodies,exclude="能源形式")["能源形式"]
    body_options=available_car_options(raw_brands,raw_series,raw_prices,raw_energies,raw_bodies,exclude="车身形式")["车身形式"]
    sanitize_pending(f"pending_regions_{page_key}",REGION_OPTIONS)
    sanitize_pending(f"pending_prices_{page_key}",price_options)
    sanitize_pending(f"pending_energies_{page_key}",energy_options)
    sanitize_pending(f"pending_bodies_{page_key}",body_options)
    sanitize_pending(f"pending_brands_{page_key}",brand_options)
    sanitize_pending(f"pending_series_{page_key}",series_options)

    with st.container(border=True):
        target=target_info(st.session_state.target_query)
        saved_scene_data=load_saved_analysis_scenes()
        custom_scenes=saved_scene_data.get(page_key,{})
        available_scenes={**built_in_analysis_scenes(page_key,target),**{f"自定义｜{name}":scene for name,scene in custom_scenes.items()}}
        st.session_state[f"analysis_scene_catalog_{page_key}"]=available_scenes
        picker_key=f"analysis_scene_picker_{page_key}"
        valid_picker_values=[item for item in st.session_state.get(picker_key,[]) if item in available_scenes]
        if picker_key not in st.session_state:
            st.session_state[picker_key]=[next(iter(available_scenes))]
            st.session_state[f"analysis_scene_last_{page_key}"]=st.session_state[picker_key][0]
        elif valid_picker_values!=st.session_state.get(picker_key,[]):
            st.session_state[picker_key]=valid_picker_values
        st.markdown('<div class="filter-group-label">自动分析场景</div><div class="metric-formula">调用预设或已保存的筛选组合；载入后仍需点击“确定”才会更新分析结果。</div>',unsafe_allow_html=True)
        scene_col,save_action_col=st.columns([3.2,1.45])
        with scene_col:
            st.multiselect("分析场景",list(available_scenes),max_selections=1,key=picker_key,placeholder="点击展开并选择分析场景",label_visibility="collapsed",on_change=analysis_scene_picker_changed,args=(page_key,))
        with save_action_col:
            st.button("保存当前筛选为场景",key=f"save_analysis_scene_{page_key}",use_container_width=True,on_click=open_save_scene_dialog,args=(page_key,))
        loaded_notice=st.session_state.pop(f"scene_loaded_notice_{page_key}",None)
        saved_notice=st.session_state.pop(f"scene_saved_notice_{page_key}",None)
        deleted_notice=st.session_state.pop(f"scene_deleted_notice_{page_key}",None)
        if loaded_notice: st.caption(f'已载入“{loaded_notice}”，请检查下方筛选并点击“确定”。')
        if saved_notice: st.success(f'已保存自定义场景“{saved_notice}”。')
        if deleted_notice: st.success(f'已删除自定义场景“{deleted_notice}”。')
        st.markdown('<div style="height:5px;border-bottom:1px solid rgba(120,190,255,.14);margin-bottom:12px"></div>',unsafe_allow_html=True)

        st.markdown(f'<div class="filter-group-label">{"竞品候选" if is_competitor else "分析对象"}</div>',unsafe_allow_html=True)
        row1_col1,row1_col2=st.columns(2)
        with row1_col1:
            selected_brands=multiselect_dropdown("分析目标 / 对比品牌" if is_competitor else "品牌",brand_options,f"pending_brands_{page_key}",max_selections=1)
        with row1_col2:
            selected_series=multiselect_dropdown("分析目标 / 对比车系" if is_competitor else "车系",series_options,f"pending_series_{page_key}")
        if is_competitor:
            brand_widget=st.session_state.get(f"pending_brands_{page_key}",[])
            series_widget=st.session_state.get(f"pending_series_{page_key}",[])
            selected_candidates=([] if not brand_widget and not series_widget else
                                 ["全部"] if "全部" in brand_widget or "全部" in series_widget else
                                 unique_list(brand_widget+series_widget))
            if selected_candidates:
                candidate_chips="".join(f'<span class="series-mini-chip">{item} ×</span>' for item in selected_candidates)
                st.markdown(f'<div class="filter-selected-row"><b>当前已选</b>{candidate_chips}<span class="filter-selected-count">共 {len(selected_candidates)} 项</span></div>',unsafe_allow_html=True)
        st.markdown('<div class="filter-group-label">市场范围</div>',unsafe_allow_html=True)
        row2_col1,row2_col2,row2_col3,row2_col4=st.columns(4)
        with row2_col1:
            selected_regions=multiselect_dropdown("地区",REGION_OPTIONS,f"pending_regions_{page_key}")
        with row2_col2:
            selected_prices=multiselect_dropdown("价格段",price_options,f"pending_prices_{page_key}")
        with row2_col3:
            selected_energies=multiselect_dropdown("能源形式",energy_options,f"pending_energies_{page_key}")
        with row2_col4:
            selected_bodies=multiselect_dropdown("车身形式",body_options,f"pending_bodies_{page_key}")

        action1,action2=st.columns([1,2])
        with action1:
            st.button("清除所有筛选",key=f"clear_filters_{page_key}",use_container_width=True,on_click=clear_pending_filters,args=(page_key,))
        with action2:
            apply_clicked=st.button("确定",key=f"apply_filters_{page_key}",type="primary",use_container_width=True)

    if st.session_state.get(f"show_save_scene_dialog_{page_key}"):
        render_save_scene_dialog(page_key)
    delete_name=st.session_state.get(f"confirm_delete_scene_{page_key}")
    if delete_name:
        render_delete_scene_dialog(page_key,delete_name)
    if apply_clicked:
        target_selection=None
        keep_competitor_scope=False
        selected_brand_values=pending_values(f"pending_brands_{page_key}",brand_options_from_data())
        selected_series_values=pending_values(f"pending_series_{page_key}",unique_list(car_df["车系"]))
        if is_competitor:
            # A multi-select still needs one explicit analysis target.  Use the
            # first selected series/brand and retain the remaining selections as
            # the comparison scope; never leave an unrelated previous target.
            if selected_series_values:
                target_selection=selected_series_values[0]
                keep_competitor_scope=len(selected_series_values)+len(selected_brand_values)>1
            elif selected_brand_values:
                target_selection=selected_brand_values[0]
                keep_competitor_scope=len(selected_brand_values)>1
        else:
            if len(selected_series_values)==1:
                target_selection=selected_series_values[0]
            elif len(selected_brand_values)==1 and not selected_series_values:
                target_selection=selected_brand_values[0]
            else:
                target_selection="自定义分析目标"
        commit_filter_selection(page_key,is_competitor)
        if target_selection:
            st.session_state.target_query=target_selection
            st.session_state.home_query=target_selection
            if is_competitor and not keep_competitor_scope:
                st.session_state[f"brands_{page_key}"]=[]
                st.session_state[f"series_{page_key}"]=[]
            st.session_state[f"sync_target_{page_key}"]=target_selection
        st.rerun()


def render_target_hero(page_key,target):
    ensure_filters(page_key,target)
    left,right=st.columns([5.1,1.35])
    is_objective_market=page_key=="market" and target.get("query")=="自定义分析目标"
    target_body=str(target.get("车身形式","")).split(" / ")[0]
    icon={"轿车":"🚗","SUV":"🚙","MPV":"🚐"}.get(target_body,"🎯")
    if target.get("is_brand_query"):
        hint=f'<span class="multi-hint">品牌级搜索：初始共命中 {len(target.get("series_breakdown",[]))} 个车系；下方车型清单、指标和图表会随已应用的市场口径同步更新。</span>'
    elif target.get("is_multi"):
        hint='<span class="multi-hint">该价格段涉及多个版本，本次搜索覆盖全版本价格段，您可以通过“高级筛选”修改结果。</span>'
    else:
        hint=""
    with left:
        if is_objective_market:
            st.markdown('<div class="hero-card"><div style="display:flex;align-items:center;gap:22px;"><div class="hero-icon">📊</div><div><div class="hero-label">当前分析模式</div><div class="hero-title">PV市场大盘</div><div class="hero-meta">尚未指定品牌或车系，仅展示当前筛选口径下的市场容量、结构、趋势与机会特征。</div></div></div></div>',unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="hero-card"><div style="display:flex;align-items:center;gap:22px;"><div class="hero-icon">{icon}</div><div><div class="hero-label">当前分析目标</div><div class="hero-title">{target["车系"]}</div><div class="hero-meta">{hint}<br>{target["品牌"]}｜{target["价格展示"]}｜覆盖价格段：{target["覆盖价格段文本"]}<br>能源：{target["能源大类"]}｜车身：{target["车身形式"]}｜级别：{target["级别"]}｜座位：{target["座位数"]}</div></div></div></div>',unsafe_allow_html=True)
    with right:
        st.markdown("<div style='height:10px'></div>",unsafe_allow_html=True)
        edit_key=f"edit_target_{page_key}"
        if st.session_state.get(f"sync_edit_{page_key}")!=st.session_state.target_query:
            st.session_state[edit_key]=st.session_state.target_query; st.session_state[f"sync_edit_{page_key}"]=st.session_state.target_query
        with st.popover("输入分析对象",use_container_width=True):
            st.text_input("输入品牌或车系",key=edit_key,placeholder="例如：奥迪A6L、Model Y、理想L8")
            if st.button("更新结果",key=f"apply_target_{page_key}",use_container_width=True,type="primary"):
                apply_target_change(edit_key,page_key); st.rerun()
        show_key=f"show_filter_{page_key}"
        if show_key not in st.session_state: st.session_state[show_key]=False
        filter_button_label="高级筛选"
        if st.button(f"{filter_button_label} ⌃" if st.session_state[show_key] else f"{filter_button_label} ⌄",key=f"toggle_filter_{page_key}",use_container_width=True):
            st.session_state[show_key]=not st.session_state[show_key]; st.rerun()
    if st.session_state.get(f"show_filter_{page_key}",False):
        render_filter_panel(page_key)
    if target.get("is_brand_query") and target.get("series_breakdown") and page_key!="strategy":
        card_rows=target["matched_rows"].copy()
        applied_brands=st.session_state.get(f"brands_{page_key}",[])
        applied_series=st.session_state.get(f"series_{page_key}",[])
        applied_prices=st.session_state.get(f"prices_{page_key}",[])
        applied_energies=st.session_state.get(f"energies_{page_key}",[])
        applied_bodies=st.session_state.get(f"bodies_{page_key}",[])
        if applied_brands: card_rows=card_rows.loc[card_rows["品牌"].isin(applied_brands)]
        if applied_series: card_rows=card_rows.loc[card_rows["车系"].isin(applied_series)]
        if applied_prices and not card_rows.empty:
            price_mask=card_rows["覆盖价格段"].map(lambda segs: bool(set(segs)&set(applied_prices))).astype(bool)
            card_rows=card_rows.loc[price_mask]
        if applied_energies: card_rows=card_rows.loc[card_rows["能源形式"].isin(applied_energies)]
        if applied_bodies: card_rows=card_rows.loc[card_rows["车身形式"].isin(applied_bodies)]
        cards=sorted(build_series_breakdown(card_rows),key=lambda r:r["近月销量"],reverse=True) if len(card_rows) else []
        module_name={"market":"市场大盘","competitor":"竞品格局","user":"用户洞察"}.get(page_key,"市场大盘")
        if page_key in {"competitor","user"}:
            chip_text="".join(
                f'<a class="series-chip-link" href="?target={html.escape(str(card["车系"]),quote=True)}&module={module_name}" target="_self"><span class="series-mini-chip">{html.escape(str(card["车系"]))}</span></a>'
                for card in cards
            )
            st.markdown(
                f'<div class="series-scope-shell"><div class="series-scope-head">「{html.escape(str(target["query"]))}」当前筛选范围内车系 <span class="brand-series-count">共 {len(cards)} 个</span></div>'
                f'<div class="series-mini-row" style="flex-wrap:wrap;overflow:visible">{chip_text}</div></div>',unsafe_allow_html=True,
            )
        else:
            card_html="".join(
                f'<a class="series-click-card" href="?target={html.escape(str(c["车系"]),quote=True)}&module={module_name}" target="_self">'
                f'<b>{html.escape(str(c["车系"]))}</b><em>{html.escape(str(c["价格展示"]))}</em><span>覆盖价格段：{html.escape(str(c["覆盖价格段"]))}<br>'
                f'能源：{html.escape(str(c["能源形式"]))}｜车身：{html.escape(str(c["车身形式"]))}<br>模拟近月销量：{c["近月销量"]:,} 辆</span></a>' for c in cards
            )
            if cards:
                st.markdown(f'<div class="series-scope-shell"><div class="series-scope-head">「{html.escape(str(target["query"]))}」当前筛选范围内车系 <span class="brand-series-count">共 {len(cards)} 个</span></div><div class="series-click-grid">{card_html}</div></div>',unsafe_allow_html=True)
            else:
                st.warning("当前筛选范围内没有可覆盖的品牌车系，请重新使用高级筛选。")
    return (
        st.session_state.get(f"brands_{page_key}",[]),
        st.session_state.get(f"series_{page_key}",[]),
        st.session_state.get(f"regions_{page_key}",["全国"]),
        st.session_state.get(f"prices_{page_key}",target.get("覆盖价格段",[])),
        st.session_state.get(f"energies_{page_key}",ENERGY_OPTIONS),
        st.session_state.get(f"bodies_{page_key}",BODY_OPTIONS)
    )

def plotly_layout(fig,height=380):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",height=height,font_color="#F3F7FF",legend_title_text="",legend=dict(font=dict(color="#FFFFFF",size=12),title_font=dict(color="#FFFFFF")),margin=dict(l=24,r=24,t=12,b=24),xaxis=dict(showgrid=False,tickfont=dict(color="#AFC3DC"),title_font=dict(color="#AFC3DC"),categoryorder="array",categoryarray=PERIOD_LABELS,tickangle=-35),yaxis=dict(gridcolor="rgba(255,255,255,0.12)",tickfont=dict(color="#AFC3DC"),title_font=dict(color="#AFC3DC")))
    return fig

def chart_sales_scale(values):
    max_value=float(pd.Series(values).fillna(0).max()) if len(values) else 0
    if max_value>=10000: return 10000.0,"万辆"
    if max_value>=1000: return 1000.0,"千辆"
    return 1.0,"辆"

def render_objective_market_dashboard(market_scope,regions):
    """Render a target-free market view when no brand or series is selected."""
    total=float(market_scope["销量"].sum())
    monthly=market_scope.groupby("月份序号")["销量"].sum()
    recent=float(monthly.reindex(RECENT_PERIOD_INDEXES,fill_value=0).mean())
    previous=float(monthly.reindex(PREVIOUS_PERIOD_INDEXES,fill_value=0).mean())
    growth=safe_change(recent,previous)
    price_total=market_scope.groupby("价格段")["销量"].sum().sort_values(ascending=False)
    top_price=str(price_total.index[0]) if len(price_total) else "暂无"
    top_price_share=float(price_total.iloc[0]/price_total.sum()) if len(price_total) and price_total.sum() else 0
    render_help_title("全国核心指标","展示当前筛选口径下的近12个月市场容量、近3个月月均销量、主力价格段与观察地区。")
    st.markdown(
        '<div class="objective-kpi-grid">'
        f'<div class="objective-kpi"><div class="objective-kpi-label">近12月市场容量</div><div class="objective-kpi-value">{total:,.0f} 辆</div><div class="objective-kpi-delta">滚动12个月</div></div>'
        f'<div class="objective-kpi"><div class="objective-kpi-label">近3月月均销量</div><div class="objective-kpi-value">{recent:,.0f} 辆</div><div class="objective-kpi-delta">较前3个月 {growth:+.1%}</div></div>'
        f'<div class="objective-kpi"><div class="objective-kpi-label">主力价格段</div><div class="objective-kpi-value">{html.escape(top_price)}</div><div class="objective-kpi-delta">占市场 {top_price_share:.1%}</div></div>'
        f'<div class="objective-kpi"><div class="objective-kpi-label">当前观察地区</div><div class="objective-kpi-value">{html.escape(format_options(regions))}</div><div class="objective-kpi-delta">独立口径展示</div></div></div>',
        unsafe_allow_html=True,
    )

    chart_specs=[("市场走势",None,"当前市场容量及月度变化"),("价格结构","价格段","主力价格带与结构变化"),("能源形式","能源大类","不同能源路线的市场结构"),("车身结构","车身形式","车身类型的需求分布")]
    colors=["#5975E8","#E06B52","#45B893","#E6AA38","#8A65D6","#55A9D9","#D35D91","#8BB650"]
    for title,dimension,insight_title in chart_specs:
        st.markdown(f"### ◈ {title}")
        with st.container(border=True):
            display_cols=st.columns(2 if len(regions)>1 else 1)
            for index,region in enumerate(regions):
                region_df=market_scope[market_scope["地区"]==region].copy()
                with display_cols[index%len(display_cols)]:
                    if dimension is None:
                        plot=region_df.groupby(["月份序号","月份"],as_index=False)["销量"].sum()
                        scale,unit=chart_sales_scale(plot["销量"])
                        plot["展示销量"]=plot["销量"]/scale
                        fig=px.bar(plot,x="月份",y="展示销量",color_discrete_sequence=["#5D70E5"],title=f"{region}｜市场销量")
                        fig.update_yaxes(title=f"市场销量（{unit}）")
                    else:
                        plot=region_df.groupby(["月份序号","月份",dimension],as_index=False)["销量"].sum()
                        scale,unit=chart_sales_scale(plot["销量"])
                        plot["展示销量"]=plot["销量"]/scale
                        fig=px.bar(plot,x="月份",y="展示销量",color=dimension,barmode="stack",color_discrete_sequence=colors,title=f"{region}｜{title}")
                        fig.update_yaxes(title=f"销量（{unit}）")
                    fig=plotly_layout(fig,360)
                    fig.update_layout(title=dict(font=dict(color="#F5FAFF",size=15),x=.01),legend=dict(orientation="h",y=-.34,x=.5,xanchor="center",font=dict(size=12,color="#F5FAFF")),margin=dict(l=30,r=15,t=55,b=105))
                    render_responsive_chart(fig,use_container_width=True,config={"displayModeBar":False})
            if dimension is None:
                finding=f"近3月月均销量较此前3个月 {growth:+.1%}，当前市场处于{'扩张' if growth>0.03 else '收缩' if growth<-.03 else '平稳'}阶段。"
            else:
                totals=market_scope.groupby(dimension)["销量"].sum().sort_values(ascending=False)
                lead=str(totals.index[0]) if len(totals) else "暂无"
                share=float(totals.iloc[0]/totals.sum()) if len(totals) and totals.sum() else 0
                finding=f"{lead}是当前主导结构，占该口径市场 {share:.1%}；应继续观察其份额变化及其他结构的增量速度。"
            st.markdown(f'<div class="ai-card"><b>机会点｜{insight_title}</b><br>{finding}</div>',unsafe_allow_html=True)

def cancel_return_home():
    st.session_state["confirm_return_home"]=False

def confirm_return_home():
    st.session_state["confirm_return_home"]=False
    set_page("首页")

@st.dialog("确认返回首页？")
def render_return_home_dialog():
    st.markdown("返回首页后，当前页面尚未确认的筛选和角色设置可能不会保留。是否继续？")
    cancel_col,confirm_col=st.columns(2)
    if cancel_col.button("取消",use_container_width=True,key="cancel_return_home"):
        cancel_return_home(); st.rerun(scope="app")
    if confirm_col.button("确认返回",type="primary",use_container_width=True,key="confirm_return_home_btn"):
        confirm_return_home(); st.rerun(scope="app")

def has_explicit_analysis_target():
    query=str(st.session_state.get("target_query","")).strip()
    return bool(query and query!="自定义分析目标" and target_info(query).get("found"))

@st.dialog("请先选择分析对象")
def render_target_required_dialog():
    st.markdown("竞品格局、用户洞察和策略生成需要明确的品牌或车系。请先输入分析对象，或前往市场大盘通过高级筛选选择品牌/车系。")
    home_col,market_col=st.columns(2)
    if home_col.button("返回首页输入",use_container_width=True,key="missing_target_home"):
        set_page("首页"); st.rerun(scope="app")
    if market_col.button("前往市场大盘",type="primary",use_container_width=True,key="missing_target_market"):
        set_page("市场大盘"); st.rerun(scope="app")

def render_custom_sidebar():
    st.markdown('<div class="side-card"><div class="side-title">🐑 小羊分析助手</div><div class="side-desc">PV市场洞察与新品GTM策略助手</div></div><div class="side-section">功能导航</div>',unsafe_allow_html=True)
    for page,icon in [("市场大盘","📈"),("竞品格局","▦"),("用户洞察","👥"),("策略生成","🎯")]:
        if st.session_state.current_page==page:
            st.markdown(f'<div class="active-nav"><div>{icon}</div><div><b>{page}</b></div></div>',unsafe_allow_html=True)
        else:
            if st.button(f"{icon}  {page}",key=f"side_{page}",use_container_width=True):
                set_page(page); st.rerun()
    if st.button("⌂ 返回首页",key="side_home",use_container_width=True):
        st.session_state["confirm_return_home"]=True
    if st.session_state.get("confirm_return_home"):
        render_return_home_dialog()

def safe_change(new_value,old_value):
    return (new_value/old_value-1) if old_value else 0.0

def share_for_groups(df,groups,column,month):
    month_df=df[df["月份序号"]==month]
    total=month_df["销量"].sum()
    selected=month_df[month_df[column].isin(groups)]["销量"].sum()
    return selected/total if total else 0.0

def render_market_conclusion(market_scope,energy_market_scope,body_market_scope,target_scope,regions,prices,target_energy_groups,target_bodies):
    market_month=market_scope.groupby("月份序号",as_index=False)["销量"].sum()
    target_month=target_scope.groupby("月份序号",as_index=False)["销量"].sum().rename(columns={"销量":"目标销量"})
    monthly=market_month.merge(target_month,on="月份序号",how="left").fillna({"目标销量":0})
    monthly["目标份额"]=monthly["目标销量"]/monthly["销量"].replace(0,np.nan)
    first_avg=monthly[monthly["月份序号"].isin(PREVIOUS_PERIOD_INDEXES)]["销量"].mean()
    recent_avg=monthly[monthly["月份序号"].isin(RECENT_PERIOD_INDEXES)]["销量"].mean()
    market_growth=safe_change(recent_avg,first_avg)
    share_start=float(monthly.loc[monthly["月份序号"]==1,"目标份额"].iloc[0]) if (monthly["月份序号"]==1).any() else 0
    share_end=float(monthly.loc[monthly["月份序号"]==LAST_PERIOD_INDEX,"目标份额"].iloc[0]) if (monthly["月份序号"]==LAST_PERIOD_INDEX).any() else 0
    share_change=(share_end-share_start)*100

    price_totals=market_scope.groupby("价格段",as_index=False)["销量"].sum().sort_values("销量",ascending=False)
    leading_price=str(price_totals.iloc[0]["价格段"]) if len(price_totals) else "待判断"
    leading_price_share=float(price_totals.iloc[0]["销量"]/price_totals["销量"].sum()) if len(price_totals) and price_totals["销量"].sum() else 0
    energy_start=share_for_groups(energy_market_scope,target_energy_groups,"能源大类",1)
    energy_end=share_for_groups(energy_market_scope,target_energy_groups,"能源大类",LAST_PERIOD_INDEX)
    body_start=share_for_groups(body_market_scope,target_bodies,"车身形式",1)
    body_end=share_for_groups(body_market_scope,target_bodies,"车身形式",LAST_PERIOD_INDEX)

    market_direction="扩张" if market_growth>.03 else "收缩" if market_growth<-.03 else "基本稳定"
    share_direction="提升" if share_change>.05 else "回落" if share_change<-.05 else "基本稳定"
    energy_delta=(energy_end-energy_start)*100
    body_delta=(body_end-body_start)*100
    st.markdown("### 市场机会研判")
    st.markdown(
        f"""
        <div class="insight-grid">
          <div class="insight-panel">
            <div class="insight-kicker">01 · 市场容量与动能</div>
            <div class="insight-title">{format_options(regions)}细分市场呈{market_direction}</div>
            <div class="insight-text">近三个月月均模拟销量较首三个月
            <span class="insight-number">{market_growth:+.1%}</span>。当前观察口径覆盖
            <b>{format_options(prices)}</b>，应重点判断当前变化来自持续需求转向，还是短期季节性波动。</div>
          </div>
          <div class="insight-panel">
            <div class="insight-kicker">02 · 价格带承接能力</div>
            <div class="insight-title">{leading_price}是当前主力价格带</div>
            <div class="insight-text">该价格带贡献当前筛选市场模拟销量的
            <span class="insight-number">{leading_price_share:.1%}</span>。目标产品若落在主力价格带内部，更利于承接现有需求；若处于边缘区间，则需通过配置或权益解释价格跨档价值。</div>
          </div>
          <div class="insight-panel">
            <div class="insight-kicker">03 · 能源与车身结构</div>
            <div class="insight-title">目标结构的渗透方向需要分层判断</div>
            <div class="insight-text">目标能源 <b>{format_options(target_energy_groups,"待判断")}</b> 市场占比由
            <span class="insight-number">{energy_start:.1%}</span> 变为 <span class="insight-number">{energy_end:.1%}</span>（{energy_delta:+.2f}pct）；
            目标车身 <b>{format_options(target_bodies,"待判断")}</b> 由 {body_start:.1%} 变为 {body_end:.1%}（{body_delta:+.2f}pct）。结构扩张意味着增量承接，结构回落则需要更强的差异化理由。</div>
          </div>
          <div class="insight-panel">
            <div class="insight-kicker">04 · 目标车型竞争位置</div>
            <div class="insight-title">目标车型份额{share_direction}</div>
            <div class="insight-text">目标车型模拟份额从 <span class="insight-number">{share_start:.2%}</span>
            变为 <span class="insight-number">{share_end:.2%}</span>，变化 <span class="insight-number">{share_change:+.2f}pct</span>。
            应结合竞品候选池进一步判断，是目标车型自身增长，还是细分市场分母变化带来的被动份额波动。</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_region_chart(market_scope,target_scope,regions):
    market_month=market_scope.groupby(["月份","月份序号","地区"],as_index=False)["销量"].sum().sort_values("月份序号")
    target_month=target_scope.groupby(["月份","月份序号","地区"],as_index=False)["销量"].sum().rename(columns={"销量":"目标销量"}).sort_values("月份序号")
    chart_df=market_month.merge(target_month,on=["月份","月份序号","地区"],how="left")
    chart_df["目标销量"]=chart_df["目标销量"].fillna(0)
    chart_df["目标车型市占率"]=np.where(chart_df["销量"]>0,chart_df["目标销量"]/chart_df["销量"]*100,0)
    divisor,unit=chart_sales_scale(chart_df["销量"])
    chart_df["市场销量展示"]=chart_df["销量"]/divisor
    fig=make_subplots(specs=[[{"secondary_y":True}]])
    for region in regions:
        sub=chart_df[chart_df["地区"]==region].sort_values("月份序号")
        if sub.empty: continue
        fig.add_trace(go.Bar(x=sub["月份"],y=sub["市场销量展示"],name=f"{region}｜市场整体",opacity=.82,hovertemplate=f"%{{x}}<br>市场销量：%{{y:,.2f}} {unit}<extra></extra>"),secondary_y=False)
        fig.add_trace(go.Scatter(x=sub["月份"],y=sub["目标车型市占率"],name=f"{region}｜目标车型市占率",mode="lines+markers",line=dict(width=3),marker=dict(size=7),hovertemplate="%{x}<br>目标车型市占率：%{y:.2f}%<extra></extra>"),secondary_y=True)
    fig.update_layout(barmode="group",template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",height=380,font_color="#F3F7FF",legend_title_text="",legend=dict(font=dict(color="#FFFFFF",size=12),title_font=dict(color="#FFFFFF")),margin=dict(l=24,r=24,t=12,b=24))
    fig.update_xaxes(showgrid=False,tickfont=dict(color="#AFC3DC"),title_font=dict(color="#AFC3DC"),categoryorder="array",categoryarray=PERIOD_LABELS,title_text="月份",tickangle=-35)
    fig.update_yaxes(title_text=f"市场销量（{unit}）",tickformat=",.2f",gridcolor="rgba(255,255,255,0.12)",zeroline=False,tickfont=dict(color="#AFC3DC"),title_font=dict(color="#AFC3DC"),secondary_y=False)
    fig.update_yaxes(title_text="目标车型市占率",ticksuffix="%",showgrid=False,zeroline=False,tickfont=dict(color="#AFC3DC"),title_font=dict(color="#AFC3DC"),secondary_y=True)
    return fig

def render_structure_chart(market_scope,target_scope,structure_column,target_groups,display_column):
    market_trend=market_scope.groupby(["月份","月份序号",structure_column],as_index=False)["销量"].sum().sort_values("月份序号")
    month_axis=pd.DataFrame({"月份序号":[item["月份序号"] for item in REPORTING_MONTHS],"月份":PERIOD_LABELS})
    divisor,unit=chart_sales_scale(market_trend["销量"])
    market_trend["销量展示"]=market_trend["销量"]/divisor
    fig=go.Figure()
    preferred_order=ENERGY_GROUP_OPTIONS if structure_column=="能源大类" else BODY_OPTIONS
    category_order=[category for category in preferred_order if category in set(market_trend[structure_column])]
    structure_colors={
        "ICE":("#173F73","rgba(23,63,115,.82)"),
        "BEV":("#3E6FA6","rgba(62,111,166,.78)"),
        "PHEV":("#7EA3C8","rgba(126,163,200,.72)"),
        "轿车":("#173F73","rgba(23,63,115,.82)"),
        "SUV":("#4E7EAF","rgba(78,126,175,.76)"),
        "MPV":("#9BB7D3","rgba(155,183,211,.68)"),
    }
    market_pivot=(
        market_trend.pivot_table(index=["月份序号","月份"],columns=structure_column,values="销量",aggfunc="sum",fill_value=0)
        .reset_index()
    )
    market_pivot=month_axis.merge(market_pivot.drop(columns=["月份"],errors="ignore"),on="月份序号",how="left").fillna(0).sort_values("月份序号")
    for category in category_order:
        sub=market_trend[market_trend[structure_column]==category].sort_values("月份序号")
        line_color,fill_color=structure_colors.get(category,("#527FAC","rgba(82,127,172,.72)"))
        fig.add_trace(go.Scatter(x=sub["月份"],y=sub["销量展示"],name=f"{category}｜市场总量",mode="lines",stackgroup="market",line=dict(width=1.8,color=line_color),fillcolor=fill_color,hovertemplate=f"%{{x}}<br>{category}市场销量：%{{y:,.2f}} {unit}<extra></extra>"))

    target_by_structure=(
        target_scope.groupby(["月份序号",structure_column],as_index=False)["销量"].sum()
        if structure_column in target_scope.columns else pd.DataFrame()
    )
    cumulative_lower=np.zeros(len(month_axis))
    for category in category_order:
        category_market=pd.to_numeric(market_pivot.get(category,pd.Series(np.zeros(len(month_axis)))),errors="coerce").fillna(0).to_numpy()
        target_values=np.zeros(len(month_axis))
        if not target_by_structure.empty:
            category_target=target_by_structure[target_by_structure[structure_column]==category][["月份序号","销量"]]
            aligned=month_axis[["月份序号"]].merge(category_target,on="月份序号",how="left").fillna({"销量":0})
            target_values=np.minimum(aligned["销量"].to_numpy(),category_market)
        if target_values.sum()>0:
            lower_display=cumulative_lower/divisor
            upper_display=(cumulative_lower+target_values)/divisor
            fig.add_trace(go.Scatter(x=month_axis["月份"],y=lower_display,mode="lines",line=dict(width=0,color="rgba(0,0,0,0)"),showlegend=False,hoverinfo="skip"))
            fig.add_trace(go.Scatter(
                x=month_axis["月份"],y=upper_display,
                name=f"目标车型（{category}）",mode="lines",fill="tonexty",
                line=dict(width=2.8,color="#EAF4FF",dash="dot"),fillcolor="rgba(225,239,255,.22)",
                hovertemplate=f"%{{x}}<br>目标车型销量：%{{customdata:,.0f}} 辆<extra></extra>",
                customdata=target_values,
            ))
        cumulative_lower+=category_market
    fig=plotly_layout(fig,390)
    fig.update_layout(legend=dict(orientation="h",x=.5,xanchor="center",y=-.30,font=dict(color="#FFFFFF",size=12)),margin=dict(l=30,r=20,t=18,b=105))
    fig.update_yaxes(title_text=f"市场及目标车型销量（{unit}）",tickformat=",.2f")
    return fig

def render_price_chart(market_scope,prices):
    price_trend=market_scope.groupby(["月份","月份序号","价格段"],as_index=False)["销量"].sum().sort_values("月份序号")
    divisor,unit=chart_sales_scale(price_trend["销量"])
    price_trend["销量展示"]=price_trend["销量"]/divisor
    selected_order=[p for p in PRICE_SEGMENTS if p in set(price_trend["价格段"])]
    price_palette=["#284B8F","#3C68B1","#5C85C6","#82A5D5","#A8C0E2","#C8D7EC","#DCE6F4","#8AA0BE","#647995","#465A73","#2D4058"]
    color_map={segment:price_palette[index%len(price_palette)] for index,segment in enumerate(PRICE_SEGMENTS)}
    fig=px.bar(price_trend,x="月份",y="销量展示",color="价格段",barmode="stack",template="plotly_dark",color_discrete_map=color_map,category_orders={"月份":PERIOD_LABELS,"价格段":selected_order},labels={"销量展示":f"销量（{unit}）"})
    fig.update_traces(hovertemplate=f"%{{x}}<br>销量：%{{y:,.2f}} {unit}<extra></extra>")
    fig.update_yaxes(title_text=f"销量（{unit}）",tickformat=",.2f")
    return plotly_layout(fig,360)

def region_metrics(market_scope,target_scope):
    market_month=market_scope.groupby("月份序号",as_index=False)["销量"].sum()
    target_month=target_scope.groupby("月份序号",as_index=False)["销量"].sum().rename(columns={"销量":"目标销量"})
    monthly=market_month.merge(target_month,on="月份序号",how="left").fillna({"目标销量":0})
    total=float(monthly["销量"].sum())
    target_total=float(monthly["目标销量"].sum())
    latest=float(monthly.loc[monthly["月份序号"]==LAST_PERIOD_INDEX,"目标销量"].sum())
    latest_market=float(monthly.loc[monthly["月份序号"]==LAST_PERIOD_INDEX,"销量"].sum())
    latest_share=latest/latest_market if latest_market else 0
    last12_indexes=[item["月份序号"] for item in REPORTING_MONTHS[-12:]]
    last12_market=float(monthly[monthly["月份序号"].isin(last12_indexes)]["销量"].sum())
    first_avg=float(monthly[monthly["月份序号"].isin(PREVIOUS_PERIOD_INDEXES)]["销量"].mean())
    recent_avg=float(monthly[monthly["月份序号"].isin(RECENT_PERIOD_INDEXES)]["销量"].mean())
    growth=safe_change(recent_avg,first_avg)
    share=target_total/total if total else 0
    price_totals=market_scope.groupby("价格段",as_index=False)["销量"].sum().sort_values("销量",ascending=False)
    leading_price=str(price_totals.iloc[0]["价格段"]) if len(price_totals) else "待判断"
    return {"market_total":total,"target_total":target_total,"latest":latest,"latest_market":latest_market,
            "latest_share":latest_share,"last12_market":last12_market,"recent_avg":recent_avg,
            "growth":growth,"share":share,"leading_price":leading_price}

def render_region_kpis(region,market_scope,target_scope):
    metrics=region_metrics(market_scope,target_scope)
    render_help_title(f"{region}核心指标",f"当前口径按{region}独立计算；目标对象市占率为目标对象当月销量除以同地区、同筛选口径的市场当月销量。")
    k1,k2,k3,k4=st.columns(4)
    with k1: render_kpi_card("近12月细分市场容量",f"{metrics['last12_market']:,.0f}","辆","滚动12个月","📊")
    with k2: render_kpi_card("近3月市场月均销量",f"{metrics['recent_avg']:,.0f}","辆",f"较此前3个月 {metrics['growth']:+.1%}","↗")
    with k3: render_kpi_card("目标对象近月销量",f"{metrics['latest']:,.0f}","辆",PERIOD_LABELS[-1],"📍")
    with k4: render_kpi_card("目标对象近月市占率",f"{metrics['latest_share']:.2%}","",f"{region}｜{PERIOD_LABELS[-1]}","◔")

def render_multi_region_kpi_table(regions,scope_map):
    cards=[]
    benchmark="全国" if "全国" in regions else regions[0]
    base_metrics=region_metrics(*scope_map[benchmark])
    for region in regions:
        market_scope,target_scope=scope_map[region]
        metrics=region_metrics(market_scope,target_scope)
        if region==benchmark:
            comparison_note=f'<div class="region-compare-note">对照基准</div>'
        else:
            capacity_ratio=metrics["last12_market"]/base_metrics["last12_market"] if base_metrics["last12_market"] else 0
            sales_ratio=metrics["latest"]/base_metrics["latest"] if base_metrics["latest"] else 0
            share_gap=(metrics["latest_share"]-base_metrics["latest_share"])*100
            comparison_note=(f'<div class="region-compare-note">市场容量占{benchmark} <b>{capacity_ratio:.1%}</b>｜'
                             f'目标销量贡献 <b>{sales_ratio:.1%}</b>｜份额差 <b>{share_gap:+.2f}pct</b></div>')
        cards.append(f'''<div class="region-compare-card"><div class="region-compare-name">{region}</div><div class="region-metric-grid">
        <div class="region-metric"><div class="region-metric-label">近12月市场容量</div><div class="region-metric-value">{metrics["last12_market"]:,.0f} 辆</div></div>
        <div class="region-metric"><div class="region-metric-label">近3月月均销量</div><div class="region-metric-value">{metrics["recent_avg"]:,.0f} 辆</div></div>
        <div class="region-metric"><div class="region-metric-label">目标近月销量</div><div class="region-metric-value region-metric-accent">{metrics["latest"]:,.0f} 辆</div></div>
        <div class="region-metric"><div class="region-metric-label">目标近月份额</div><div class="region-metric-value region-metric-accent">{metrics["latest_share"]:.2%}</div></div>
        </div>{comparison_note}</div>''')
    st.markdown('<div class="competitor-section-title">地区核心指标对比</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="region-compare-grid">{"".join(cards)}</div>',unsafe_allow_html=True)

def render_region_chart_grid(regions,scope_map,chart_kind,prices,target_energy_groups,target_bodies):
    for start in range(0,len(regions),2):
        chunk=regions[start:start+2]
        columns=st.columns(len(chunk))
        for column,region in zip(columns,chunk):
            market_scope,target_scope=scope_map[region]
            with column:
                if chart_kind=="market":
                    title=f"{region}市场销量与目标对象市占率"
                    fig=render_region_chart(market_scope,target_scope,[region])
                elif chart_kind=="price":
                    title=f"{region}｜{title_prefix(prices,'全部价格段')}价格段趋势"
                    fig=render_price_chart(market_scope,prices)
                elif chart_kind=="energy":
                    title=f"{region}能源结构与目标车型销量"
                    structure_market=filter_market_data(regions=[region],prices=prices,energy_groups=None,bodies=target_bodies)
                    fig=render_structure_chart(structure_market,target_scope,"能源大类",target_energy_groups,"能源结构")
                else:
                    title=f"{region}车身结构与目标车型销量"
                    structure_market=filter_market_data(regions=[region],prices=prices,energy_groups=target_energy_groups,bodies=None)
                    fig=render_structure_chart(structure_market,target_scope,"车身形式",target_bodies,"车身结构")
                note=(f"堆叠柱展示{region}当前筛选范围内各价格段的月度销量结构。"
                      if chart_kind=="price" else
                      f"市场结构与目标车型使用同一销量坐标；目标车型面积嵌在其所属{('能源形式' if chart_kind=='energy' else '车身结构')}市场内部。"
                      if chart_kind in ["energy","body"] else
                      f"目标对象市占率 = 目标对象当月销量 ÷ {region}当前筛选市场当月销量。")
                st.markdown(f'<div class="module-chart-head"><div class="module-chart-title">{title}</div><div class="module-chart-note">{note}</div></div>',unsafe_allow_html=True)
                render_responsive_chart(fig,use_container_width=True)

def render_module_region_conclusion(regions,scope_map,chart_kind,structure_scope_map=None):
    if not regions:
        return
    benchmark="全国" if "全国" in regions else regions[0]
    analysis_scope_map=structure_scope_map if chart_kind in ["energy","body"] and structure_scope_map else scope_map
    base_market,base_target=analysis_scope_map[benchmark]
    labels={"market":"市场容量","price":"价格结构","energy":"能源结构","body":"车身结构"}
    structure_column={"price":"价格段","energy":"能源大类","body":"车身形式"}.get(chart_kind)
    if len(regions)==1:
        metrics=region_metrics(base_market,base_target)
        if chart_kind=="market":
            direction="扩张" if metrics["growth"]>0 else "收缩"
            reason=("需求释放与细分结构扩容共同推高近期容量。" if metrics["growth"]>0
                    else "需求进入存量争夺期，新增客源和自然增长空间收窄。")
            strategy=("以增量承接为主，优先扩大有效触点并强化主销配置。" if metrics["growth"]>0
                      else "以份额防守和竞品替代为主，减少泛化投放。")
            action=("加码高贡献渠道，围绕近月主销人群设置试驾和转化专项。" if metrics["growth"]>0
                    else "锁定CR3竞品客群，强化置换权益、价值对比与核心城市转化。")
            detail=(f'<b>现象：</b>近三月市场变化 {metrics["growth"]:+.1%}，处于{direction}阶段；目标累计份额 {metrics["share"]:.2%}。<br>'
                    f'<b>原因：</b>{reason}<br><b>策略：</b>{strategy}<br><b>动作：</b>{action}')
        else:
            totals=base_market.groupby(structure_column)["销量"].sum().sort_values(ascending=False)
            leading=str(totals.index[0]) if len(totals) else "待判断"
            leading_share=float(totals.iloc[0]/totals.sum()) if totals.sum() else 0
            target_month=base_target.groupby("月份序号")["销量"].sum()
            target_first=target_month.reindex(PREVIOUS_PERIOD_INDEXES).mean()
            target_recent=target_month.reindex(RECENT_PERIOD_INDEXES).mean()
            target_growth=safe_change(target_recent,target_first)
            reason={"price":"需求与供给正在主力价格带形成规模聚集。","energy":"补能条件、使用成本与消费者接受度共同塑造能源选择。","body":"家庭结构、空间需求和日常使用场景决定车身偏好。"}[chart_kind]
            strategy={"price":"围绕主力价格带建立清晰价值锚点，并控制跨价格档解释成本。","energy":"根据目标能源路线的顺逆风决定增量承接或用户教育优先级。","body":"围绕主流车身需求建立产品卖点和场景表达。"}[chart_kind]
            action={"price":"对齐主力竞品成交价，配置限时权益并验证上下价格档转化。","energy":"强化补能、能耗和全周期成本对比，并匹配相应渠道体验。","body":"集中表达空间、乘坐与家庭出行价值，针对主销场景组织体验活动。"}[chart_kind]
            detail=(f'<b>现象：</b>{leading}贡献 {leading_share:.1%}，为当前主导结构；目标近三月销量变化 {target_growth:+.1%}。<br>'
                    f'<b>原因：</b>{reason}<br><b>策略：</b>{strategy}<br><b>动作：</b>{action}')
        st.markdown(
            f'<div class="opportunity-callout"><div class="insight-kicker">{benchmark}｜{labels[chart_kind]}</div>'
            f'<div class="opportunity-title">机会点</div><div class="opportunity-text">{detail}</div></div>',
            unsafe_allow_html=True,
        )
        return
    panels=[]
    for region in [r for r in regions if r!=benchmark]:
        region_market,region_target=analysis_scope_map[region]
        base_metrics=region_metrics(base_market,base_target)
        current_metrics=region_metrics(region_market,region_target)
        if chart_kind=="market":
            growth_gap=(current_metrics["growth"]-base_metrics["growth"])*100
            share_gap=(current_metrics["share"]-base_metrics["share"])*100
            judgment=(f"区域市场增长与目标渗透均领先{benchmark}，可优先用于区域样板和增量验证。"
                      if growth_gap>0 and share_gap>0 else
                      f"区域市场增长快于{benchmark}，但目标车型份额仍低于{benchmark}，应优先检查渠道覆盖、认知和转化效率。"
                      if growth_gap>0 else
                      f"目标车型份额高于{benchmark}，但区域市场增长慢于{benchmark}，更适合存量竞争与精准人群运营。"
                      if share_gap>0 else
                      f"区域市场增长和目标车型份额均低于{benchmark}，建议先聚焦核心城市、小范围验证后再扩大投入。")
            if growth_gap>0 and share_gap>0:
                interpretation=f'该地区近三个月市场增速较{benchmark}高 {growth_gap:.2f}pct，且目标车型市占率高 {share_gap:.2f}pct，说明区域需求和本品销售承接均相对更强。'
            elif growth_gap>0:
                interpretation=f'该地区近三个月市场增速较{benchmark}高 {growth_gap:.2f}pct，但目标车型市占率低 {abs(share_gap):.2f}pct；市场需求并不弱，差距更可能出现在品牌认知、门店覆盖、线索转化或竞品拦截环节，仍需结合渠道数据验证。'
            elif share_gap>0:
                interpretation=f'该地区近三个月市场增速较{benchmark}低 {abs(growth_gap):.2f}pct，但目标车型市占率高 {share_gap:.2f}pct；本品相对竞争力较好，但整体市场需求偏弱，新增投入应更重视存量置换与精准获客。'
            else:
                interpretation=f'该地区近三个月市场增速较{benchmark}低 {abs(growth_gap):.2f}pct，目标车型市占率也低 {abs(share_gap):.2f}pct；这表示区域总需求和本品相对表现同时偏弱，可能涉及区域消费需求、门店覆盖、线索转化或竞品分流，需结合门店与线索数据进一步验证。'
            strategy="优先建设区域样板并放大优势。" if growth_gap>0 and share_gap>0 else "先补齐渠道与转化短板，再决定是否扩大投入。"
            action="聚焦高贡献城市复制主销渠道打法。" if share_gap>0 else "核查门店覆盖、线索转化和竞品置换流失，设置区域专项权益。"
            detail=(f'<b>对比结果：</b>近三个月市场增速较{benchmark} {growth_gap:+.2f}pct，目标车型市占率较{benchmark} {share_gap:+.2f}pct。<br>'
                    f'<b>数据含义：</b>{interpretation}<br><b>策略：</b>{strategy}<br><b>动作：</b>{action}')
        else:
            base_mix=base_market.groupby(structure_column)["销量"].sum()
            current_mix=region_market.groupby(structure_column)["销量"].sum()
            base_share=(base_mix/base_mix.sum()).to_dict() if base_mix.sum() else {}
            current_share=(current_mix/current_mix.sum()).to_dict() if current_mix.sum() else {}
            leading=max(current_share,key=current_share.get) if current_share else "待判断"
            gap=(current_share.get(leading,0)-base_share.get(leading,0))*100
            target_first=region_target[region_target["月份序号"].isin(PREVIOUS_PERIOD_INDEXES)]["销量"].mean()
            target_recent=region_target[region_target["月份序号"].isin(RECENT_PERIOD_INDEXES)]["销量"].mean()
            target_growth=safe_change(target_recent,target_first)
            structure_name={"price":"价格带","energy":"能源路线","body":"车身形态"}[chart_kind]
            judgment=("该结构在区域内更集中，可将其作为产品配置、传播与渠道陈列的优先锚点。"
                      if gap>2 else
                      "区域结构与全国接近，上市策略可沿用全国主方案，再针对核心城市做轻量调整。"
                      if gap>-2 else
                      "该结构在区域内弱于全国，需避免直接照搬全国组合，并寻找更适配的细分需求。")
            cause=("区域消费者对该结构偏好更集中。" if gap>2 else "区域结构与全国接近，差异主要来自车型与渠道效率。" if gap>-2 else "区域消费者需求重心与全国存在偏移。")
            strategy="把该结构作为区域产品和传播锚点。" if gap>2 else "沿用全国主方案并做轻量区域适配。" if gap>-2 else "避免照搬全国组合，优先寻找区域主导结构。"
            action="调整区域主推配置、素材和展车组合，并按月跟踪份额变化。"
            detail=(f'<b>现象：</b>区域主导{structure_name}为 {leading}，占比较{benchmark} {gap:+.2f}pct；目标近三月变化 {target_growth:+.1%}。<br>'
                    f'<b>原因：</b>{cause}<br><b>策略：</b>{strategy}<br><b>动作：</b>{action}')
        panels.append(
            f'<div class="insight-panel opportunity-panel"><div class="insight-kicker">{region} VS {benchmark}｜{labels[chart_kind]}</div>'
            f'<div class="insight-title">机会点 · {labels[chart_kind]}对比</div>'
            f'<div class="insight-text">{detail}</div></div>'
        )
    st.markdown(f'<div class="insight-grid">{"".join(panels)}</div>',unsafe_allow_html=True)

def read_user_material(uploaded_file):
    name=uploaded_file.name.lower()
    raw=uploaded_file.getvalue()
    try:
        if name.endswith(".txt"):
            return raw.decode("utf-8",errors="ignore")
        if name.endswith(".docx"):
            with zipfile.ZipFile(io.BytesIO(raw)) as package:
                xml=package.read("word/document.xml")
            root=ET.fromstring(xml)
            return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
        if name.endswith(".csv"):
            frame=pd.read_csv(io.BytesIO(raw))
            return "\n".join(frame.fillna("").astype(str).agg("｜".join,axis=1).tolist())
        if name.endswith((".xlsx",".xls")):
            frame=pd.read_excel(io.BytesIO(raw))
            return "\n".join(frame.fillna("").astype(str).agg("｜".join,axis=1).tolist())
    except Exception:
        return ""
    return ""

def compact_top_values(series,limit=3,empty="待识别"):
    values=series.fillna("").astype(str).str.strip()
    values=values[~values.isin(["","nan","无明显影响人","未提及"])]
    if values.empty: return empty
    return "、".join(values.value_counts().head(limit).index.tolist())

def keyword_score(text,words):
    return sum(text.count(word) for word in words)

def value_distribution(series,limit=6):
    values=series.fillna("").astype(str).str.strip()
    values=values[~values.isin(["","nan","未提及"])]
    counts=values.value_counts().head(limit)
    return [(str(name),int(count)) for name,count in counts.items()]

def split_distribution(series,multi=False,limit=10):
    values=[]
    for raw in series.fillna("").astype(str):
        parts=re.split(r"[；;、|]",raw) if multi else [raw]
        values.extend(part.strip() for part in parts if part.strip() and part.strip() not in ["nan","未提及","不清楚"])
    if not values: return []
    counts=pd.Series(values).value_counts().head(limit)
    return [(str(name),int(count)) for name,count in counts.items()]

def norm_brand_name(value):
    key=norm_search(value)
    return key[:-2] if key.endswith("汽车") else key

def survey_rows_for_target(target):
    if user_profile_survey_df.empty: return pd.DataFrame()
    survey=user_profile_survey_df.copy()
    matched_rows=target.get("matched_rows",pd.DataFrame())
    if target.get("is_brand_query"):
        brands=matched_rows["品牌"].dropna().astype(str).unique().tolist() if not matched_rows.empty else [target.get("query","")]
        brand_keys={norm_brand_name(item) for item in brands if str(item).strip()}
        exact=survey[survey["品牌"].map(norm_brand_name).isin(brand_keys)]
        if not exact.empty: return exact.copy()
        query_key=norm_search(target.get("query",""))
        if len(query_key)>=2:
            fuzzy=survey[survey["品牌"].map(lambda value:query_key in norm_search(value) or norm_search(value) in query_key)]
            return fuzzy.copy()
        return pd.DataFrame()
    series_names=matched_rows["车系"].dropna().astype(str).unique().tolist() if not matched_rows.empty else [target.get("车系","")]
    series_keys={norm_search(item) for item in series_names if str(item).strip()}
    exact=survey[survey["车系"].map(norm_search).isin(series_keys) | survey["分析对象名称"].map(norm_search).isin(series_keys)]
    if not exact.empty: return exact.copy()
    if len(series_keys)==1:
        key=next(iter(series_keys))
        fuzzy=survey[survey["车系"].map(lambda value:norm_search(value)==key) | survey["分析对象名称"].map(lambda value:norm_search(value)==key)]
        return fuzzy.copy()
    return pd.DataFrame()

def top_distribution_value(distribution):
    return distribution[0][0] if distribution else "样本不足，暂不判断"

def build_survey_profile(target,rows):
    distributions={
        "年龄段":split_distribution(rows["年龄段"]),
        "职业":split_distribution(rows["职业"]),
        "购车预算":split_distribution(rows["购车预算"]),
        "家庭结构":split_distribution(rows["家庭结构"]),
        "首购 / 增购 / 换购":split_distribution(rows["首购/增购/换购"]),
        "决策周期":split_distribution(rows["决策周期"]),
        "购车动因":split_distribution(rows["购车动因"],multi=True)}
    tops={name:top_distribution_value(values) for name,values in distributions.items()}
    motive_top="、".join(item[0] for item in distributions["购车动因"][:2]) if distributions["购车动因"] else "样本不足，暂不判断"
    family=tops["家庭结构"]
    purchase=tops["首购 / 增购 / 换购"]
    motive=tops["购车动因"]
    occupation=tops["职业"]
    age_numbers=[int(value) for value in re.findall(r"\d+",tops["年龄段"])]
    young_age=bool(age_numbers) and max(age_numbers)<=35
    if purchase=="首购" and young_age: persona="年轻首购型"
    elif purchase=="换购" and any(token in family for token in ["一孩","二孩","三代","有孩"]): persona="家庭换购型"
    elif any(token in motive for token in ["智能","科技","尝鲜"]): persona="科技尝鲜型"
    elif any(token in motive+occupation for token in ["品牌升级","豪华","企业主","管理者","商务"]): persona="豪华品牌升级型"
    elif any(token in motive for token in ["商务","通勤"]): persona="商务通勤型"
    else: persona="理性综合决策型"
    if st.session_state.get("_source_document") and all(tops[k] in ("未知","样本不足，暂不判断") for k in ("年龄段","职业","家庭结构","首购 / 增购 / 换购","购车动因")):
        persona="画像信息不足"
    target_label=f'{target.get("query",target.get("车系","当前目标"))}品牌相关样本' if target.get("is_brand_query") else target.get("车系","当前车型")
    summary=(f'从当前材料样本看，{target_label}用户主要集中在 {tops["年龄段"]}，职业以 {tops["职业"]} 为主，'
             f'家庭结构多为 {tops["家庭结构"]}；购车类型以 {tops["首购 / 增购 / 换购"]} 为主，'
             f'决策周期集中在 {tops["决策周期"]}，主要购车动因是 {motive_top}。')
    keywords={"年龄":tops["年龄段"],"职业":tops["职业"],"家庭":tops["家庭结构"],"决策周期":tops["决策周期"],"购车动因":motive_top}
    return {"persona":persona,"keywords":keywords,"summary":summary,"distributions":distributions,"sample_count":len(rows)}

def profile_distribution_figure(title,distribution):
    labels=[item[0] for item in distribution]
    values=[item[1] for item in distribution]
    total=max(sum(values),1)
    colors=["#5B8FF9","#61DDAA","#F6BD16","#E8684A","#9270CA","#6DC8EC","#FF9D4D","#65789B"]
    fig=go.Figure(go.Pie(labels=labels,values=values,hole=.62,sort=False,direction="clockwise",domain=dict(x=[0,.56]),
                         marker=dict(colors=[colors[index%len(colors)] for index in range(len(labels))],line=dict(color="#0A1B31",width=2)),
                         textinfo="percent",textfont=dict(color="#F5F9FF",size=11),hovertemplate="%{label}<br>%{value}份｜%{percent}<extra></extra>"))
    fig.add_annotation(text=f"{total}<br><span style='font-size:10px'>份样本</span>",x=.28,y=.5,xanchor="center",yanchor="middle",align="center",showarrow=False,font=dict(color="#F5F9FF",size=17))
    fig.update_layout(title=dict(text=title,x=.04,y=.96,font=dict(size=14,color="#F5F9FF")),height=250,
                      margin=dict(l=8,r=5,t=42,b=10),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=True,legend=dict(orientation="v",x=.61,xanchor="left",y=.52,yanchor="middle",font=dict(size=11,color="#BFD1E5")),
                      uniformtext_minsize=9,uniformtext_mode="hide")
    return fig

def render_survey_profile(target, rows_override=None, source_available=True):
    st.markdown('<div id="user-profile" class="section-anchor"></div><div class="user-section-title">◈ 用户画像</div>',unsafe_allow_html=True)
    if not source_available:
        st.info("暂未找到 user_profile_survey.csv / xlsx，请上传问卷结果表或将文件放入项目根目录（也可放入 data 文件夹）。")
        return
    rows=rows_override if rows_override is not None else survey_rows_for_target(target)
    if rows.empty:
        st.info("当前车型暂无用户画像问卷数据，请补充 user_profile_survey.csv。")
        return
    profile=build_survey_profile(target,rows)
    icons={"年轻首购型":"🧑‍💻","家庭换购型":"👨‍👩‍👧","豪华品牌升级型":"💼","科技尝鲜型":"✨","商务通勤型":"🏙️","理性综合决策型":"🚘"}
    asset_names={"年轻首购型":"persona_young.png","家庭换购型":"persona_family.png","豪华品牌升级型":"persona_luxury.png","科技尝鲜型":"persona_tech.png","商务通勤型":"persona_business.png"}
    asset_name=asset_names.get(profile["persona"])
    asset_path=(Path(__file__).resolve().parent/"assets"/asset_name) if asset_name else None
    tags="".join(f'<div class="user-persona-tag"><b>{html.escape(label)}</b>{html.escape(value)}为主</div>' if value!="样本不足，暂不判断" else f'<div class="user-persona-tag"><b>{html.escape(label)}</b>{value}</div>' for label,value in profile["keywords"].items())
    icon=icons.get(profile["persona"],"🚘")
    st.markdown(f'<div class="user-persona-hero"><div class="user-persona-hero-icon">{icon}</div><div class="user-persona-copy"><div class="user-persona-kicker">PERSONA SNAPSHOT</div><div class="user-persona-name">{html.escape(profile["persona"])}</div><div class="user-persona-tags">{tags}</div><div class="user-survey-meta">当前口径有效个体样本：{profile["sample_count"]} 份</div></div></div>',unsafe_allow_html=True)
    st.markdown(f'<div class="user-profile-summary"><b>画像摘要</b><br>{html.escape(profile["summary"])}</div>',unsafe_allow_html=True)
    st.markdown('<div class="user-profile-evidence">数据支撑</div>',unsafe_allow_html=True)
    chart_fields=["年龄段","职业","购车预算","家庭结构","首购 / 增购 / 换购","决策周期"]
    for start in range(0,len(chart_fields),3):
        cols=st.columns(3,gap="small")
        for col,field in zip(cols,chart_fields[start:start+3]):
            with col:
                values=profile["distributions"].get(field,[])
                with st.container(border=True):
                    if values:
                        render_responsive_chart(profile_distribution_figure(f"{field}分布",values),use_container_width=True,key=f'profile_{field}_{norm_search(target.get("query","target"))}')
                    else:
                        st.markdown(f'<div class="ai-card"><b>{field}分布</b><br><span class="small-note">样本不足，暂不判断</span></div>',unsafe_allow_html=True)

def infer_purchase_type(text):
    if any(word in text for word in ["置换","换车","增购","家里已有","现在开的车","原来的车"]): return "增换购"
    if any(word in text for word in ["首购","第一辆车","第一次买车"]): return "首购"
    return "未明确"

def extract_competitor_names(text,target_name,limit=3):
    counts={}
    for name in car_df["车系"].dropna().astype(str).drop_duplicates():
        if name==target_name: continue
        count=text.count(name)
        if count: counts[name]=count
    patterns=[r"看过([^，。；但更]{2,14})",r"之前看的([^，。；但更]{2,14})",r"对比([^，。；时]{2,14})"]
    for pattern in patterns:
        for name in re.findall(pattern,text):
            clean=name.strip("，。；、 ")
            if clean and clean!=target_name and not any(word in clean for word in ["起来","以后","一下"]):
                counts[clean]=counts.get(clean,0)+1
    return [name for name,_ in sorted(counts.items(),key=lambda item:(-item[1],item[0]))[:limit]]

def build_material_user_insight(target,rows):
    target_name=str(target["车系"])
    text="\n".join(rows["用户原文"].astype(str))
    needs_map={
        "空间舒适":["空间","后排","座椅","舒适","乘坐","第三排"],
        "安全表现":["安全","刹车","碰撞","辅助驾驶","智驾"],
        "智能体验":["智能","车机","座舱","语音","智驾","辅助驾驶"],
        "价格权益":["价格","优惠","权益","预算","性价比","降价"],
        "品牌与品质":["品牌","品质","质量","可靠","豪华","体面"],
        "补能与续航":["充电","补能","续航","长途","油耗","能耗"],
        "驾驶体验":["操控","驾驶","底盘","动力","开起来"],
        "使用成本":["保养","维修","保险","保值","成本"]}
    scored=[]
    reason_templates={
        "空间舒适":"家庭乘坐、后排空间和长途舒适度直接影响共同决策",
        "安全表现":"家庭出行使主动安全与驾驶辅助成为重要判断项",
        "智能体验":"用户会将车机、座舱和辅助驾驶与同价位竞品直接比较",
        "价格权益":"成交优惠、权益稳定性和预算适配影响最终下单",
        "品牌与品质":"品牌认可、豪华感和长期可靠性构成信任基础",
        "补能与续航":"补能条件、续航与实际能耗决定使用便利性",
        "驾驶体验":"底盘、动力和操控感受需要通过试驾完成验证",
        "使用成本":"维修保养、保险与保值影响长期持有判断"}
    for name,words in needs_map.items():
        count=keyword_score(text,words)
        if count: scored.append((name,count,reason_templates[name]))
    scored.sort(key=lambda item:(-item[1],item[0]))
    max_score=max([item[1] for item in scored],default=1)
    needs=[(name,int(62+30*count/max_score),reason) for name,count,reason in scored[:5]]
    concern_map={
        "智能体验仍有差距":["车机","智能化","智驾","辅助驾驶","不够新"],
        "价格与权益波动":["降价","优惠","权益","背刺","价格"],
        "长期质量与售后成本":["维修","保养","小毛病","质量","可靠","售后"],
        "补能、续航与能耗":["充电","续航","补能","油耗","能耗"],
        "空间与乘坐体验":["空间小","后排小","第三排","座椅硬","不舒服"]}
    concerns=[]
    for name,words in concern_map.items():
        count=keyword_score(text,words)
        if count:
            concerns.append((name,f"对应表达在当前车型材料中出现 {count} 次，需在试驾或成交沟通中优先回应。"))
    concerns=concerns[:3] or [("决策信息不足","当前材料中的负向表达较少，建议补充流失用户与未购用户访谈。")]
    competitors=extract_competitor_names(text,target_name,3)
    competitor_cards=[]
    for name in competitors:
        related=[sentence.strip() for sentence in re.split(r"[。！？\n]",text) if name in sentence]
        joined="；".join(related)
        trait="同价位和相近使用场景的综合产品力"
        if any(word in joined for word in ["智能","车机","智驾"]): trait="智能座舱与辅助驾驶体验"
        elif any(word in joined for word in ["品牌","豪华","体面"]): trait="品牌认知与豪华体验"
        elif any(word in joined for word in ["空间","舒适","后排","座椅"]): trait="空间与家庭乘坐体验"
        advantage=f"主要竞争维度为{trait}"
        win="本品在家庭场景完整度、综合适配或试驾共识上更符合用户需求"
        loss=f"若用户优先选择{trait}，且本品未充分建立差异，可能转向{name}"
        competitor_cards.append((name,advantage,win,loss))
    if not competitor_cards:
        competitor_cards=[("暂未形成明确竞品","材料中未出现稳定的对比车型","本品选择更多来自自身产品价值","建议补充决策过程中的对比车型追问")]
    quotes=[item.strip() for item in re.split(r"[。！？\n]",text) if 14<=len(item.strip())<=90][:3]
    profile={
        "年龄":compact_top_values(rows["年龄段"],2),
        "职业":compact_top_values(rows["职业"],3),
        "收入或预算":str(target.get("覆盖价格段文本","待识别")),
        "婚育与家庭结构":compact_top_values(rows["家庭结构"],2),
        "首购/增换购类型":infer_purchase_type(text),
        "购车动因":needs[0][0]+"、"+(needs[1][0] if len(needs)>1 else "综合产品升级"),
        "决策周期":compact_top_values(rows["决策周期"],2),
        "决策人和影响人":compact_top_values(rows["主要决策人"],2)+"；影响人："+compact_top_values(rows["决策影响人"],2,"未明确"),
        "信息获取渠道":compact_top_values(rows.get("来源平台",pd.Series(dtype=str)),3)}
    purchase_types=pd.Series([infer_purchase_type(item) for item in rows["用户原文"].astype(str)])
    distributions={
        "年龄":value_distribution(rows["年龄段"]),
        "职业":value_distribution(rows["职业"]),
        "预算":value_distribution(rows.get("车型价格范围",pd.Series(dtype=str))),
        "家庭结构":value_distribution(rows["家庭结构"]),
        "首购/增换购":value_distribution(purchase_types)}
    return {"target":target_name,"profile":profile,"needs":needs,"concerns":concerns,"competitors":competitor_cards,
            "quotes":quotes,"source":f"车型资料库（{len(rows)}条）","distributions":distributions}

def user_insight_base(target):
    target_name=str(target.get("车系",""))
    if not user_material_df.empty:
        matched=user_material_df[user_material_df["车系"].astype(str).map(norm_search)==norm_search(target_name)].copy()
        if not matched.empty:
            return build_material_user_insight(target,matched)
    name=str(target.get("车系","目标车型"))
    body=str(target.get("车身形式","SUV"))
    energy=str(target.get("能源大类","ICE"))
    price=str(target.get("覆盖价格段文本","30-40万"))
    family_mode="家庭升级" if "SUV" in body or "MPV" in body else "品质换购"
    if energy=="BEV":
        needs=[("智能体验",88,"高频通勤希望降低驾驶负担"),("补能效率",80,"充电便利性直接影响日常使用"),("安全表现",75,"家庭用户关注主动与被动安全"),("空间舒适",70,"兼顾通勤与家庭共同出行"),("使用成本",64,"希望降低长期能源与保养支出")]
        concerns=[("补能与长途便利","担心节假日长途补能时间和路线规划"),("保值率","关注新能源车型长期残值变化"),("智能功能稳定性","担心功能更新与实际体验存在差异")]
        competitors=[("问界M7","智能座舱与服务体验","操控与补能效率","空间和家庭场景不足"),("理想L6","家庭空间与舒适配置","智能体验和驾驶感受","长途便利与家庭认可度"),("蔚来ES6","服务体系与换电体验","使用成本和产品效率","品牌服务感知不足")]
    elif energy=="PHEV":
        needs=[("空间舒适",90,"家庭成员共同出行频繁，二排体验影响决策"),("安全表现",84,"儿童与长途出行提升安全关注"),("补能便利",76,"希望兼顾城市用电和长途无焦虑"),("智能体验",70,"期待座舱与辅助驾驶降低使用负担"),("价格权益",62,"需要在家庭预算内获得明确配置价值")]
        concerns=[("价格与权益变化","担心购车后短期调整影响价值感"),("长期质量稳定性","关注复杂动力系统的可靠性"),("实际能耗","担心馈电油耗与宣传体验存在差异")]
        competitors=[("问界M7","智能座舱、渠道服务与科技感","空间舒适和家庭认可","价格权益或智能体验不足"),("Model Y","品牌认知、操控与补能网络","家庭空间和二排舒适","品牌号召力与使用效率不足"),("蔚来ES8","服务体验和豪华感","补能灵活与家庭场景","豪华感或服务感知不足")]
    else:
        needs=[("品牌与品质",88,"换购用户希望获得更稳定的品质认同"),("乘坐舒适",82,"商务与家庭场景都重视静谧和底盘体验"),("安全表现",76,"成熟用户对可靠性和安全更敏感"),("价格权益",69,"成交价格和金融方案影响最终选择"),("保值率",63,"换购用户关注长期持有成本")]
        concerns=[("新能源转型速度","担心传统动力产品后续竞争力下降"),("配置性价比","关注同价位新能源车型配置优势"),("后期使用成本","保险、保养与维修成本影响决策")]
        competitors=[("宝马5系","操控、品牌形象与驾驶体验","舒适和稳重表达","驾驶乐趣或品牌个性不足"),("奔驰E级","豪华氛围与品牌认同","均衡配置与使用便利","豪华感和内饰吸引力不足"),("新能源中大型车","智能配置与使用成本","成熟品质和售后网络","智能化或使用成本不占优")]
    profile={"年龄":"30–39岁","职业":"企业职员、管理者及专业人士","收入或预算":price,"婚育与家庭结构":"已婚育儿家庭为主","首购 / 增购 / 换购类型":"样本不足，暂不判断","购车动因":family_mode+"、改善空间与使用体验","决策周期":"1–3个月","决策人和影响人":"夫妻共同决策，子女与父母体验产生影响","信息获取渠道":"汽车App、短视频、朋友推荐与门店试驾"}
    return {"target":name,"profile":profile,"needs":needs,"concerns":concerns,"competitors":competitors,
            "quotes":["家里人坐得舒服，比单纯看参数更重要。","买车会同时比较两三款，最后还是看全家试驾后的感受。"],"source":"系统基础资料"}

def analyze_user_material(target,text,has_upload=False):
    result=user_insight_base(target)
    clean=re.sub(r"\s+"," ",text or "").strip()
    if not clean:
        return result
    keyword_rules={
        "空间与乘坐舒适":["空间","二排","座椅","舒适","静音","静谧","底盘","后备箱"],"安全表现":["安全","儿童","碰撞","刹车"],
        "智能体验":["智能","智驾","辅助驾驶","车机","座舱"],"补能便利":["充电","补能","续航","长途","油耗"],
        "价格权益":["价格","优惠","权益","降价","预算"],"品牌与品质":["品牌","质量","品质","可靠"],
        "使用成本":["能耗","保养","保险","成本"]}
    scores={name:sum(clean.count(word) for word in words) for name,words in keyword_rules.items()}
    merged=[]
    need_alias={"空间舒适":"空间与乘坐舒适","乘坐舒适":"空间与乘坐舒适","补能便利":"补能与续航"}
    base_reason={need_alias.get(name,name):reason for name,_,reason in result["needs"]}
    for name,count in sorted(scores.items(),key=lambda item:item[1],reverse=True):
        if count:
            merged.append((name,min(98,60+count*5),f"当前原文资料中相关表达出现 {count} 次；{base_reason.get(name,'该因素多次参与用户选择判断')}"))
    for item in result["needs"]:
        canonical=need_alias.get(item[0],item[0])
        if canonical not in {row[0] for row in merged}: merged.append((canonical,item[1],item[2]))
    result["needs"]=merged[:5]
    age_matches=[int(value) for value in re.findall(r"(?:年龄|今年|我)(?:为|是|：|:)?\s*(2[0-9]|3[0-9]|4[0-9]|5[0-9])\s*岁?",clean)]
    if age_matches:
        avg=int(round(sum(age_matches)/len(age_matches)))
        result["profile"]["年龄"]=f"约{avg}岁（资料识别）"
    budget=re.findall(r"(\d{2,3})(?:\s*[-至到]\s*(\d{2,3}))?\s*万",clean)
    if budget:
        low,high=budget[0]; result["profile"]["收入或预算"]=f"{low}-{high}万元" if high else f"约{low}万元"
    occupation_map=[("教师",["教师","老师"]),("企业职员",["职员","上班族","白领"]),("管理者",["管理","经理","负责人"]),("个体经营",["个体","创业","老板"]),("专业人士",["医生","律师","工程师"])]
    occupations=[label for label,words in occupation_map if any(word in clean for word in words)]
    if occupations: result["profile"]["职业"]="、".join(occupations)
    known_competitors=["Model Y","问界M7","问界M6","蔚来ES8","蔚来ES6","宝马5系","奔驰E级","奥迪A6L","理想L6","理想L8","汉兰达","坦克300"]
    mentioned=[name for name in known_competitors if norm_search(name) in norm_search(clean) and norm_search(name)!=norm_search(result["target"])]
    if mentioned:
        original={row[0]:row for row in result["competitors"]}
        result["competitors"]=[original.get(name,(name,"资料中被用户主动列入比较范围","本品在家庭适配与综合体验上更匹配","竞品在特定卖点或价格上更具吸引力")) for name in mentioned[:3]]
    sentences=[item.strip() for item in re.split(r"[。！？!?\n]",text) if 12<=len(item.strip())<=90]
    if sentences: result["quotes"]=sentences[:3]
    result["source"]="用户上传资料" if has_upload else "data 默认资料"
    return result

def clear_user_materials():
    st.session_state["user_upload_nonce"]=st.session_state.get("user_upload_nonce",0)+1
    st.session_state.pop("user_insight_result",None)
    st.session_state.pop("user_insight_target",None)

def render_user_insight_page(target):
    nonce=st.session_state.get("user_upload_nonce",0)
    st.markdown('<div class="user-section-title" style="margin-top:12px">◈ 资料上传与分析</div><div class="user-section-note">上传多个访谈、问卷或评论文件，也可直接粘贴用户原话。</div>',unsafe_allow_html=True)
    uploaded=st.file_uploader("上传用户资料",type=["docx","xlsx","xls","csv","txt"],accept_multiple_files=True,key=f"user_files_{nonce}")
    pasted=st.text_area("粘贴访谈、问卷开放题或用户评论",placeholder="可直接粘贴一段或多段用户原话……",height=88,key=f"user_text_{nonce}")
    extracted=[]
    for file in uploaded or []:
        content=read_user_material(file)
        if content: extracted.append(content)
    combined="\n".join(extracted+[pasted or ""])
    file_count=len(uploaded or [])
    char_count=len(re.sub(r"\s+","",combined))
    st.markdown(f'<div class="user-source-row"><span class="user-source-pill">已识别文件 {file_count} 个</span><span class="user-source-pill">已识别文本 {char_count:,} 字</span></div>',unsafe_allow_html=True)
    start_col,clear_col=st.columns([3,1])
    with start_col:
        start=st.button("开始用户洞察分析",type="primary",use_container_width=True,key="start_user_insight")
    with clear_col:
        st.button("清除资料",use_container_width=True,key="clear_user_material",on_click=clear_user_materials)
    if start:
        with st.spinner("正在识别资料并生成用户洞察……"):
            st.session_state["user_insight_result"]=analyze_user_material(target,combined,bool(file_count))
            st.session_state["user_insight_target"]=target["车系"]
    if st.session_state.get("user_insight_target")!=target["车系"]:
        st.session_state["user_insight_result"]=user_insight_base(target)
        st.session_state["user_insight_target"]=target["车系"]
    result=st.session_state.get("user_insight_result") or user_insight_base(target)

    render_survey_profile(target)

    st.markdown('<div class="user-section-title">◈ 用户需求</div><div class="user-section-note">综合资料提及情况与购车决策影响，展示需求优先级和主要顾虑。</div>',unsafe_allow_html=True)
    need_rows="".join(f'<div class="user-need-row"><span class="user-need-rank">{i}</span><span class="user-need-name">{html.escape(name)}</span><div class="user-need-bar"><div class="user-need-fill" style="width:{score}%"></div></div><span class="user-need-score">{score}</span></div>' for i,(name,score,_) in enumerate(result["needs"],1))
    reasons="".join(f'<div class="user-reason-item"><b>{html.escape(name)}</b>{html.escape(reason)}</div>' for name,_,reason in result["needs"][:4])
    concerns="".join(f'<div class="user-reason-item user-concern-item"><b>{html.escape(name)}</b>{html.escape(reason)}</div>' for name,reason in result["concerns"])
    st.markdown(f'<div class="user-need-layout"><div class="user-need-panel"><div class="insight-title">需求优先级</div>{need_rows}</div><div><div class="user-need-panel"><div class="insight-title">关注理由</div><div class="user-reason-list">{reasons}</div></div><div class="user-need-panel" style="margin-top:11px"><div class="insight-title">顾虑与提升空间</div><div class="user-reason-list">{concerns}</div></div></div></div>',unsafe_allow_html=True)

    st.markdown('<div class="user-section-title">◈ 竞品对比</div><div class="user-section-note">聚焦用户决策过程中为什么选择本品或转向竞品。</div>',unsafe_allow_html=True)
    competitor_cards="".join(f'<div class="user-competitor-card"><div class="user-competitor-name">{html.escape(name)}</div><div class="user-competitor-block"><b>竞品优势</b>{html.escape(advantage)}</div><div class="user-competitor-block"><b>本品赢单原因</b>{html.escape(win)}</div><div class="user-competitor-block"><b>本品丢单原因</b>{html.escape(loss)}</div></div>' for name,advantage,win,loss in result["competitors"])
    st.markdown(f'<div class="user-competitor-grid">{competitor_cards}</div>',unsafe_allow_html=True)

    primary_need=result["needs"][0][0]
    primary_concern=result["concerns"][0][0]
    scripts=[("需求识别","先确认家庭与换购背景",f"您这次换车最希望改善的是哪种日常体验？如果重点是{primary_need}，建议把全家高频使用场景一起放进判断。"),("竞品比较","把参数比较转为场景比较",f"您同时考虑的车型各有优势，可以用通勤、全家出行和长途三个真实场景逐项体验，再看哪一款更符合长期使用。"),("顾虑回应",f"正面回应{primary_concern}",f"您对{primary_concern}的担心很实际，我们可以把当前权益、实际使用条件和长期成本逐项算清楚，再判断是否适合现在做决定。"),("促成转化","推动共同试驾和家庭确认",f"建议邀请主要决策人与家人共同试驾，重点体验{primary_need}，现场确认没有明显顾虑后再讨论具体购车方案。")]
    script_cards="".join(f'<div class="user-script-card"><div class="user-script-stage">{html.escape(stage)}</div><div class="user-script-title">{html.escape(title)}</div><div class="user-script-text">{html.escape(text)}</div></div>' for stage,title,text in scripts)
    quote=html.escape(result["quotes"][0]) if result["quotes"] else "暂无可展示用户原话"
    st.markdown(f'<div class="user-section-title">◈ 沟通话术</div><div class="user-section-note">按需求识别、竞品比较、顾虑回应和促成转化组织沟通。</div><div class="user-script-grid">{script_cards}</div><div class="user-quote">用户原话：“{quote}”</div>',unsafe_allow_html=True)


def _render_ai_empty(message):
    st.markdown(f'<div class="ai-card"><span class="small-note">{html.escape(message)}</span></div>',unsafe_allow_html=True)


def _show_user_data_loaded_dialog(stats):
    if not hasattr(st,"dialog"):
        st.success(f'资料已载入：问卷 {stats["survey"]} 份，原文 {stats["materials"]} 条。')
        return
    @st.dialog("资料载入完成",width="large")
    def _dialog():
        st.markdown(f'<div class="user-ai-kpis"><div class="user-ai-kpi">当前目标问卷<b>{stats["survey"]}</b></div><div class="user-ai-kpi">当前目标原文<b>{stats["materials"]}</b></div><div class="user-ai-kpi">待 AI 分析<b>{stats["pending"]}</b></div><div class="user-ai-kpi">已完成分析<b>{stats["analyzed"]}</b></div><div class="user-ai-kpi">本次最多分析<b>{stats["batch"]}</b></div></div>',unsafe_allow_html=True)
        if stats["survey"] or stats["materials"]:
            if stats["materials"] and stats["pending"]==0 and stats["analyzed"]:
                st.success("资料读取成功，原文材料已匹配现有 AI 缓存，无需重复分析；页面已直接更新结果。")
            elif stats["materials"]:
                st.success("资料读取成功，已按当前分析对象完成匹配。问卷数据将直接统计，新增原文可点击“一键生成 AI 报告”。")
            else:
                st.success("问卷资料读取成功，用户画像与分布图已按当前分析对象更新。")
        else:
            st.warning("文件已读取，但没有匹配到当前分析对象。请检查品牌、车系或分析对象名称字段。")
        if st.button("知道了",type="primary",use_container_width=True,key="close_user_upload_dialog"):
            st.rerun()
    _dialog()


def _render_ai_summary(summary):
    if not summary:
        return
    competitor_summary=str(summary.get("竞品比较总结","数据不足"))
    for generic_name in ["新能源替代车型","新能源车型","新能源汽车","新能源车","新势力车型","新势力","同级别车型","同价位竞品"]:
        competitor_summary=competitor_summary.replace(generic_name,"")
    competitor_summary=(re.sub(r"[、，,]{2,}","、",competitor_summary)
                        .replace("为、","为").replace("、和","和").replace("和，","，").replace("和,",",")
                        .strip("、，, "))
    strategy="".join(f'<li>{html.escape(str(item))}</li>' for item in summary.get("沟通策略建议",[])[:3])
    st.markdown(
        '<div class="user-section-title">◈ AI洞察总结</div>'
        '<div class="ai-card">'
        f'<div class="insight-title">用户画像总结</div><div class="insight-text">{html.escape(str(summary.get("用户画像总结","数据不足")))}</div><br>'
        f'<div class="insight-title">核心需求总结</div><div class="insight-text">{html.escape(str(summary.get("核心需求总结","数据不足")))}</div><br>'
        f'<div class="insight-title">主要顾虑总结</div><div class="insight-text">{html.escape(str(summary.get("主要顾虑总结","数据不足")))}</div><br>'
        f'<div class="insight-title">竞品比较总结</div><div class="insight-text">{html.escape(competitor_summary or "当前材料尚未识别到明确品牌或车系竞品。")}</div><br>'
        f'<div class="insight-title">沟通策略建议</div><ul class="insight-text">{strategy}</ul>'
        f'<div class="small-note">{html.escape(str(summary.get("数据不足提醒","")))}</div></div>',unsafe_allow_html=True)

def public_competitor_profile(name):
    """Curated public-review evidence used only to supplement, never replace, uploaded user material."""
    normalized=norm_search(str(name))
    profiles=[
        (["modely","特斯拉"],"操控响应、空间利用率、悬架舒适性、能耗与补能效率","动力响应、操控和超充网络辨识度高，空间利用率也较突出；悬架偏硬、极简内饰和功能适应成本是常见取舍","https://www.dongchedi.com/auto/series/score/4363-x-S7-x-x-x-1","懂车帝车主口碑"),
        (["小鹏g9","g9"],"智能驾驶、800V补能、续航表现与家庭空间舒适度","智能驾驶与补能效率更容易形成技术感知；理想车型则在多人乘坐、家庭空间与舒适配置上更占优势","https://www.autohome.com.cn/pk/158522.html","汽车之家车型对比"),
        (["蔚来es8","es8"],"换电便利、服务体系、空气悬架、三排空间与静谧性","换电与服务体系辨识度高，空气悬架、三排空间和NVH获得车主较多肯定；大车停车和软件操作仍是常见取舍","https://www.dongchedi.com/auto/series/score/1616-x-S0-3-create_time-x-6","懂车帝车主口碑"),
        (["问界m9","m9"],"华为智驾、鸿蒙座舱、豪华配置、价格与家庭实用性","华为ADS与鸿蒙座舱形成鲜明智能化优势，豪华配置更高；理想车型在家庭空间实用、增程成熟度和价格门槛上更容易建立价值感","https://auto.zol.com.cn/1207/12078497_all.html","公开车型横评"),
        (["奥迪q5l","q5l"],"豪华品牌认知、动力与底盘质感、后排空间、内饰科技感和用车成本","驾驶质感、动力和品牌认知是主要优势；用户也会权衡内饰科技感、后排体验、油耗及智能化配置","https://www.dongchedi.com/auto/series/score/2916-x-S0-x-x-1-x","懂车帝车主口碑"),
    ]
    for aliases,compare,advantage,url,source in profiles:
        if any(alias in normalized for alias in aliases):
            return {"比较点":compare,"竞品优势":advantage,"来源":source,"链接":url}
    return None


def render_user_insight_page(target):
    st.markdown("""
    <style>
    .user-ai-toolbar{padding:13px 16px;border:1px solid #294a70;border-radius:14px;background:linear-gradient(135deg,#112641,#0b192d);margin:8px 0 10px}
    .user-ai-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:10px 0 14px}
    .user-ai-kpi{padding:12px;border:1px solid #2a4668;border-radius:12px;background:#10223a;color:#d9e9fa}.user-ai-kpi b{display:block;color:#fff;font-size:20px;margin-top:4px}
    .user-top-list{display:grid;gap:9px}.user-top-item{padding:12px 14px;border:1px solid #28496d;border-radius:12px;background:#10233b}.user-top-item b{color:#f8fbff}.user-top-item span{color:#7fb3ff;float:right}
    .user-evidence-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.user-evidence-card{padding:14px;border:1px solid #28496d;border-radius:13px;background:#10223a}.user-evidence-card b{color:#fff}.user-evidence-card .meta{font-size:12px;color:#8eabc8;margin:5px 0}.user-evidence-card .tags{color:#72d8b2;font-size:12px;margin-top:8px}
    .user-rank-stack{display:flex;flex-direction:column;gap:10px;padding:5px 0}.user-rank-row{position:relative;min-height:74px;padding:12px 18px 12px 58px;border-radius:14px;background:linear-gradient(90deg,rgba(77,119,238,.30),rgba(20,47,79,.84));border:1px solid rgba(112,170,241,.28);overflow:hidden}.user-rank-row:nth-child(1){background:linear-gradient(90deg,rgba(255,178,72,.34),rgba(25,52,83,.90));border-color:rgba(255,199,103,.48)}.user-rank-row:nth-child(2){margin-right:3%}.user-rank-row:nth-child(3){margin-right:6%}.user-rank-row:nth-child(4){margin-right:9%}.user-rank-row:nth-child(5){margin-right:12%}.user-rank-no{position:absolute;left:13px;top:14px;width:32px;height:32px;border-radius:10px;display:flex;align-items:center;justify-content:center;background:#294f82;color:#fff;font-size:14px;font-weight:950}.user-rank-row:first-child .user-rank-no{background:#F3A93B;color:#14233a}.user-rank-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.user-rank-name{color:#fff;font-size:15px;font-weight:950}.user-rank-value{color:#9dc8f5;font-size:13px;font-weight:900}.user-rank-row:first-child .user-rank-value{color:#ffd797}.user-rank-detail{margin-top:7px;color:#C8D9EA;font-size:12px;line-height:1.65}.user-rank-detail b{color:#80D8BB}
    .user-action-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.user-action-card{padding:16px 17px;border-radius:15px;background:linear-gradient(145deg,rgba(44,67,105,.88),rgba(12,29,52,.94));border:1px solid rgba(242,150,102,.30)}.user-action-label{color:#ffae7a;font-size:11px;font-weight:950;letter-spacing:.06em}.user-action-title{color:#fff;font-size:16px;font-weight:950;margin:7px 0}.user-action-text{color:#cbdced;font-size:13px;line-height:1.7}
    .user-competitor-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.user-competitor-card{padding:18px;border-radius:16px;background:linear-gradient(145deg,rgba(31,65,103,.96),rgba(10,28,50,.96));border:1px solid rgba(91,205,190,.34);box-shadow:0 12px 26px rgba(0,0,0,.12)}.user-competitor-name{color:#fff;font-size:18px;font-weight:950;margin-bottom:13px}.user-competitor-line{padding:9px 0;border-top:1px solid rgba(255,255,255,.08);color:#d6e5f5;font-size:13px;line-height:1.65}.user-competitor-line b{display:block;color:#72d8c0;font-size:11px;margin-bottom:3px}.user-quote-single{min-height:190px;padding:25px 27px;border-radius:18px;background:linear-gradient(145deg,#172f50,#0d213a);border:1px solid rgba(108,174,239,.32);display:flex;flex-direction:column;justify-content:center}.user-quote-text{color:#fff;font-size:17px;font-weight:800;line-height:1.85}.user-quote-meta{margin-top:14px;color:#8faccc;font-size:12px}.user-quote-count{text-align:center;color:#7fc4f5;font-size:12px;margin-top:9px}
    @media(max-width:900px){.user-ai-kpis{grid-template-columns:repeat(2,1fr)}.user-evidence-grid,.user-action-grid{grid-template-columns:1fr}.user-rank-row{margin-right:0!important}}
    </style>
    """,unsafe_allow_html=True)
    st.markdown('<div class="user-section-title" style="margin-top:12px">◈ 上传用户资料与AI报告</div><div class="user-section-note">未上传时展示演示资料；上传后自动提取材料中的个体记录，并生成对应画像与洞察。</div>',unsafe_allow_html=True)
    upload_panel=st.container(border=True)
    with upload_panel:
        from user_documents import persist_document, extract_document
        st.file_uploader("用户访谈/问卷材料", type=["docx","pdf","xlsx","csv"],
                         key="user_document_upload", on_change=persist_document)
        st.caption("支持 Word（DOCX）、文字版 PDF、Excel（XLSX）及 CSV。上传即发送至 DeepSeek 分析，请仅使用模拟或已脱敏资料。每次最多 5 MB、24000 字符、30 位受访者；扫描 PDF 请先转为文字版。")
        document=st.session_state.get("_source_document")
        if document:
            import hashlib
            attempt=hashlib.sha256(document[1]+dsui.target_label(target).encode()).hexdigest()
            result=st.session_state.get("_document_result")
            ready=bool(result and result["fingerprint"]==attempt)
            retry=False
            if st.session_state.get("_document_error"):
                st.error(st.session_state["_document_error"])
                retry=st.button("重试材料分析")
            if not dsui.api_config()["api_key"]:
                st.info("AI 尚未配置，暂不能分析上传材料。")
            elif not ready and (st.session_state.get("_document_attempt")!=attempt or retry):
                st.session_state["_document_attempt"]=attempt
                try:
                    with st.spinner("正在读取材料、提取个体信息并计算画像……"):
                        extract_document(target)
                    st.session_state.pop("_document_error",None)
                    st.rerun()
                except Exception as exc:
                    st.session_state["_document_error"]="材料分析未完成："+str(exc)
                    st.error(st.session_state["_document_error"])
            result=st.session_state.get("_document_result")
            if not result or result["fingerprint"]!=attempt:
                st.info("尚无本次材料的分析结果。完成提取后才显示画像，不会使用默认演示样本填充。")
                return
            st.success(f"材料已提取：{len(result['survey'])} 位受访者。缺失信息标记为未知，比例由个体记录计算。")
            with st.expander("查看提取明细，核对原文"):
                st.dataframe(result["survey"],hide_index=True)
                st.dataframe(result["materials"][["样本ID","用户原文"]],hide_index=True)
        survey_upload=materials_upload=None
    survey_all,survey_source,survey_error=dsui.load_source_table("survey",survey_upload)
    materials_all,materials_source,materials_error=dsui.load_source_table("materials",materials_upload)
    if survey_error: st.warning(survey_error)
    if materials_error: st.warning(materials_error)
    survey_rows=dsui.filter_for_target(survey_all,target)
    material_rows=dsui.filter_for_target(materials_all,target)
    cache_rows=dsui.cache_for_materials(material_rows)
    material_ids=set(material_rows.apply(dsui._material_id,axis=1)) if not material_rows.empty else set()
    analyzed_ids=set(cache_rows["材料ID"].astype(str)) if not cache_rows.empty else set()
    pending_count=len(material_ids-analyzed_ids)
    batch_count=min(5,pending_count,max(0,remaining_session_calls()-1))
    survey_profile=build_survey_profile(target,survey_rows) if not survey_rows.empty else None
    upload_signature=tuple((item.name,getattr(item,"size",0)) for item in [survey_upload,materials_upload] if item is not None)
    if upload_signature and st.session_state.get("user_upload_dialog_signature")!=upload_signature:
        st.session_state["user_upload_dialog_signature"]=upload_signature
        _show_user_data_loaded_dialog({"survey":len(survey_rows),"materials":len(material_rows),"pending":pending_count,"analyzed":len(cache_rows),"batch":batch_count})
    config=dsui.api_config()
    if not config["api_key"]:
        st.info("在线 AI 暂未启用。下方问卷画像与基础洞察仍可直接查看，无需填写密钥。")
    st.caption(f"当前匹配：{len(survey_rows)} 份问卷 · {len(material_rows)} 条原文 · {len(cache_rows)} 条已完成 AI 分析。未上传时使用明确标注的演示样本。")
    analyzed_count=len(cache_rows)
    summary=dsui.get_cached_summary(target,len(survey_rows),len(material_rows),analyzed_count)
    if document and not cache_rows.empty and summary is None:
        summary_attempt=dsui.summary_key(target,len(survey_rows),len(material_rows),analyzed_count)
        if st.session_state.get("_document_summary_attempt")!=summary_attempt:
            st.session_state["_document_summary_attempt"]=summary_attempt
            try:
                with st.spinner("正在汇总本次材料的洞察……"):
                    summary=dsui.generate_summary(target,survey_profile or {},cache_rows,len(survey_rows),len(material_rows))
            except Exception:
                st.warning("个体提取和画像统计已完成，汇总暂未生成。可点击下方按钮重试汇总。")
    if material_rows.empty:
        st.info("当前车型暂无用户原文材料；可上传 user_materials.csv / xlsx，或补充本地默认文件。")
    else:
        with upload_panel:
            st.markdown('<div style="height:4px"></div>',unsafe_allow_html=True)
            _,report_col,_=st.columns([.7,2.2,.7])
            with report_col:
                run_report=st.button("一键生成 AI 报告",type="primary",use_container_width=True,disabled=(not config["api_key"]),key="run_deepseek_report")
            st.markdown('<div style="text-align:center;color:#8FA7C2;font-size:12px;margin:5px 0 10px;">自动分析新增语料并生成当前分析对象的AI洞察总结；已有结果将直接复用。</div>',unsafe_allow_html=True)
            if run_report:
                errors=[]
                if pending_count and not batch_count:
                    errors.append("本次体验的 AI 额度不足以继续提取新材料；下方仍可查看现有结果。")
                if batch_count:
                    with st.spinner(f"正在分析本批 {batch_count} 条新增材料……"):
                        _,errors=dsui.analyze_new_materials(material_rows,target,batch_count)
                refreshed_cache=dsui.cache_for_materials(material_rows)
                if not refreshed_cache.empty and (batch_count or summary is None) and not errors:
                    with st.spinner("正在生成页面级用户洞察总结……"):
                        try:
                            summary=dsui.generate_summary(target,survey_profile or {},refreshed_cache,len(survey_rows),len(material_rows))
                        except Exception as exc:
                            errors.append(str(exc))
                if errors:
                    st.error("部分分析未完成：\n"+"\n".join(errors[:5]))
                else:
                    st.session_state["user_report_notice"]=f"AI 报告已更新，已分析 {len(refreshed_cache)} / {len(material_ids)} 条材料；未分析材料不计入 AI 结论。"
                    st.rerun()
            _render_ai_summary(summary)
    if st.session_state.get("user_report_notice"):
        st.success(st.session_state.pop("user_report_notice"))
    render_survey_profile(target,rows_override=survey_rows,source_available=not survey_all.empty)
    if survey_rows.empty and material_rows.empty:
        st.warning("当前车型暂无用户洞察数据，请上传或补充对应问卷表与用户原文材料。")
    cache_rows=dsui.cache_for_materials(material_rows)
    ai_ready=not cache_rows.empty
    baseline=None
    if ai_ready:
        needs=dsui.aggregate_top(cache_rows,"核心需求",5)
        reasons=dsui.aggregate_top(cache_rows,"关注理由",5)
        concerns=dsui.aggregate_top(cache_rows,"顾虑点",5)
        improvements=dsui.aggregate_top(cache_rows,"提升空间",5)
        competitors=dsui.aggregate_top(cache_rows,"提及竞品",5)
        dimensions=dsui.aggregate_top(cache_rows,"比较维度",5)
    elif not material_rows.empty:
        baseline=analyze_user_material(target,"\n".join(material_rows["用户原文"].astype(str)),False)
        needs=[(name,score) for name,score,_ in baseline["needs"][:5]]
        reasons=[(reason,1) for _,_,reason in baseline["needs"][:4]]
        concerns=[(name,1) for name,_ in baseline["concerns"][:5]]
        improvements=[(reason,1) for _,reason in baseline["concerns"][:5]]
        competitors=[(row[0],1) for row in baseline["competitors"][:5]]
        dimensions=[]
    else:
        needs=reasons=concerns=improvements=competitors=dimensions=[]
    generic_competitors={"新能源车","新能源车型","新能源汽车","新势力","新势力车型","新能源替代车型","同级别车型","同价位竞品","竞品","其他竞品"}
    competitors=[(name,count) for name,count in competitors if str(name).strip() not in generic_competitors and not str(name).strip().endswith("替代车型")]
    mode_note="基于 DeepSeek 已分析材料统计，刷新页面不会重复调用 API。" if ai_ready else "当前为原文资料的基础提炼结果；点击上方“一键生成AI报告”后生成语义归纳。"
    st.markdown(f'<div id="user-needs" class="section-anchor"></div><div class="user-section-title">◈ 核心需求排序</div><div class="user-section-note">{mode_note}</div>',unsafe_allow_html=True)
    if needs:
        raw_material_text="\n".join(material_rows.get("用户原文",pd.Series(dtype=str)).dropna().astype(str).tolist())
        need_terms={
            "空间与乘坐舒适":["空间","后排","座椅","舒适","静谧","底盘"],"空间舒适":["空间","后排","座椅","舒适","静谧","底盘"],
            "价格权益":["价格","优惠","权益","预算","性价比"],"使用成本":["能耗","油耗","保养","保险","成本"],
            "补能与续航":["补能","续航","充电","长途","增程"],"智能体验":["智驾","智能","车机","座舱","语音"],
            "家庭出行适配":["家庭","孩子","老人","全家","出行"],"品牌与品质":["品牌","品质","可靠","豪华","质量"],
        }
        mentions=[]
        for name,count in needs[:5]:
            terms=need_terms.get(str(name),[str(name)])
            mentions.append(int(count) if st.session_state.get("_source_document") else max(1,keyword_score(raw_material_text,terms)))
        max_mentions=max(mentions or [1])
        reason_rules={
            "空间":"商务接待与家庭出行都重视后排空间、静谧性和底盘舒适度",
            "价格":"用户会把成交权益、配置获得感和长期成本放在一起判断",
            "成本":"补能、能耗和后期使用费用直接影响长期持有判断",
            "补能":"城市通勤便利性与长途无焦虑共同决定能源方案接受度",
            "智能":"车机流畅度、辅助驾驶和座舱交互会被用户与竞品直接比较",
            "家庭":"儿童、老人和多人乘坐场景决定空间配置与舒适需求",
            "品牌":"品牌信任、可靠性与豪华感共同影响最终选择",
        }
        ranked_needs=sorted(zip(needs[:5],mentions),key=lambda item:item[1],reverse=True)
        rows=[]
        for index,((name,_),mention_count) in enumerate(ranked_needs,1):
            score=round(6+4*(mention_count/max_mentions),1)
            rank_value=f"{mention_count} 位受访者" if st.session_state.get("_source_document") else f"{score:.1f}分｜{mention_count}次提及"
            reason=None if st.session_state.get("_source_document") else next((value for keyword,value in reason_rules.items() if keyword in str(name)),None)
            if st.session_state.get("_source_document"):
                related=cache_rows[cache_rows.apply(lambda row:str(name) in dsui._json_list(row.get("核心需求",[])),axis=1)]
                related_reasons=dsui.aggregate_top(related,"关注理由",1)
                reason=str(related_reasons[0][0]) if related_reasons else "材料未提供明确的关注原因"
            elif not reason and index-1<len(reasons): reason=str(reasons[index-1][0])
            reason=reason or "该需求在当前用户材料中多次参与选择判断"
            rows.append(f'<div class="user-rank-row"><div class="user-rank-no">{index}</div><div class="user-rank-head"><div class="user-rank-name">{html.escape(str(name))}</div><div class="user-rank-value">{rank_value}</div></div><div class="user-rank-detail"><b>关注原因：</b>{html.escape(reason)}</div></div>')
        st.markdown(f'<div class="user-rank-stack">{"".join(rows)}</div>',unsafe_allow_html=True)
    else: _render_ai_empty("尚无分析结果。上传或补充原文材料后，点击上方“一键生成AI报告”。")
    st.markdown('<div id="user-concerns" class="section-anchor"></div><div class="user-section-title">◈ 顾虑点 / 提升空间</div>',unsafe_allow_html=True)
    if concerns:
        def concern_action(name,fallback):
            text=str(name)
            rules=[
                (("智能","智驾","车机"),"通过实车演示说明车机、智驾能力与使用边界，并给出升级计划。"),
                (("品质","售后","维修","可靠"),"用质保政策、维修成本和售后覆盖数据降低长期使用顾虑。"),
                (("价格","权益","预算"),"拆解成交价、金融权益与全周期成本，建立清晰的价值锚点。"),
                (("后排","隔音","底盘","舒适"),"安排后排试乘和典型路况体验，用可感知体验替代参数描述。"),
                (("补能","续航","能耗"),"结合通勤与长途场景测算补能频次、能耗和真实使用成本。"),
                (("产品力","差异"),"围绕高频使用场景制作本品与明确竞品的逐项体验对比。"),
            ]
            for keywords,action in rules:
                if any(word in text for word in keywords): return action
            return fallback or "围绕该顾虑补充体验、证据和价值说明。"
        action_cards=[]
        for i,(name,count) in enumerate(concerns[:4]):
            fallback=improvements[i][0] if i<len(improvements) else ""
            action=concern_action(name,fallback)
            action_cards.append(f'<div class="user-action-card"><div class="user-action-label">顾虑 {i+1} · {count} 次提及</div><div class="user-action-title">{html.escape(name)}</div><div class="user-action-text"><b>建议动作：</b>{html.escape(action)}</div></div>')
        st.markdown(f'<div class="user-action-grid">{"".join(action_cards)}</div>',unsafe_allow_html=True)
    else: _render_ai_empty("当前缓存中尚无可统计的顾虑点与提升空间。")
    st.markdown('<div id="user-competitors" class="section-anchor"></div><div class="user-section-title">◈ 竞品比较关系</div>',unsafe_allow_html=True)
    if competitors:
        cards=[]
        baseline_map={row[0]:row for row in (baseline.get("competitors",[]) if baseline else [])}
        for name,count in competitors[:5]:
            public=None if st.session_state.get("_source_document") else public_competitor_profile(name)
            if ai_ready:
                mask=cache_rows.apply(lambda row:name in dsui.list_values(pd.DataFrame([row]),"提及竞品"),axis=1)
                related=cache_rows.loc[mask]
                compare_values=dsui.aggregate_top(related,"比较维度",3) if not related.empty else []
                advantage_values=dsui.aggregate_top(related,"选择竞品原因",2) if not related.empty else []
                advantage_values=[(item,n) for item,n in advantage_values if not any(word in item for word in ["新能源车","新势力","新能源替代车型","同级别车型"])]
                material_compare="、".join(item for item,_ in compare_values)
                material_advantage="；".join(item for item,_ in advantage_values)
            else:
                row=baseline_map.get(name)
                material_compare=row[1] if row else ""
                material_advantage=row[3] if row else ""
            compare_text=material_compare or (public or {}).get("比较点") or "产品体验、价格与使用场景"
            advantage_text=material_advantage or "当前材料仅识别到比较关系，尚未形成稳定的独立优势判断"
            supplement=""
            if public:
                supplement=(f'<div class="user-competitor-line"><b>公开口碑补充</b>{html.escape(public["竞品优势"])}'
                            f'<div class="small-note" style="margin-top:6px"><a href="{html.escape(public["链接"])}" target="_blank" style="color:#7FC4F5">来源：{html.escape(public["来源"])}</a></div></div>')
            cards.append(f'<div class="user-competitor-card"><div class="user-competitor-name">{html.escape(name)} <span class="small-note">{count} 次提及</span></div><div class="user-competitor-line"><b>用户主要比较点</b>{html.escape(compare_text)}</div><div class="user-competitor-line"><b>材料中的竞品优势</b>{html.escape(advantage_text)}</div>{supplement}</div>')
        st.markdown(f'<div class="user-competitor-cards">{"".join(cards)}</div>',unsafe_allow_html=True)
    else: _render_ai_empty("当前缓存中尚未识别到稳定的竞品比较关系。")
    scripts=[value for value in cache_rows.get("沟通话术建议",pd.Series(dtype=str)).dropna().astype(str).tolist() if value and value!="未知"]
    if not scripts and baseline and needs and concerns:
        scripts=[f'先围绕“{needs[0][0]}”确认用户的高频使用场景，再结合实车体验建立产品价值。',
                 f'针对“{concerns[0][0]}”主动说明使用条件、权益与长期成本，避免顾虑延后到成交阶段。',
                 '将竞品参数比较转成通勤、家庭出行和长途三类真实场景的逐项体验。']
    with st.container(border=True):
        render_help_title("◈ 沟通话术建议","将需求、顾虑与竞品比较转化为可直接使用的沟通动作。","user-scripts")
        if scripts:
            highlight_terms=[str(item[0]) for item in (needs[:3]+concerns[:2])]
            def script_markup(text):
                escaped=html.escape(str(text))
                for term in highlight_terms:
                    if term:
                        escaped=escaped.replace(html.escape(term),f'<b style="color:#FFD166">{html.escape(term)}</b>')
                return escaped
            script_cards="".join(f'<div class="user-script-card"><div class="user-script-stage">建议 {i}</div><div class="user-script-text">{script_markup(text)}</div></div>' for i,text in enumerate(dict.fromkeys(scripts[:4]),1))
            st.markdown(f'<div class="user-script-grid">{script_cards}</div>',unsafe_allow_html=True)
        else: _render_ai_empty("当前尚无可展示的沟通建议；已分析资料可能未提供足够依据。")
    with st.container(border=True):
        render_help_title("◈ 用户实评","保留用户真实表达，便于核对结论并捕捉可用于传播与销售的话语。","user-reviews")
        evidence_rows=[]
        if not cache_rows.empty:
            for _,row in cache_rows.head(5).iterrows():
                tags=dsui.list_values(pd.DataFrame([row]),"核心需求")[:3]
                quote=str(row.get("典型原文","") or row.get("用户原文","") or "")
                evidence_rows.append((quote,f'{row.get("来源类型","未知")} · {row.get("来源平台","未知")}'," · ".join(tags)))
        elif not material_rows.empty:
            for _,row in material_rows.head(5).iterrows():
                quote=str(row.get("用户原文","") or "")
                evidence_rows.append((quote,f'{row.get("来源类型","未知")} · {row.get("来源平台","未知")}',""))
        if evidence_rows:
            quote_key=f'user_quote_index_{norm_search(str(target.get("query",target.get("车系","target"))))}'
            current_index=int(st.session_state.get(quote_key,0))%len(evidence_rows)
            left_arrow,quote_col,right_arrow=st.columns([.55,5.9,.55],vertical_alignment="center")
            with left_arrow:
                if st.button("←",key=f'{quote_key}_prev',use_container_width=True):
                    st.session_state[quote_key]=(current_index-1)%len(evidence_rows); st.rerun()
            quote,meta,tags=evidence_rows[current_index]
            with quote_col:
                tags_html=f'<div class="tags">{html.escape(tags)}</div>' if tags else ""
                st.markdown(f'<div class="user-quote-single"><div class="user-quote-text">“{html.escape(quote)}”</div><div class="user-quote-meta">{html.escape(meta)}</div>{tags_html}</div><div class="user-quote-count">{current_index+1} / {len(evidence_rows)}</div>',unsafe_allow_html=True)
            with right_arrow:
                if st.button("→",key=f'{quote_key}_next',use_container_width=True):
                    st.session_state[quote_key]=(current_index+1)%len(evidence_rows); st.rerun()
        else: _render_ai_empty("当前暂无可展示的用户原文。")
def build_strategy_context(target,brands,series_filter,regions,prices,energies,bodies,execution_roles=None):
    target_rows=filter_target_rows_for_context(target["matched_rows"],brands=brands,series_filter=series_filter,prices=prices,energies=energies,bodies=bodies)
    if target_rows.empty: target_rows=target["matched_rows"].copy()
    target_names=target_rows["分析对象名称"].astype(str).unique().tolist()
    selected_energy_groups=unique_list([energy_group(item) for item in energies],ENERGY_GROUP_OPTIONS)
    benchmark="全国" if "全国" in regions else regions[0]
    market_scope=filter_market_data(regions=regions,prices=prices,energy_groups=selected_energy_groups,bodies=bodies)
    target_scope=filter_target_data(regions=regions,prices=prices,energies=energies,bodies=bodies,names=target_names,brands=brands,series_filter=series_filter)
    market_region=market_scope[market_scope["地区"]==benchmark].copy()
    target_region=target_scope[target_scope["地区"]==benchmark].copy()
    market_month=market_region.groupby("月份序号")["销量"].sum()
    target_month=target_region.groupby("月份序号")["销量"].sum()
    recent_market=float(market_month.reindex(RECENT_PERIOD_INDEXES,fill_value=0).mean())
    previous_market=float(market_month.reindex(PREVIOUS_PERIOD_INDEXES,fill_value=0).mean())
    market_growth=recent_market/previous_market-1 if previous_market else 0
    latest_market=float(market_month.get(LAST_PERIOD_INDEX,0))
    latest_target=float(target_month.get(LAST_PERIOD_INDEX,0))
    latest_share=latest_target/latest_market if latest_market else 0
    region_shares={}
    for region in regions:
        m=market_scope[(market_scope["地区"]==region)&(market_scope["月份序号"]==LAST_PERIOD_INDEX)]["销量"].sum()
        t=target_scope[(target_scope["地区"]==region)&(target_scope["月份序号"]==LAST_PERIOD_INDEX)]["销量"].sum()
        region_shares[region]=float(t/m) if m else 0
    regional_signal=""
    regional_gaps=[]
    if len(region_shares)>1:
        comparison=max((item for item in region_shares if item!=benchmark),key=lambda item:region_shares[item],default="")
        if comparison:
            gap=(region_shares[comparison]-region_shares[benchmark])*100
            regional_signal=f'{comparison}目标份额较{benchmark}{gap:+.2f}pct'
        for region, share in region_shares.items():
            if region != benchmark:
                regional_gaps.append({"地区":region,"目标份额":round(share,4),"较基准":round((share-region_shares.get(benchmark,0))*100,2)})

    price_signals=[]
    for price in prices:
        m=float(market_scope[(market_scope["价格段"]==price)&(market_scope["地区"]==benchmark)&(market_scope["月份序号"]==LAST_PERIOD_INDEX)]["销量"].sum())
        t=float(target_scope[(target_scope["价格段"]==price)&(target_scope["地区"]==benchmark)&(target_scope["月份序号"]==LAST_PERIOD_INDEX)]["销量"].sum())
        if m:
            price_signals.append({"价格段":price,"目标份额":round(t/m,4),"市场销量":round(m)})
    price_signals.sort(key=lambda row:(row["目标份额"],row["市场销量"]),reverse=True)

    is_brand_query=target.get("is_brand_query",False)
    # 策略页的竞争判断应覆盖同一市场口径内的全部竞品；品牌与车系筛选只用于
    # 明确本品分析对象，不能把竞争市场收窄为本品品牌内部。
    sales_scope=competitor_sales_scope(target,regions,prices,energies,bodies,None,None,False)
    cr_df=concentration_table(sales_scope,target,is_brand_query,regions) if not sales_scope.empty else pd.DataFrame()
    tiers=classify_competitors(sales_scope,target,is_brand_query,regions) if not sales_scope.empty else pd.DataFrame()
    cr_row=cr_df[cr_df["地区"]==benchmark].iloc[0] if not cr_df.empty and benchmark in set(cr_df["地区"]) else (cr_df.iloc[0] if not cr_df.empty else None)
    core_rows=tiers[tiers["竞品层级"]=="核心竞品"].head(4) if not tiers.empty else pd.DataFrame()
    core_names=core_rows["竞品对象"].astype(str).tolist() if not core_rows.empty else []
    core_profiles=[]
    for _,row in core_rows.iterrows():
        core_profiles.append({"竞品":str(row.get("竞品对象","")),"竞争表现":str(row.get("竞争表现",row.get("入选原因",""))).replace("|||","；")[:220]})
    defense=""
    if not tiers.empty:
        core=tiers[tiers["竞品层级"]=="核心竞品"].head(1)
        if not core.empty: defense=str(core.iloc[0].get("竞争表现",core.iloc[0].get("入选原因",""))).replace("|||","；")

    survey_all,_,_=dsui.load_source_table("survey",None)
    material_all,_,_=dsui.load_source_table("materials",None)
    survey_rows=dsui.filter_for_target(survey_all,target)
    material_rows=dsui.filter_for_target(material_all,target)
    profile=build_survey_profile(target,survey_rows) if not survey_rows.empty else None
    cache_rows=dsui.cache_for_materials(material_rows)
    if not cache_rows.empty:
        needs=dsui.aggregate_top(cache_rows,"核心需求",5)
        concerns=dsui.aggregate_top(cache_rows,"顾虑点",5)
        user_competitors=dsui.aggregate_top(cache_rows,"提及竞品",5)
        scripts=[item for item in cache_rows.get("沟通话术建议",pd.Series(dtype=str)).dropna().astype(str).tolist() if item and item!="未知"]
    elif not material_rows.empty:
        baseline=analyze_user_material(target,"\n".join(material_rows["用户原文"].astype(str)),False)
        needs=[(name,score) for name,score,_ in baseline["needs"]]
        concerns=[(name,1) for name,_ in baseline["concerns"]]
        user_competitors=[(row[0],1) for row in baseline["competitors"]]
        scripts=[]
    else:
        needs=concerns=user_competitors=[]; scripts=[]
    generic={"新能源车","新能源车型","新能源汽车","新势力","新势力车型","新能源替代车型","同级别车型","同价位竞品","竞品"}
    user_competitors=[(name,count) for name,count in user_competitors if name not in generic]
    return {
        "目标车型":target.get("车系",target.get("query","当前目标")),"分析口径":{"地区":regions,"价格段":prices,"能源":selected_energy_groups,"车身":bodies},
        "市场摘要":{"基准地区":benchmark,"近三月市场变化":round(market_growth,4),"目标近月份额":round(latest_share,4),"近三月月均销量":round(recent_market),"区域信号":regional_signal,"区域差异":regional_gaps,"价格段表现":price_signals,"价格范围":target_price_range(target,prices),"目标能源":target.get("能源大类",""),"目标车身":target.get("车身形式","")},
        "竞争摘要":{"CR3":round(float(cr_row["CR3"]),4) if cr_row is not None else None,"CR5":round(float(cr_row["CR5"]),4) if cr_row is not None else None,"本品位置":str(cr_row["本品头部位置"]) if cr_row is not None else "暂无排名","核心竞品":core_names,"核心竞品表现":core_profiles,"攻防信号":defense[:180]},
        "用户摘要":{"画像":profile["persona"] if profile else "样本不足","画像关键词":profile["keywords"] if profile else {},"核心需求":[name for name,_ in needs[:3]],"主要顾虑":[name for name,_ in concerns[:3]],"高频对比竞品":[name for name,_ in user_competitors[:3]],"沟通抓手":scripts[:2],"问卷样本数":len(survey_rows),"原文材料数":len(material_rows)},
        "执行配置":execution_roles or {"最终策略目标":"提升目标细分市场转化","参与角色":[]},
    }


def build_rule_strategy(context):
    market=context["市场摘要"]; competition=context["竞争摘要"]; user=context["用户摘要"]
    target=context["目标车型"]
    final_goal=context.get("执行配置",{}).get("最终策略目标") or "提升目标细分市场的有效触达、试驾与成交转化"
    need=(user["核心需求"] or ["核心使用场景"])[0]
    concern=(user["主要顾虑"] or ["价值解释"])[0]
    core_competitors="、".join(competition["核心竞品"][:2]) or "头部竞品"
    growth=float(market["近三月市场变化"] or 0); cr5=competition["CR5"]
    market_name=f'{market["价格范围"]}{market["目标能源"]}{market["目标车身"]}'
    market_judgment="承接增长需求" if growth>=.03 else "争夺存量份额" if growth<0 else "把握结构性需求"
    concentration="竞争相对分散" if cr5 is not None and cr5<.45 else "头部竞争已形成" if cr5 is not None else "竞争格局待验证"
    persona=user.get("画像") or "核心目标用户"
    conclusion=f'为实现“{final_goal}”，{target}应聚焦{persona}，在{market_name}市场{market_judgment}，发挥“{need}”体验优势，并通过场景化获客、对比试驾和竞品攻防推动销量增长。'
    best_price=(market.get("价格段表现") or [{}])[0]
    price_evidence=(f'{best_price.get("价格段")}市场目标近月份额 {best_price.get("目标份额",0):.2%}、市场销量 {best_price.get("市场销量",0):,} 辆；' if best_price else "")
    market_evidence=f'{price_evidence}近三月细分市场月均 {market["近三月月均销量"]:,} 辆、较此前三个月 {growth:+.1%}；目标整体近月份额 {market["目标近月份额"]:.2%}。'
    if market["区域信号"]: market_evidence+=f' {market["区域信号"]}。'
    core_detail=(competition.get("核心竞品表现") or [{}])[0]
    cr_evidence=(f'{market["基准地区"]}CR3为 {competition["CR3"]:.2%}、CR5为 {cr5:.2%}，{competition["本品位置"]}；核心竞品{core_detail.get("竞品",core_competitors)}：{core_detail.get("竞争表现",competition.get("攻防信号","需重点跟踪"))}。' if cr5 is not None else "当前口径暂缺足够竞品样本。")
    user_evidence=f'{user["画像"]}为主要画像；核心需求为“{need}”，主要顾虑为“{concern}”。'
    opportunities=[
        {"机会类型":"市场机会","机会名称":f'{market_name}{market_judgment}',"关键依据":market_evidence,"落地建议":"将资源优先投向份额提升空间更大的地区与主力价格带，组织区域专项传播、试驾和门店活动。"},
        {"机会类型":"竞争机会","机会名称":f'{concentration}，围绕{core_competitors}建立攻防',"关键依据":cr_evidence,"落地建议":f'针对{core_competitors}制作产品对比卡和销售攻防话术，以本品强项组织对比试驾，并对竞品优势设置专项回应。'},
        {"机会类型":"用户转化机会","机会名称":f'以“{need}”驱动体验转化',"关键依据":user_evidence,"落地建议":f'围绕真实使用场景制作内容、设计试驾动线并前置回应“{concern}”，用留资、到店和试驾转化验证效果。'},
    ]
    strategies=[{"策略名称":"区域与场景双线突破","策略目标":final_goal,"策略路径":f'聚焦{persona}与高潜地区，以“{need}”为价值主线并对{core_competitors}建立攻防。'}]
    stages=[{"阶段":"预热期","时间":"上市前4-2周","阶段目标":"完成新品预热、销售作战计划、首轮用户触达与产品培训"},{"阶段":"上市期","时间":"上市前1周至上市周","阶段目标":"集中完成专家邀约、到店体验、试驾与首批订单转化"},{"阶段":"转化期","时间":"上市后1-4周","阶段目标":"通过门店运营、日常追盯和用户跟进持续扩大成交"},{"阶段":"复盘期","时间":"上市后5-6周","阶段目标":"总结上市成效、识别转化瓶颈并更新后续运营动作"}]
    roles=context.get("执行配置",{}).get("参与角色") or [{"角色":"GTM","职责":"策略统筹"},{"角色":"市场/内容","职责":"传播物料"},{"角色":"销售/门店","职责":"试驾成交"},{"角色":"数据分析","职责":"监测复盘"}]
    task_templates={"GTM":("制定新品上市作战计划并统筹竞品攻防与阶段推进","预热期","转化期","上市作战手册与周追踪清单","里程碑完成率"),"市场/内容":(f'完成{need}场景预热海报、短视频、上市传播与常态内容',"预热期","转化期","预热及上市传播素材包","内容互动与有效留资数"),"销售/门店":(f'完成产品培训、门店展陈、专家邀约、试驾和订单跟进，回应{concern}',"预热期","转化期","培训记录、活动台账与订单跟进表","培训通过率、到店率、试驾率和成交率"),"用户运营":("预热触达潜客，上市期集中邀约，上市后持续跟进竞品摇摆用户","预热期","转化期","用户分层、触达与复访记录","触达率、邀约到店率和复访转化率"),"数据分析":("建立上市指标看板，日常追盯线索与订单并完成上市复盘","预热期","复盘期","上市看板、日报与复盘报告","各环节转化率及目标达成率"),"产品":("完成新品卖点、产品培训和核心顾虑答疑支持","预热期","上市期","产品培训课件与答疑手册","培训覆盖率和销售使用率")}
    tasks=[]
    for role in roles:
        name=role.get("角色","参与角色"); default=task_templates.get(name,(f'依据“{role.get("职责","协同执行")}”完成新品上市专项任务',"预热期","转化期","专项交付物","任务完成率"))
        tasks.append({"角色":name,"任务":default[0],"开始阶段":default[1],"结束阶段":default[2],"交付物":default[3],"衡量指标":default[4]})
    return {"主结论":conclusion,"关键机会点":opportunities,"核心策略":strategies,"阶段计划":stages,"角色任务":tasks}


def render_strategy_onepager(target,filters):
    st.markdown("""
    <style>
    .strategy-section-title{margin:26px 0 12px;color:#F5F9FF;font-size:24px;font-weight:950;letter-spacing:.01em}
    .strategy-verdict{position:relative;padding:26px 28px;border-radius:20px;overflow:hidden;background:radial-gradient(circle at 92% 10%,rgba(82,126,255,.28),transparent 34%),linear-gradient(135deg,#18365b,#0b1d34);border:1px solid rgba(113,178,244,.42);box-shadow:0 18px 42px rgba(0,0,0,.20)}.strategy-verdict:after{content:"";position:absolute;right:-32px;top:-42px;width:180px;height:180px;border:1px solid rgba(124,192,255,.18);border-radius:50%}.strategy-kicker{color:#79C3FF;font-size:12px;font-weight:950;letter-spacing:.08em}.strategy-verdict-text{position:relative;z-index:1;margin:10px 0 19px;color:#fff;font-size:24px;font-weight:950;line-height:1.58;width:100%;padding-right:24px}.strategy-tags{display:flex;gap:9px;flex-wrap:wrap}.strategy-tags span{padding:7px 11px;border-radius:999px;background:rgba(86,143,222,.20);border:1px solid rgba(115,185,246,.31);color:#DDEEFF;font-size:12px;font-weight:800}
    .strategy-opportunity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}.strategy-opportunity{min-height:245px;padding:20px;border-radius:18px;background:linear-gradient(145deg,#132c4a,#0b1d33);border:1px solid #31557a}.strategy-opportunity.market{border-top:3px solid #58A6FF}.strategy-opportunity.competition{border-top:3px solid #F4B04F}.strategy-opportunity.user{border-top:3px solid #58D5B0}.strategy-opportunity-head{display:flex;align-items:center;gap:8px;color:#9CCBFF;font-size:12px;font-weight:950}.strategy-opportunity.competition .strategy-opportunity-head{color:#FFD184}.strategy-opportunity.user .strategy-opportunity-head{color:#7EE4C4}.strategy-opportunity-head span{font-size:19px}.strategy-opportunity-name{margin:14px 0 16px;color:#fff;font-size:18px;font-weight:950;line-height:1.45}.strategy-opportunity-line{padding:11px 0;border-top:1px solid rgba(255,255,255,.08);color:#C8DAED;font-size:13px;line-height:1.65}.strategy-opportunity-line b{display:block;margin-bottom:4px;color:#7DAEDF;font-size:11px}.strategy-opportunity-line.meaning b{color:#70D7B8}
    .strategy-role-setup{margin:10px 0 15px;padding:14px 17px;border-radius:15px;background:rgba(16,39,67,.68);border:1px solid rgba(91,150,211,.25)}.strategy-role-note{color:#91AAC5;font-size:11px;line-height:1.6}
    .strategy-core-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.strategy-core-card{min-height:128px;padding:20px;border-radius:16px;background:linear-gradient(145deg,#17375C,#0D213A);border-left:4px solid #5EA9F2;text-align:center;display:flex;flex-direction:column;justify-content:center}.strategy-core-card b{display:block;color:#fff;font-size:17px}.strategy-core-card span{display:block;margin-top:8px;color:#9FC0DE;font-size:12px;line-height:1.55}.strategy-core-card p{margin:10px 0 0;color:#D7E5F4;font-size:13px;line-height:1.65}
    .strategy-stage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.strategy-stage-card{padding:14px;border-radius:14px;background:#102943;border:1px solid rgba(101,163,225,.25)}.strategy-stage-card b{color:#fff;font-size:14px}.strategy-stage-card span{float:right;color:#75BDFC;font-size:10px;font-weight:800}.strategy-stage-card p{margin:8px 0 0;color:#BFD2E5;font-size:11px;line-height:1.55}
    .strategy-role-gantt{margin-top:14px;padding:17px;border-radius:18px;background:linear-gradient(145deg,#0E223B,#09182B);border:1px solid rgba(101,163,225,.28);overflow-x:auto}.strategy-gantt-grid{display:grid;grid-template-columns:145px repeat(4,minmax(175px,1fr));gap:7px;min-width:900px}.strategy-gantt-head{padding:9px 8px;text-align:center;color:#91ABCA;font-size:11px;font-weight:900}.strategy-gantt-head:first-child{text-align:left}.strategy-role-label{padding:11px 8px;color:#fff;font-size:13px;font-weight:950;border-top:1px solid rgba(255,255,255,.07)}.strategy-task-track{grid-column:2/6;display:grid;grid-template-columns:repeat(4,1fr);gap:7px;align-items:center;min-height:66px;border-top:1px solid rgba(255,255,255,.07)}.strategy-task-bar{min-height:49px;padding:8px 10px;border-radius:11px;background:linear-gradient(90deg,#2D70C9,#3158B8);border:1px solid rgba(133,194,255,.38);color:#fff}.strategy-task-bar.alt1{background:linear-gradient(90deg,#248579,#267B9E)}.strategy-task-bar.alt2{background:linear-gradient(90deg,#A7672D,#C38336)}.strategy-task-bar.alt3{background:linear-gradient(90deg,#6753B5,#795CCB)}.strategy-task-bar b{display:block;font-size:11px;line-height:1.35}.strategy-task-bar span{display:block;margin-top:4px;color:#D3E4F7;font-size:9px;line-height:1.35}.strategy-gantt-legend{margin-top:10px;color:#7994B2;font-size:10px}
    .strategy-timeline{padding:18px;border-radius:18px;background:linear-gradient(145deg,#0E223B,#09182B);border:1px solid rgba(101,163,225,.28)}.strategy-week-head,.strategy-timeline-row{display:grid;grid-template-columns:130px repeat(6,minmax(70px,1fr));gap:7px}.strategy-week-head{padding-bottom:10px;color:#809AB7;font-size:11px;text-align:center}.strategy-week-head span:first-child{text-align:left}.strategy-timeline-row{align-items:center;min-height:67px;border-top:1px solid rgba(255,255,255,.06)}.strategy-stage-name{color:#fff;font-size:14px;font-weight:950}.strategy-stage-name small{display:block;margin-top:4px;color:#89A5C3;font-size:10px;font-weight:700}.strategy-stage-bar{align-self:center;min-height:45px;padding:8px 12px;border-radius:12px;color:#fff;box-shadow:0 8px 20px rgba(0,0,0,.16)}.strategy-stage-bar b{display:block;font-size:13px}.strategy-stage-bar span{display:block;margin-top:3px;font-size:10px;color:rgba(255,255,255,.83);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.strategy-stage-bar.s1,.strategy-plan-card.s1{background:linear-gradient(90deg,#3278D2,#436FEA)}.strategy-stage-bar.s2,.strategy-plan-card.s2{background:linear-gradient(90deg,#217F87,#2AAE9A)}.strategy-stage-bar.s3,.strategy-plan-card.s3{background:linear-gradient(90deg,#B56B29,#E99C3C)}.strategy-stage-bar.s4,.strategy-plan-card.s4{background:linear-gradient(90deg,#6655B8,#8B6EE8)}
    .strategy-plan-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px;margin-top:12px}.strategy-plan-card{position:relative;min-height:205px;padding:17px;border-radius:16px;color:#fff;overflow:hidden}.strategy-plan-card:after{content:"";position:absolute;inset:3px;border-radius:13px;background:rgba(7,22,39,.80);z-index:0}.strategy-plan-card>div{position:relative;z-index:1}.strategy-plan-top{display:flex;justify-content:space-between;gap:8px;align-items:center}.strategy-plan-top b{font-size:16px}.strategy-plan-top span{font-size:11px;color:#BBD4F2}.strategy-plan-owner{margin:10px 0;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.12);color:#9FBBD8;font-size:11px;line-height:1.5}.strategy-plan-goal,.strategy-plan-action{font-size:12px;line-height:1.65;margin-top:8px}.strategy-plan-goal{color:#fff}.strategy-plan-action{color:#C8D9EA}.strategy-footnote{margin:11px 0 2px;text-align:right;color:#708AA7;font-size:10px}
    .strategy-confirm{margin:16px 0 12px;padding:19px 21px;border-radius:18px;background:linear-gradient(145deg,#132C4A,#0B1D33);border:1px solid rgba(104,166,226,.32)}.strategy-confirm-title{color:#fff;font-size:18px;font-weight:950}.strategy-confirm-note{margin-top:5px;color:#9CB4CF;font-size:12px;line-height:1.65}.strategy-confirm-scope{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.strategy-confirm-scope span{padding:6px 10px;border-radius:9px;background:rgba(72,125,188,.20);border:1px solid rgba(104,166,226,.22);color:#DCEBFA;font-size:11px;font-weight:800}.strategy-result-status{margin:12px 0;padding:11px 14px;border-radius:12px;background:rgba(36,82,132,.22);border-left:3px solid #62ACF5;color:#BDD4EC;font-size:11px}.strategy-result-status b{color:#fff}.strategy-placeholder{filter:blur(3px);opacity:.25;pointer-events:none;user-select:none}.strategy-placeholder-card{height:126px;border-radius:18px;background:linear-gradient(145deg,#18365B,#0B1D34);margin:13px 0}.strategy-placeholder-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:13px}.strategy-placeholder-grid span{height:188px;border-radius:17px;background:#17304E}.strategy-waiting-note{margin:14px 0 4px;text-align:center;color:#9CB4CF;font-size:13px}
    @media(max-width:1050px){.strategy-opportunity-grid,.strategy-core-grid{grid-template-columns:1fr}.strategy-stage-grid{grid-template-columns:1fr 1fr}}@media(max-width:700px){.strategy-stage-grid{grid-template-columns:1fr}.strategy-verdict-text{font-size:20px}}
    </style>
    """,unsafe_allow_html=True)
    brands,series_filter,regions,prices,energies,bodies=filters
    role_defaults={"GTM":"策略统筹、机会判断与跨部门协同","市场/内容":"线上传播、内容与物料制作","销售/门店":"线下展陈、邀约、试驾与成交","用户运营":"用户分层、触达与复访","数据分析":"指标监控、归因与策略复盘","产品":"产品价值证据与顾虑答疑"}
    role_base=list(role_defaults)
    target_token=norm_search(str(target.get("query",target.get("车系","target"))))
    st.markdown('<div class="strategy-help-overlay"><span class="mini-help" data-tooltip="选择本次参与执行的角色并明确职责，系统会据此拆分阶段任务；目标、角色或职责变化后会形成新的缓存口径。">&#128279;&#65038;</span></div>',unsafe_allow_html=True)
    with st.expander("设置策略目标与参与角色",expanded=False):
        strategy_goal=st.text_input("最终策略目标",value="提升目标细分市场的有效触达、试驾与成交转化",key=f'strategy_goal_{target_token}')
        custom_roles_text=st.text_input("新增自定义角色（多个角色用顿号或逗号分隔）",placeholder="例如：区域营销、经销商、交付",key=f'custom_strategy_roles_{target_token}')
        custom_roles=[item.strip() for item in re.split(r'[、,，]+',custom_roles_text) if item.strip()]
        role_options=list(dict.fromkeys(role_base+custom_roles))
        selected_roles=st.multiselect("参与角色",role_options,default=[item for item in ["GTM","市场/内容","销售/门店","数据分析"] if item in role_options],max_selections=8,key=f'selected_strategy_roles_v3_{target_token}')
        if not selected_roles: selected_roles=["GTM"]
        role_responsibilities=[]
        role_cols=st.columns(2)
        for index,role in enumerate(selected_roles):
            with role_cols[index%2]:
                duty=st.text_input(f'{role}主要工作',value=role_defaults.get(role,"根据策略目标承担专项执行任务"),key=f'role_duty_v2_{target_token}_{norm_search(role)}')
                role_responsibilities.append({"角色":role,"职责":duty})
    execution_roles={"最终策略目标":strategy_goal,"参与角色":role_responsibilities}
    context=build_strategy_context(target,brands,series_filter,regions,prices,energies,bodies,execution_roles)
    context["资料版本"]=source_version()
    rule_result=build_rule_strategy(context)
    cache_record=dstrategy.get_cached_record(context)
    context_signature=dstrategy.cache_key(context)[:12]
    state_key=f'strategy_record_{norm_search(target.get("query",target.get("车系","target")))}_{context_signature}'
    fallback_key=f'strategy_fallback_{context_signature}'
    result_record=st.session_state.get(state_key)
    config=dsui.api_config()
    scope_text=f'{format_options(regions)}｜{target_price_range(target,prices)}｜{format_options(unique_list([energy_group(item) for item in energies],ENERGY_GROUP_OPTIONS))}｜{format_options(bodies)}'
    st.markdown(f'<div class="strategy-confirm"><div class="strategy-confirm-title">确认最终分析目标</div><div class="strategy-confirm-note">请确认目标车型与分析口径。只有点击确认后，系统才会读取同口径缓存或调用 DeepSeek 生成策略结果。</div><div class="strategy-confirm-scope"><span>目标：{html.escape(str(context["目标车型"]))}</span><span>地区：{html.escape(format_options(regions))}</span><span>价格：{html.escape(target_price_range(target,prices))}</span><span>能源：{html.escape(format_options(unique_list([energy_group(item) for item in energies],ENERGY_GROUP_OPTIONS)))}</span><span>车身：{html.escape(format_options(bodies))}</span></div></div>',unsafe_allow_html=True)
    confirm_generate=st.button("确认目标并生成策略",type="primary",use_container_width=True,key=f'confirm_strategy_{context_signature}')
    if confirm_generate:
        if cache_record:
            result_record=cache_record
            st.session_state[state_key]=cache_record
            st.session_state.pop(fallback_key,None)
            st.success("已读取同一分析口径的AI策略缓存，本次未调用API。")
        elif config["api_key"]:
            with st.spinner("正在综合市场、竞争与用户摘要，生成AI策略一页纸……"):
                try:
                    generated=dstrategy.generate_strategy(context)
                    result_record={"result":generated,"model":config["model"],"generated_at":datetime.now().isoformat(),"version":"AI综合版"}
                    st.session_state[state_key]=result_record
                    st.session_state.pop(fallback_key,None)
                    st.success("AI综合版策略一页纸已生成并缓存。")
                except Exception as exc:
                    st.session_state[fallback_key]=str(exc)
        else:
            result_record={"result":rule_result,"model":"预设分析逻辑","generated_at":datetime.now().isoformat(),"version":"基础版"}
            st.session_state[state_key]=result_record
            st.success("基础版策略已生成。当前未启用在线 AI。")
    if st.session_state.get(fallback_key) and not result_record:
        st.warning(f'{st.session_state[fallback_key]} 当前尚未展示策略结果。')
        fallback_col,fallback_note=st.columns([1.7,4.3],vertical_alignment="center")
        with fallback_col:
            use_basic=st.button("改用基础版",use_container_width=True,key=f'use_basic_{context_signature}')
        with fallback_note:
            st.caption("基础版根据相同摘要和预设分析逻辑生成，可作为API不可用时的参考结果。")
        if use_basic:
            result_record={"result":rule_result,"model":"预设分析逻辑","generated_at":datetime.now().isoformat(),"version":"基础版"}
            st.session_state[state_key]=result_record
            st.session_state.pop(fallback_key,None)
            st.rerun()
    if not result_record:
        st.markdown('<div class="strategy-waiting-note">确认目标与参与角色后，才会展示主结论、关键机会点、核心策略及角色任务图。</div><div class="strategy-placeholder"><div class="strategy-placeholder-card"></div><div class="strategy-placeholder-grid"><span></span><span></span><span></span></div></div>',unsafe_allow_html=True)
        return
    result=dict(result_record.get("result",rule_result) or {})
    # Protect the execution view from legacy/incomplete cache rows.
    for required_key in ("核心策略","阶段计划","角色任务"):
        if not isinstance(result.get(required_key),list) or not result.get(required_key):
            result[required_key]=rule_result[required_key]
    version_name=result_record.get("version") or ("AI综合版" if result_record.get("model") and result_record.get("model")!="预设分析逻辑" else "基础版")
    generated_raw=str(result_record.get("generated_at",datetime.now().isoformat()))
    try: generated_display=datetime.fromisoformat(generated_raw).strftime("%Y年%m月%d日 %H:%M")
    except ValueError: generated_display=generated_raw[:16].replace("T"," ")
    st.markdown(f'<div class="strategy-result-status"><b>✦ {html.escape(version_name)}</b>｜{html.escape(str(context["目标车型"]))}｜{html.escape(scope_text)}｜生成时间：{html.escape(generated_display)}</div>',unsafe_allow_html=True)
    pdf_bytes=build_strategy_onepage_pdf(context["目标车型"],scope_text,version_name,generated_display,result,"市场与竞争销量当前仍为模拟口径；正式经营决策前请使用真实数据复核。")
    download_col,refresh_col=st.columns([1,1])
    with download_col:
        st.download_button("下载策略一页纸（PDF）",pdf_bytes,file_name=f'{context["目标车型"]}_策略一页纸.pdf',mime="application/pdf",use_container_width=True,key=f'download_strategy_{context_signature}')
    with refresh_col:
        with st.expander("重新生成AI综合版"):
            confirm_cost=st.checkbox("确认重新调用API并覆盖当前缓存",key=f'confirm_strategy_cost_{context_signature}')
            if st.button("重新生成",disabled=not confirm_cost or not config["api_key"],use_container_width=True,key=f'regenerate_strategy_{context_signature}'):
                with st.spinner("正在重新生成AI综合版……"):
                    try:
                        regenerated=dstrategy.generate_strategy(context)
                        st.session_state[state_key]={"result":regenerated,"model":config["model"],"generated_at":datetime.now().isoformat(),"version":"AI综合版"}
                        st.success("AI综合版已更新。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
    opportunity_colors={"市场机会":"market","竞争机会":"competition","用户转化机会":"user"}
    tags=[f'市场机会｜近三月 {context["市场摘要"]["近三月市场变化"]:+.1%}',f'竞争空位｜CR5 {context["竞争摘要"]["CR5"]:.1%}' if context["竞争摘要"]["CR5"] is not None else '竞争空位｜待验证',f'核心用户｜{context["用户摘要"]["画像"]}',f'转化抓手｜{(context["用户摘要"]["核心需求"] or ["场景体验"])[0]}']
    st.markdown('<div class="strategy-section-title">◈ 主结论</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="strategy-verdict"><div class="strategy-kicker">最终策略判断</div><div class="strategy-verdict-text">{html.escape(str(result["主结论"]))}</div><div class="strategy-tags">{"".join(f"<span>{html.escape(tag)}</span>" for tag in tags)}</div></div>',unsafe_allow_html=True)
    st.markdown('<div class="strategy-section-title">◈ 关键机会点</div>',unsafe_allow_html=True)
    cards=[]
    icons={"市场机会":"↗","竞争机会":"◎","用户转化机会":"◆"}
    for item in result.get("关键机会点",[])[:3]:
        kind=str(item.get("机会类型","机会")); css=opportunity_colors.get(kind,"market")
        advice=item.get("落地建议",item.get("策略含义",""))
        cards.append(f'<div class="strategy-opportunity {css}"><div class="strategy-opportunity-head"><span>{icons.get(kind,"◆")}</span>{html.escape(kind)}</div><div class="strategy-opportunity-name">{html.escape(str(item.get("机会名称","")))}</div><div class="strategy-opportunity-line"><b>关键依据</b>{html.escape(str(item.get("关键依据","")))}</div><div class="strategy-opportunity-line meaning"><b>落地建议</b>{html.escape(str(advice))}</div></div>')
    st.markdown(f'<div class="strategy-opportunity-grid">{"".join(cards)}</div>',unsafe_allow_html=True)
    st.markdown('<div class="strategy-section-title">◈ 核心策略</div>',unsafe_allow_html=True)
    strategies=result.get("核心策略",[])[:3]
    stages=result.get("阶段计划",[])[:4]
    tasks=result.get("角色任务",[])
    stage_names=[str(item.get("阶段","")) for item in stages]
    stage_index={name:index for index,name in enumerate(stage_names)}
    role_order=[item.get("角色") for item in context.get("执行配置",{}).get("参与角色",[]) if item.get("角色")]
    for task in tasks:
        if task.get("角色") not in role_order: role_order.append(task.get("角色"))
    with st.expander("编辑图表",expanded=False):
        st.caption("直接修改每个角色的任务与起止阶段；新增任务后点击“应用并重绘”即可更新图表。")
        count_key=f"strategy_task_count_{context_signature}"
        st.session_state.setdefault(count_key,max(1,len(tasks)))
        if st.button("＋ 新增任务",key=f"add_strategy_task_{context_signature}"):
            st.session_state[count_key]+=1
            st.rerun()
        edited_tasks=[]
        for row_no in range(st.session_state[count_key]):
            source=tasks[row_no] if row_no<len(tasks) else {}
            st.markdown(f"**任务 {row_no+1}**")
            c1,c2,c3,c4=st.columns([1.1,2.5,1,1])
            role=c1.text_input("角色",value=str(source.get("角色","")),key=f"task_role_{context_signature}_{row_no}",placeholder="例如：销售/门店")
            task_name=c2.text_input("具体任务",value=str(source.get("任务","")),key=f"task_name_{context_signature}_{row_no}",placeholder="例如：组织首批用户到店试驾")
            start_default=stage_index.get(str(source.get("开始阶段","")),0)
            end_default=stage_index.get(str(source.get("结束阶段","")),start_default)
            start_stage=c3.selectbox("开始阶段",stage_names,index=min(start_default,max(0,len(stage_names)-1)),key=f"task_start_{context_signature}_{row_no}") if stage_names else ""
            end_stage=c4.selectbox("结束阶段",stage_names,index=min(max(end_default,start_default),max(0,len(stage_names)-1)),key=f"task_end_{context_signature}_{row_no}") if stage_names else ""
            d1,d2,d3=st.columns([2,2,.6])
            deliverable=d1.text_input("交付物",value=str(source.get("交付物","")),key=f"task_delivery_{context_signature}_{row_no}",placeholder="例如：试驾名单与跟进记录")
            metric=d2.text_input("衡量指标",value=str(source.get("衡量指标","")),key=f"task_metric_{context_signature}_{row_no}",placeholder="例如：到店率、试驾率、订单率")
            remove=d3.checkbox("删除",key=f"task_remove_{context_signature}_{row_no}")
            if role.strip() and task_name.strip() and not remove:
                edited_tasks.append({"角色":role.strip(),"任务":task_name.strip(),"开始阶段":start_stage,"结束阶段":end_stage,"交付物":deliverable.strip(),"衡量指标":metric.strip()})
            st.divider()
        if st.button("应用并重绘",type="primary",use_container_width=True,key=f"apply_strategy_tasks_{context_signature}"):
            result["角色任务"]=edited_tasks
            result_record=dict(result_record); result_record["result"]=result
            st.session_state[state_key]=result_record
            st.success("图表已更新。")
            st.rerun()
    core_cards=''.join(f'<div class="strategy-core-card"><b>{html.escape(str(item.get("策略名称","核心策略")))}</b><span>目标｜{html.escape(str(item.get("策略目标","")))}</span><p>{html.escape(str(item.get("策略路径","")))}</p></div>' for item in strategies)
    st.markdown(f'<div class="strategy-core-grid">{core_cards}</div>',unsafe_allow_html=True)
    stage_cards=''.join(f'<div class="strategy-stage-card"><b>{html.escape(str(item.get("阶段","")))}</b><span>{html.escape(str(item.get("时间","")))}</span><p>{html.escape(str(item.get("阶段目标","")))}</p></div>' for item in stages)
    st.markdown(f'<div class="strategy-stage-grid">{stage_cards}</div>',unsafe_allow_html=True)
    gantt_fig=go.Figure()
    gantt_colors=["#4F7DE8","#43A29B","#D48B31","#765DCE","#D35F78","#3E93C8"]
    for task_no,task in enumerate(tasks):
        role=str(task.get("角色","")).strip()
        if not role or not stage_names: continue
        start=stage_index.get(str(task.get("开始阶段","")),0)
        end=stage_index.get(str(task.get("结束阶段","")),start)
        if end<start: start,end=end,start
        gantt_fig.add_trace(go.Bar(
            x=[end-start+1],base=[start],y=[role],orientation="h",
            marker=dict(color=gantt_colors[role_order.index(role)%len(gantt_colors)] if role in role_order else gantt_colors[task_no%len(gantt_colors)],line=dict(color="#BBD7FF",width=1),cornerradius=10),
            text=[str(task.get("任务",""))],textposition="inside",insidetextanchor="middle",textfont=dict(color="#FFFFFF",size=12,family="Microsoft YaHei, SimHei, Arial"),
            customdata=[[str(task.get("交付物","")),str(task.get("衡量指标","")),str(task.get("开始阶段","")),str(task.get("结束阶段",""))]],
            hovertemplate="<b>%{text}</b><br>阶段：%{customdata[2]} - %{customdata[3]}<br>交付物：%{customdata[0]}<br>指标：%{customdata[1]}<extra></extra>",showlegend=False,
        ))
    gantt_fig.update_layout(
        barmode="overlay",height=max(330,120+70*max(1,len(role_order))),margin=dict(l=112,r=18,t=24,b=26),
        paper_bgcolor="#081426",plot_bgcolor="#0B1B31",font=dict(family="Microsoft YaHei, SimHei, Arial",color="#EAF4FF",size=12),
        xaxis=dict(range=[0,max(1,len(stage_names))],tickmode="array",tickvals=[i+.5 for i in range(len(stage_names))],ticktext=stage_names,side="top",title=dict(text="策略阶段",font=dict(color="#B8D3F2")),tickfont=dict(color="#B8D3F2",size=12),gridcolor="rgba(139,174,213,.18)",fixedrange=True),
        yaxis=dict(categoryorder="array",categoryarray=list(reversed(role_order)),showticklabels=False,gridcolor="rgba(139,174,213,.12)",fixedrange=True),
        hoverlabel=dict(bgcolor="#132C4A",font_color="#FFFFFF",font_family="Microsoft YaHei"),
    )
    for role_no,role in enumerate(role_order):
        gantt_fig.add_annotation(x=-.02,xref="paper",y=role,yref="y",text=f"<b>{html.escape(str(role))}</b>",showarrow=False,xanchor="right",font=dict(color=gantt_colors[role_no%len(gantt_colors)],size=12,family="Microsoft YaHei, SimHei, Arial"))
    render_responsive_chart(gantt_fig,use_container_width=True,config={"displayModeBar":False})


requested_module=st.query_params.get("module")
requested_target=st.query_params.get("target")
if requested_target:
    st.session_state.target_query=str(requested_target)
    st.session_state.home_query=str(requested_target)
    reset_view_state()
if requested_module in {"市场大盘","竞品格局","用户洞察","策略生成"}:
    set_page(requested_module)
    st.query_params.clear()

prepare_page_data(st.session_state.current_page)

if st.session_state.current_page=="首页":
    st.markdown('<div class="home-title">小羊分析助手</div>',unsafe_allow_html=True)
    st.markdown('<div class="home-subtitle">输入品牌或车系，一键获取GTM相关分析</div>',unsafe_allow_html=True)
    _,center,_=st.columns([.6,2.8,.6])
    with center:
        c1,c2=st.columns([5,1.2])
        with c1:
            st.text_input("搜索品牌或车系",key="home_query",placeholder="请输入您想查找的车型/品牌，例如：奥迪A6L",label_visibility="collapsed",on_change=submit_search)
        with c2:
            if st.button("搜索",use_container_width=True): submit_search(); st.rerun()
        if st.session_state.get("_home_search_error"):
            st.warning(st.session_state["_home_search_error"])
        st.markdown('<div class="small-note" style="margin:8px 0 4px;">快速体验</div>',unsafe_allow_html=True)
        example_cols=st.columns(3)
        for example_col,example in zip(example_cols,["比亚迪","问界M7","奥迪A6L"]):
            with example_col:
                st.button(example,key=f"quick_{example}",use_container_width=True,on_click=quick_search,args=(example,))
        st.markdown("<br>",unsafe_allow_html=True)
        cols=st.columns(4)
        modules=[("市场大盘","查看市场容量、价格段、能源形式与车身形式走势。",""),("竞品格局","识别核心竞品、潜在威胁、可抢夺对象和攻防重点。",""),("用户洞察","提炼用户画像、需求顾虑、竞品比较和沟通话术。",""),("策略生成","压缩市场、竞品与用户结论，输出策略一页纸。","")]
        for col,(title,desc,badge) in zip(cols,modules):
            with col:
                badge_html=f'<span class="build-badge">{badge}</span>' if badge else ""
                st.markdown(f'<a class="home-module-card" href="?module={title}" target="_self"><span class="home-module-title">{title}{badge_html}</span><span class="home-module-desc">{desc}</span></a>',unsafe_allow_html=True)
else:
    sidebar_col,content_col=st.columns([.9,6.1],gap="small")
    with sidebar_col: render_custom_sidebar()
    with content_col:
        if st.session_state.current_page=="市场大盘":
            render_page_title("市场大盘","从宏观层判断新品所在细分市场是否具备进入机会","📈")
            objective_market_mode=not str(st.session_state.target_query).strip() or st.session_state.target_query=="自定义分析目标"
            target=target_info("自定义分析目标" if objective_market_mode else st.session_state.target_query)
            brands,series_filter,regions,prices,energies,bodies=render_target_hero("market",target)
            if not target["found"]:
                st.markdown(f'<div class="ai-card"><span class="tag red-tag">系统暂未收录</span><br><br>系统暂未收录 <b>{target["query"]}</b> 该品牌或车系。请检查 car_info.csv 是否已补充该车型，或更换搜索词后重新搜索。</div>',unsafe_allow_html=True)
                render_footer_note(); st.stop()
            if not objective_market_mode: render_section_nav("market")
            selected_energy_groups=unique_list([energy_group(e) for e in energies],ENERGY_GROUP_OPTIONS)
            market_scope=filter_market_data(regions=regions,prices=prices,energy_groups=selected_energy_groups,bodies=bodies)
            if objective_market_mode:
                if market_scope.empty:
                    st.warning("当前筛选口径暂无市场数据，请调整高级筛选后重试。")
                else:
                    st.info("当前未选择品牌或车系，以下仅展示PV市场大盘，不计算目标车型销量、市占率、用户或竞品结论。")
                    render_objective_market_dashboard(market_scope,regions)
                render_footer_note(); st.stop()
            target_rows_for_context=filter_target_rows_for_context(target["matched_rows"],brands=brands,series_filter=series_filter,prices=prices,energies=energies,bodies=bodies)
            target_names=target_rows_for_context["分析对象名称"].astype(str).unique().tolist()
            target_energy_groups=unique_list(target_rows_for_context["能源大类"],ENERGY_GROUP_OPTIONS)
            target_bodies=unique_list(target_rows_for_context["车身形式"],BODY_OPTIONS)
            target_scope=filter_target_data(regions=regions,prices=prices,energies=energies,bodies=bodies,names=target_names,brands=brands,series_filter=series_filter)
            if market_scope.empty or target_scope.empty:
                st.warning("当前筛选条件下暂无对应车系，请重新使用高级筛选后重试。"); render_footer_note(); st.stop()
            st.markdown("<div style='height:18px'></div>",unsafe_allow_html=True)
            scope_map={}
            for region in regions:
                region_market=market_scope[market_scope["地区"]==region].copy()
                region_target=target_scope[target_scope["地区"]==region].copy()
                if not region_market.empty and not region_target.empty:
                    scope_map[region]=(region_market,region_target)
            valid_regions=[region for region in regions if region in scope_map]
            if not valid_regions:
                st.warning("所选地区暂无可展示的数据，请调整地区范围后重试。"); render_footer_note(); st.stop()
            energy_scope_map={region:(filter_market_data(regions=[region],prices=prices,energy_groups=None,bodies=bodies),scope_map[region][1]) for region in valid_regions}
            body_scope_map={region:(filter_market_data(regions=[region],prices=prices,energy_groups=selected_energy_groups,bodies=None),scope_map[region][1]) for region in valid_regions}
            st.markdown('<div id="market-opportunity" class="section-anchor"></div>',unsafe_allow_html=True)
            if len(valid_regions)>1:
                render_multi_region_kpi_table(valid_regions,scope_map)
            else:
                only_market,only_target=scope_map[valid_regions[0]]
                render_region_kpis(valid_regions[0],only_market,only_target)
            st.markdown('<div id="market-trend" class="section-anchor"></div>',unsafe_allow_html=True)
            st.markdown("### ◈ 市场走势")
            with st.container(border=True):
                render_region_chart_grid(valid_regions,scope_map,"market",prices,target_energy_groups,target_bodies)
                render_module_region_conclusion(valid_regions,scope_map,"market")
            st.markdown('<div id="price-structure" class="section-anchor"></div>',unsafe_allow_html=True)
            st.markdown("### ◈ 价格结构")
            with st.container(border=True):
                render_region_chart_grid(valid_regions,scope_map,"price",prices,target_energy_groups,target_bodies)
                render_module_region_conclusion(valid_regions,scope_map,"price")
            st.markdown('<div id="energy-structure" class="section-anchor"></div>',unsafe_allow_html=True)
            st.markdown("### ◈ 能源形式")
            with st.container(border=True):
                render_region_chart_grid(valid_regions,scope_map,"energy",prices,target_energy_groups,target_bodies)
                render_module_region_conclusion(valid_regions,scope_map,"energy",energy_scope_map)
            st.markdown('<div id="body-structure" class="section-anchor"></div>',unsafe_allow_html=True)
            st.markdown("### ◈ 车身结构")
            with st.container(border=True):
                render_region_chart_grid(valid_regions,scope_map,"body",prices,target_energy_groups,target_bodies)
                render_module_region_conclusion(valid_regions,scope_map,"body",body_scope_map)
            if len(valid_regions)==1:
                only_region=valid_regions[0]
                only_market,only_target=scope_map[only_region]
                render_market_conclusion(only_market,energy_scope_map[only_region][0],body_scope_map[only_region][0],only_target,valid_regions,prices,target_energy_groups,target_bodies)
            market_pdf=build_market_pdf_report(target,valid_regions,prices,energies,bodies,scope_map,energy_scope_map,body_scope_map)
            st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)
            st.download_button("下载市场大盘报告（PDF）",market_pdf,file_name=f'{target["车系"]}_市场大盘报告.pdf',mime="application/pdf",use_container_width=True)
            render_footer_note()
        elif st.session_state.current_page=="竞品格局":
            render_page_title("竞品格局","从中观层识别核心竞品、潜在威胁与差异化攻防重点","▦")
            if not has_explicit_analysis_target():
                render_target_required_dialog(); render_footer_note(); st.stop()
            target=target_info(st.session_state.target_query)
            brands,series_filter,regions,prices,energies,bodies=render_target_hero("competitor",target)
            if not target["found"]:
                st.markdown(f'<div class="ai-card"><span class="tag red-tag">系统暂未收录</span><br><br>系统暂未收录 <b>{target["query"]}</b> 该品牌或车系。</div>',unsafe_allow_html=True)
                render_footer_note(); st.stop()
            render_section_nav("competitor")
            is_brand_query=target.get("is_brand_query",False)
            comparison_level="品牌" if is_brand_query else "车系"
            chart_target_products=unique_list(target["matched_rows"]["品牌"] if is_brand_query else target["matched_rows"]["品牌"].astype(str)+"-"+target["matched_rows"]["车系"].astype(str))
            price_range_text=target_price_range(target,prices)
            sales_scope=competitor_sales_scope(target,regions,prices,energies,bodies,brands,series_filter,False)
            nev_scope=competitor_sales_scope(target,regions,prices,energies,["SUV"],brands,series_filter,True)
            if sales_scope.empty:
                st.warning("当前价格、车身和地区范围下暂无竞品销量数据，请调整竞品范围后重试。")
                render_footer_note(); st.stop()

            cr_df=concentration_table(sales_scope,target,is_brand_query,regions)
            tiers=classify_competitors(sales_scope,target,is_brand_query,regions)
            st.markdown('<div id="competition-overview" class="section-anchor"></div>',unsafe_allow_html=True)
            render_competitor_overview(tiers,cr_df,regions)
            render_head_to_head(tiers,sales_scope,target,is_brand_query,regions)

            st.markdown('<div id="competition-chart" class="section-anchor"></div>',unsafe_allow_html=True)
            with st.container(border=True):
                render_help_title(f"◈ {price_range_text}{comparison_level}竞争格局TOP15","百分比堆积柱展示TOP15月度份额，灰色为其他对象，彩色图层按最近一个月销量由高到低排列。")
                compact_grid=len(regions)>1
                for start in range(0,len(regions),2):
                    chunk=regions[start:start+2]
                    columns=st.columns(len(chunk))
                    for column,region in zip(columns,chunk):
                        with column:
                            share_fig=render_top15_share_chart(sales_scope,is_brand_query,region,chart_target_products,compact_grid)
                            share_fig.update_layout(title=dict(text=f"{region}｜{price_range_text}{format_options(bodies)} TOP15份额",x=.5,xanchor="center",y=.97,font=dict(size=14,color="#EAF3FF")),margin=dict(l=24,r=12,t=58,b=115))
                            render_responsive_chart(share_fig,use_container_width=True)
                            st.markdown(competition_legend_markup(sales_scope,is_brand_query,region,chart_target_products,compact_grid),unsafe_allow_html=True)
                render_competition_opportunity_insight(sales_scope,is_brand_query,regions,f"{price_range_text}{comparison_level}竞争格局")

            with st.container(border=True):
                render_help_title(f"◈ {price_range_text}新能源SUV{comparison_level}竞争格局TOP15","固定限制BEV/PHEV与SUV车身，比较TOP15月度份额；灰色为其他新能源SUV，整柱合计100%。")
                if nev_scope.empty or float(nev_scope["销量"].sum())<=0:
                    st.info("当前品牌/车系、价格和车身范围内没有可用的新能源销量样本。可放宽竞品品牌/车系，或调整价格段后查看新能源竞争格局。")
                else:
                    compact_grid=len(regions)>1
                    for start in range(0,len(regions),2):
                        chunk=regions[start:start+2]
                        columns=st.columns(len(chunk))
                        for column,region in zip(columns,chunk):
                            with column:
                                region_nev=nev_scope[nev_scope["地区"]==region]
                                if region_nev.empty or float(region_nev["销量"].sum())<=0:
                                    st.info(f"{region}当前筛选范围内暂无可用的新能源销量样本。")
                                    continue
                                nev_fig=render_new_energy_share_chart(nev_scope,is_brand_query,region,chart_target_products,compact_grid)
                                nev_fig.update_layout(title=dict(text=f"{region}｜新能源SUV TOP15份额",x=.5,xanchor="center",y=.97,font=dict(size=14,color="#EAF3FF")),margin=dict(l=24,r=12,t=58,b=115))
                                render_responsive_chart(nev_fig,use_container_width=True)
                                st.markdown(competition_legend_markup(nev_scope,is_brand_query,region,chart_target_products,compact_grid),unsafe_allow_html=True)
                    render_competition_opportunity_insight(nev_scope,is_brand_query,regions,f"{price_range_text}新能源SUV{comparison_level}竞争格局")

            st.markdown('<div id="concentration" class="section-anchor"></div>',unsafe_allow_html=True)
            st.markdown("### ◈ 市场集中度")
            render_concentration_table(cr_df)
            if len(cr_df)>1:
                benchmark="全国" if "全国" in regions else regions[0]
                base=cr_df[cr_df["地区"]==benchmark].iloc[0]
                for region in [item for item in regions if item!=benchmark]:
                    current=cr_df[cr_df["地区"]==region].iloc[0]
                    st.markdown(f'<div class="insight-panel"><div class="insight-kicker">{region} VS {benchmark}</div><div class="insight-title">集中度机会判断</div><div class="insight-text">{region} CR3为 <span class="insight-number">{current["CR3"]:.2%}</span>、CR5为 <span class="insight-number">{current["CR5"]:.2%}</span>；CR5较{benchmark} <span class="insight-number">{(current["CR5"]-base["CR5"])*100:+.2f}pct</span>。{"集中度更低、头部尚未固化，具有切入机会。" if current["CR5"]<base["CR5"] else "集中度更高，应重点制定针对头部竞品的替代策略。"}</div></div>',unsafe_allow_html=True)

            st.markdown('<div id="competitor-pool" class="section-anchor"></div>',unsafe_allow_html=True)
            st.markdown("### ◈ 竞品池")
            if tiers.empty:
                st.warning("当前口径下暂未形成稳定的竞品分级结果。")
            else:
                render_competitor_tiers(tiers,is_brand_query)
                st.markdown('<div id="attack-summary" class="section-anchor"></div>',unsafe_allow_html=True)
                render_competitor_summary(tiers,cr_df,target,is_brand_query,regions,prices,bodies,sales_scope)
            competitor_pdf=build_competitor_pdf_report(target,regions,prices,energies,bodies,cr_df,tiers)
            st.markdown('<div style="height:12px;clear:both"></div>',unsafe_allow_html=True)
            st.download_button("下载竞品格局报告（PDF）",competitor_pdf,file_name=f'{target["车系"]}_竞品格局报告.pdf',mime="application/pdf",use_container_width=True)
            render_footer_note()
        elif st.session_state.current_page=="用户洞察":
            render_page_title("用户洞察","整合访谈、问卷与用户评论，提炼画像、需求、竞品选择和转化话术","👥")
            if not has_explicit_analysis_target():
                render_target_required_dialog(); render_footer_note(); st.stop()
            target=target_info(st.session_state.target_query)
            render_target_hero("user",target)
            if not target["found"]:
                st.markdown(f'<div class="ai-card"><span class="tag red-tag">系统暂未收录</span><br><br>系统暂未收录 <b>{target["query"]}</b> 该品牌或车系。</div>',unsafe_allow_html=True)
                render_footer_note(); st.stop()
            render_section_nav("user")
            render_user_insight_page(target)
            render_footer_note()
        elif st.session_state.current_page=="策略生成":
            render_page_title("策略生成","压缩市场、竞争与用户洞察，形成可执行的GTM推进方案","🎯")
            if not has_explicit_analysis_target():
                render_target_required_dialog(); render_footer_note(); st.stop()
            target=target_info(st.session_state.target_query)
            strategy_filters=render_target_hero("strategy",target)
            if not target["found"]:
                st.markdown(f'<div class="ai-card"><span class="tag red-tag">系统暂未收录</span><br><br>系统暂未收录 <b>{target["query"]}</b> 该品牌或车系。</div>',unsafe_allow_html=True)
                render_footer_note(); st.stop()
            render_strategy_onepager(target,strategy_filters)
            render_footer_note()
