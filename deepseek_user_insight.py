import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from session_runtime import SessionFile, saved_upload, source_version, setting, reserve_api_call

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


ROOT = Path(__file__).resolve().parent
if load_dotenv is not None:
    load_dotenv(ROOT / ".env")
    if not setting("DEEPSEEK_API_KEY", "").strip():
        load_dotenv(ROOT / "deepseekAPI.env", override=True)

CACHE_PATH = SessionFile("user_insights_cache.csv")
SUMMARY_CACHE_PATH = SessionFile("user_insight_summary_cache.json")
ERROR_LOG_PATH = SessionFile("deepseek_error_log.txt")

SURVEY_REQUIRED = [
    "样本ID", "品牌", "车系", "分析对象名称", "年龄段", "职业", "购车预算", "家庭结构",
    "首购/增购/换购", "决策周期", "购车动因", "主要决策人",
]
MATERIAL_REQUIRED = [
    "材料ID", "样本ID", "品牌", "车系", "分析对象名称", "来源类型", "来源平台", "用户原文",
]
AI_FIELDS = [
    "用户类型", "使用场景", "购车动因", "核心需求", "关注理由", "顾虑点", "提升空间", "提及竞品",
    "比较维度", "选择本品原因", "选择竞品原因", "情绪倾向", "转化阶段", "沟通话术建议", "典型原文", "置信度",
]
CACHE_COLUMNS = [
    "材料ID", "样本ID", "品牌", "车系", "分析对象名称", *AI_FIELDS, "来源类型", "来源平台", "用户原文",
    "分析模型", "分析时间",
]
LIST_FIELDS = {
    "用户类型", "使用场景", "购车动因", "核心需求", "关注理由", "顾虑点", "提升空间", "提及竞品",
    "比较维度", "选择本品原因", "选择竞品原因",
}


def _read_csv(path):
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.read_csv(path)


def read_table(source, filename=None):
    name = (filename or getattr(source, "name", "")).lower()
    if hasattr(source, "getvalue"):
        import io
        raw = io.BytesIO(source.getvalue())
        return pd.read_excel(raw) if name.endswith((".xlsx", ".xls")) else pd.read_csv(raw, encoding="utf-8-sig")
    path = Path(source)
    return pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else _read_csv(path)


def _prepare(frame, required):
    frame = frame.copy() if frame is not None else pd.DataFrame()
    frame.columns = [str(col).strip() for col in frame.columns]
    for col in required:
        if col not in frame.columns:
            frame[col] = ""
        frame[col] = frame[col].fillna("").astype(str).str.strip()
    return frame


def find_local_table(kind):
    if kind == "survey":
        names = ["user_profile_survey.csv", "user_profile_survey.xlsx", "data/user_profile_survey.csv", "data/user_profile_survey.xlsx"]
        demo = ["data/user_profile_survey_demo_v01.csv", "data/user_profile_survey_demo_v01.xlsx"]
    else:
        names = ["user_materials.csv", "user_materials.xlsx", "data/user_materials.csv", "data/user_materials.xlsx"]
        demo = ["data/user_materials_public_demo_v01.csv", "data/user_materials_public_demo_v01.xlsx"]
    for relative in names + demo:
        path = ROOT / relative
        if path.exists():
            return path, relative in demo
    return None, False


def load_source_table(kind, uploaded=None):
    if uploaded is None:
        uploaded = saved_upload(kind)
    required = SURVEY_REQUIRED if kind == "survey" else MATERIAL_REQUIRED + [
        "年龄段", "职业", "家庭结构", "是否已购", "购车阶段", "决策周期", "主要决策人", "决策影响人",
    ]
    if uploaded is not None:
        try:
            return _prepare(read_table(uploaded, uploaded.name), required), f"页面上传 · {uploaded.name}", None
        except Exception as exc:
            return pd.DataFrame(columns=required), "页面上传", f"无法读取 {uploaded.name}：{exc}"
    path, is_demo = find_local_table(kind)
    if path is None:
        return pd.DataFrame(columns=required), "未找到文件", None
    try:
        label = f"本地{'演示' if is_demo else '正式'}文件 · {path.name}"
        supplement = ROOT / "data" / ("user_profile_survey_demo_supplement.xlsx" if kind == "survey" else "user_materials_demo_supplement.xlsx")
        supplement_path = str(supplement) if is_demo and supplement.exists() else ""
        frame = _load_bundled_table(str(path), path.stat().st_mtime_ns, supplement_path,
                                    supplement.stat().st_mtime_ns if supplement_path else 0)
        return _prepare(frame, required), label, None
    except Exception as exc:
        return pd.DataFrame(columns=required), str(path), f"无法读取 {path.name}：{exc}"


@st.cache_data(show_spinner=False)
def _load_bundled_table(path, modified, supplement_path, supplement_modified):
    frame = read_table(path)
    if supplement_path:
        extra = read_table(supplement_path)
        present = set(frame["车系"].fillna("").map(_norm))
        extra = extra[~extra["车系"].fillna("").map(_norm).isin(present)]
        frame = pd.concat([frame, extra], ignore_index=True)
    return frame


def _norm(value):
    return "".join(str(value).lower().replace("汽车", "").split()).replace("-", "").replace("·", "")


def filter_for_target(frame, target):
    if frame is None or frame.empty:
        return frame.copy()
    rows = frame.copy()
    matched = target.get("matched_rows", pd.DataFrame())
    if target.get("is_brand_query"):
        brands = matched.get("品牌", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if not matched.empty else [target.get("query", "")]
        keys = {_norm(item) for item in brands if str(item).strip()}
        return rows[rows["品牌"].map(_norm).isin(keys)].copy()
    series = matched.get("车系", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if not matched.empty else [target.get("车系", target.get("query", ""))]
    keys = {_norm(item) for item in series if str(item).strip()}
    return rows[rows["车系"].map(_norm).isin(keys) | rows["分析对象名称"].map(_norm).isin(keys)].copy()


def target_label(target):
    return str(target.get("query") if target.get("is_brand_query") else target.get("车系") or target.get("query") or "当前目标")


def api_config():
    return {
        "api_key": setting("DEEPSEEK_API_KEY", "").strip(),
        "base_url": setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip() or "https://api.deepseek.com",
        "model": setting("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash",
    }


def ensure_cache():
    if not CACHE_PATH.exists():
        pd.DataFrame(columns=CACHE_COLUMNS).to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")


def load_cache():
    ensure_cache()
    try:
        return _prepare(_read_csv(CACHE_PATH), CACHE_COLUMNS)
    except Exception:
        return pd.DataFrame(columns=CACHE_COLUMNS)


def _json_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [item.strip() for item in text.replace("；", "|").replace("、", "|").split("|") if item.strip()]


def list_values(frame, field):
    values = []
    if frame is None or frame.empty or field not in frame.columns:
        return values
    for value in frame[field]:
        values.extend(_json_list(value))
    return values


def _material_id(row):
    given = str(row.get("材料ID", "")).strip()
    raw = "|".join(str(row.get(col, "")) for col in ["品牌", "车系", "来源类型", "来源平台", "用户原文"])
    return given + "-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _log_bad_response(raw, error):
    with ERROR_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {error}\n{raw}\n")


def analyze_material_with_deepseek(row, target_name):
    config = api_config()
    if not config["api_key"]:
        raise RuntimeError("暂未检测到 DeepSeek API Key，当前为演示模式，可使用看板、问卷统计和基础版策略。")
    if OpenAI is None:
        raise RuntimeError("缺少 openai 依赖，请先安装 requirements.txt 中的依赖。")
    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"], timeout=60, max_retries=0)
    system_prompt = (
        "你是一个汽车行业用户研究与GTM策略分析助手。你的任务是基于用户原文，提取可用于用户洞察和销售沟通的结构化信息。"
        "必须严格基于原文，不得编造原文没有的信息。年龄、职业、家庭结构、首购/增购/换购等基础画像信息不从原文推断，"
        "除非原文明确提到。输出必须是合法 JSON。"
    )
    example = {field: [] for field in LIST_FIELDS}
    example.update({"情绪倾向": "未知", "转化阶段": "未知", "沟通话术建议": "", "典型原文": "", "置信度": "低"})
    user_prompt = (
        f"当前目标车型：{target_name}\n品牌：{row.get('品牌','')}\n车系：{row.get('车系','')}\n"
        f"来源类型：{row.get('来源类型','')}\n来源平台：{row.get('来源平台','')}\n用户原文：{row.get('用户原文','')}\n\n"
        "只基于用户原文分析；不要输出解释性段落；不要使用 Markdown；只输出 JSON 对象；不确定的信息用空数组或“未知”；"
        "置信度只能是高/中/低。JSON 字段与类型必须严格参照以下示例：\n" + json.dumps(example, ensure_ascii=False)
    )
    reserve_api_call()
    response = client.chat.completions.create(
        model=config["model"], messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_object"}, extra_body={"thinking": {"type": "disabled"}}, temperature=0.2, max_tokens=1800,
    )
    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        _log_bad_response(raw, exc)
        raise ValueError("AI 返回格式异常，请重试") from exc
    result = {}
    for field in AI_FIELDS:
        if field in LIST_FIELDS:
            result[field] = _json_list(parsed.get(field, []))[:8]
        else:
            result[field] = str(parsed.get(field, "") or "未知").strip()
    if result["置信度"] not in {"高", "中", "低"}:
        result["置信度"] = "低"
    return result


def analyze_new_materials(material_rows, target, limit=20):
    cache = load_cache()
    known = set(cache["材料ID"].astype(str))
    pending = material_rows.copy()
    pending["材料ID"] = pending.apply(_material_id, axis=1)
    pending = pending[~pending["材料ID"].isin(known)].head(limit)
    added, errors = [], []
    config = api_config()
    for _, row in pending.iterrows():
        try:
            insight = analyze_material_with_deepseek(row, target_label(target))
            record = {col: "" for col in CACHE_COLUMNS}
            for col in ["材料ID", "样本ID", "品牌", "车系", "分析对象名称", "来源类型", "来源平台", "用户原文"]:
                record[col] = str(row.get(col, ""))
            for field, value in insight.items():
                record[field] = json.dumps(value, ensure_ascii=False) if field in LIST_FIELDS else value
            record["分析模型"] = config["model"]
            record["分析时间"] = datetime.now().isoformat(timespec="seconds")
            added.append(record)
        except Exception as exc:
            errors.append(f"{row.get('材料ID','未知材料')}：{exc}")
    if added:
        cache = pd.concat([cache, pd.DataFrame(added)], ignore_index=True)[CACHE_COLUMNS]
        cache.to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")
    return len(added), errors


def cache_for_materials(material_rows):
    cache = load_cache()
    ids = {_material_id(row) for _, row in material_rows.iterrows()}
    return cache[cache["材料ID"].astype(str).isin(ids)].copy()


def clear_cache_for_materials(material_rows):
    cache = load_cache()
    ids = {_material_id(row) for _, row in material_rows.iterrows()}
    kept = cache[~cache["材料ID"].astype(str).isin(ids)].copy()
    kept.to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")
    return len(cache) - len(kept)


def aggregate_top(frame, field, limit=5):
    values = list_values(frame, field)
    if not values:
        return []
    # Preserve extracted phrases: substring grouping misclassifies negated mentions.
    counts = pd.Series(values).value_counts().head(limit)
    return [(str(name), int(count)) for name, count in counts.items()]


def _summary_store():
    if not SUMMARY_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(SUMMARY_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def summary_key(target, survey_count, material_count, analyzed_count):
    config = api_config()
    raw = f"{target_label(target)}|{survey_count}|{material_count}|{analyzed_count}|{config['model']}|{source_version()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_cached_summary(target, survey_count, material_count, analyzed_count):
    return _summary_store().get(summary_key(target, survey_count, material_count, analyzed_count))


def generate_summary(target, survey_profile, cache_rows, survey_count, material_count):
    config = api_config()
    if not config["api_key"]:
        raise RuntimeError("暂未检测到 DeepSeek API Key，当前为演示模式，可使用看板、问卷统计和基础版策略。")
    if OpenAI is None:
        raise RuntimeError("缺少 openai 依赖，请先安装 requirements.txt 中的依赖。")
    generic_competitors = {"新能源车", "新能源车型", "新能源汽车", "新势力", "新势力车型", "新能源替代车型", "同级别车型", "同价位竞品", "竞品", "其他竞品"}
    specific_competitors = [(name, count) for name, count in aggregate_top(cache_rows, "提及竞品") if name not in generic_competitors and not str(name).endswith("替代车型")]
    payload = {
        "目标": target_label(target), "问卷样本数": survey_count, "原文材料数": material_count,
        "问卷统计": survey_profile, "核心需求Top5": aggregate_top(cache_rows, "核心需求"),
        "顾虑点Top5": aggregate_top(cache_rows, "顾虑点"), "竞品Top5": specific_competitors[:5],
        "比较维度Top5": aggregate_top(cache_rows, "比较维度"),
        "沟通建议": cache_rows.get("沟通话术建议", pd.Series(dtype=str)).dropna().astype(str).head(10).tolist(),
    }
    system = "你是汽车行业用户研究与GTM策略分析助手。仅依据提供的统计与已分析结果输出合法JSON，不得补造证据。竞品结论只允许写明确品牌或车系，不得将‘新能源车’‘新势力’‘同级车型’等泛化类别列为竞品。"
    schema = {"用户画像总结": "", "核心需求总结": "", "主要顾虑总结": "", "竞品比较总结": "", "沟通策略建议": [], "数据不足提醒": ""}
    prompt = "请输出页面级用户洞察总结。不要Markdown，只输出JSON；沟通策略建议为3条以内。格式：" + json.dumps(schema, ensure_ascii=False) + "\n数据：" + json.dumps(payload, ensure_ascii=False)
    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"], timeout=60, max_retries=0)
    reserve_api_call()
    response = client.chat.completions.create(model=config["model"], messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}], response_format={"type": "json_object"}, extra_body={"thinking": {"type": "disabled"}}, temperature=0.2, max_tokens=1400)
    raw = response.choices[0].message.content or ""
    try:
        result = json.loads(raw)
    except Exception as exc:
        _log_bad_response(raw, exc)
        raise ValueError("AI 返回格式异常，请重试") from exc
    key = summary_key(target, survey_count, material_count, len(cache_rows))
    store = _summary_store()
    store[key] = result
    SUMMARY_CACHE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
