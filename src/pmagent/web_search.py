#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import sys
import textwrap
import urllib.parse
import urllib.request
import urllib.error
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .paths import resolve_data_dir


def load_dotenv(dotenv_path: Optional[Path] = None):
    """Load .env file into os.environ (simple implementation, no dependencies)."""
    if dotenv_path is None:
        try:
            dotenv_path = resolve_data_dir() / ".env"
        except RuntimeError:
            return
    try:
        if not dotenv_path.exists():
            return
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # Remove surrounding quotes if present
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if key and key not in os.environ:  # Don't override existing env vars
            os.environ[key] = value


load_dotenv()


BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_SUMMARIZER_URL = "https://api.search.brave.com/res/v1/summarizer/search"
BRAVE_CHAT_COMPLETIONS_URL = "https://api.search.brave.com/res/v1/chat/completions"

BRAVE_ANSWERS_AVAILABLE = True

DEFAULT_LIBRETRANSLATE_URL = "https://libretranslate.com/translate"
MYMEMORY_TRANSLATE_URL = "https://api.mymemory.translated.net/get"


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def looks_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def libretranslate_zh(text: str) -> Optional[str]:
    """
    Best-effort translation to Chinese using LibreTranslate-compatible endpoint.
    Controlled by env:
      LIBRETRANSLATE_URL (default: https://libretranslate.com/translate)
      LIBRETRANSLATE_API_KEY (optional)
    """
    text = (text or "").strip()
    if not text:
        return None
    if looks_chinese(text):
        return text

    url = os.environ.get("LIBRETRANSLATE_URL", "").strip() or DEFAULT_LIBRETRANSLATE_URL
    api_key = os.environ.get("LIBRETRANSLATE_API_KEY", "").strip()

    payload = {"q": text, "source": "auto", "target": "zh", "format": "text"}
    if api_key:
        payload["api_key"] = api_key

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        data = _http_post_json(url, headers=headers, payload=payload)
    except Exception as e:
        print(f"[warn] translate failed: {e}", file=sys.stderr)
        return None

    translated = (data.get("translatedText") or "").strip()
    return translated or None


def mymemory_translate_zh(text: str) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None
    if looks_chinese(text):
        return text
    if len(text) > 400:
        text = text[:400]

    params: Params = {"q": text, "langpair": "en|zh-CN"}
    email = os.environ.get("MYMEMORY_EMAIL", "").strip()
    if email:
        params["de"] = email
    headers = {"Accept": "application/json"}
    try:
        data = _http_get_json(MYMEMORY_TRANSLATE_URL, headers=headers, params=params)
    except Exception as e:
        print(f"[warn] translate failed (mymemory): {e}", file=sys.stderr)
        return None

    resp = data.get("responseData") or {}
    translated = (resp.get("translatedText") or "").strip()
    if not translated:
        return None
    bad_markers = [
        "QUERY LENGTH LIMIT EXCEEDED",
        "MAX ALLOWED QUERY",
        "INVALID PARAMETER",
    ]
    for m in bad_markers:
        if m in translated:
            return None
    return translated or None


def translate_zh(text: str) -> Optional[str]:
    provider = os.environ.get("TRANSLATE_PROVIDER", "").strip().lower() or "mymemory"
    if provider == "none":
        return None
    if provider == "libretranslate":
        t = libretranslate_zh(text)
        if t:
            return t
        return mymemory_translate_zh(text)
    if provider == "mymemory":
        return mymemory_translate_zh(text)
    return None


Params = Dict[str, Union[str, int]]


def _http_get_json(url: str, headers: Dict[str, str], params: Optional[Params] = None) -> Dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {err_body[:800]}") from e


def _http_post_json(url: str, headers: Dict[str, str], payload: Dict) -> Dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {err_body[:800]}") from e


def brave_answers_cn_section(*, api_key: str, section_name: str, query: str, results: List[Dict]) -> Optional[str]:
    """
    Uses Brave Answers (OpenAI-compatible) to produce a Chinese summary and translated source list
    grounded ONLY in the provided results list (no extra links).
    """
    global BRAVE_ANSWERS_AVAILABLE
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-subscription-token": api_key,
    }

    def _clip(s: str, n: int = 280) -> str:
        s = (s or "").replace("\n", " ").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    packed = []
    for r in results[:12]:
        packed.append(
            {
                "title": _clip(r.get("title", "")),
                "url": r.get("url", ""),
                "age": _clip(r.get("age", ""), 80),
                "description": _clip(r.get("description", "")),
            }
        )

    prompt = (
        "你是我的研究助手。请严格只基于我提供的搜索结果列表生成输出，不要引入列表之外的新链接或事实。\n"
        f"主题：{section_name}\n"
        f"搜索查询：{query}\n\n"
        "搜索结果（JSON）：\n"
        f"{json.dumps(packed, ensure_ascii=False, indent=2)}\n\n"
        "请用中文输出两段（Markdown）：\n"
        "1) `### 摘要`：5-8 条要点，偏“发生了什么/为什么重要/对我意味着什么”。\n"
        "2) `### 来源`：逐条列出来源，格式 `- 中文标题（可翻译或概括）：URL — 中文一句话说明（可包含时间线索）`。\n"
        "要求：保持简洁；不要输出多余解释。"
    )

    payload = {"stream": False, "messages": [{"role": "user", "content": prompt}]}

    try:
        data = _http_post_json(BRAVE_CHAT_COMPLETIONS_URL, headers=headers, payload=payload)
    except Exception as e:
        msg = str(e)
        if "OPTION_NOT_IN_PLAN" in msg:
            BRAVE_ANSWERS_AVAILABLE = False
            print("[warn] Brave Answers not available in current plan; falling back to non-translated snippets.", file=sys.stderr)
            return None
        print(f"[warn] Brave Answers failed for section '{section_name}': {e}", file=sys.stderr)
        return None

    choices = data.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    content = (msg.get("content") or "").strip()
    return content or None

def brave_search(
    *,
    api_key: str,
    query: str,
    count: int,
    freshness: Optional[str],
    country: Optional[str],
    search_lang: Optional[str],
    ui_lang: Optional[str],
    safesearch: Optional[str],
    want_summary: bool,
) -> Tuple[Dict, Optional[str]]:
    headers: Dict[str, str] = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params: Params = {
        "q": query,
        "count": count,
    }
    if freshness:
        params["freshness"] = freshness
    if country:
        params["country"] = country
    if search_lang:
        params["search_lang"] = search_lang
    if ui_lang:
        params["ui_lang"] = ui_lang
    if safesearch:
        params["safesearch"] = safesearch
    if want_summary:
        params["summary"] = 1

    data = _http_get_json(BRAVE_WEB_SEARCH_URL, headers=headers, params=params)

    summary_text: Optional[str] = None
    if want_summary:
        summarizer = data.get("summarizer") or {}
        key = summarizer.get("key")
        if key:
            summary_data = _http_get_json(BRAVE_SUMMARIZER_URL, headers=headers, params={"key": key})
            summary_text = (summary_data.get("summary") or "").strip() or None

    return data, summary_text


def _load_domain_preset(preset_name: str) -> Optional[Dict]:
    """Load a domain policy preset from watchlist.json."""
    try:
        config_path = resolve_data_dir() / "config" / "watchlist.json"
    except RuntimeError:
        return None
    if not config_path.exists():
        return None
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        presets = cfg.get("domain_presets") or {}
        return presets.get(preset_name) or presets.get("general")
    except Exception:
        return None


def extract_web_results(data: Dict) -> List[Dict]:
    web = data.get("web") or {}
    results = web.get("results") or []
    extracted: List[Dict] = []
    for r in results:
        extracted.append(
            {
                "title": (r.get("title") or "").strip(),
                "url": (r.get("url") or "").strip(),
                "description": (r.get("description") or "").strip(),
                "age": (r.get("age") or "").strip(),
            }
        )
    return extracted


def parse_domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def apply_domain_policy(
    results: List[Dict],
    *,
    prefer_domains: List[str],
    exclude_domains: List[str],
    max_per_domain: int,
) -> List[Dict]:
    prefer = [d.lower().lstrip(".") for d in (prefer_domains or [])]
    exclude = [d.lower().lstrip(".") for d in (exclude_domains or [])]

    def is_match(domain: str, patterns: List[str]) -> bool:
        for p in patterns:
            if domain == p or domain.endswith("." + p):
                return True
        return False

    filtered: List[Dict] = []
    for r in results:
        domain = parse_domain(r.get("url", ""))
        if not domain:
            continue
        if exclude and is_match(domain, exclude):
            continue
        rr = dict(r)
        rr["_domain"] = domain
        rr["_preferred"] = 1 if (prefer and is_match(domain, prefer)) else 0
        filtered.append(rr)

    filtered.sort(key=lambda x: (-int(x.get("_preferred", 0))))

    if max_per_domain and max_per_domain > 0:
        counts: Dict[str, int] = {}
        capped: List[Dict] = []
        for r in filtered:
            domain = r.get("_domain") or ""
            counts[domain] = counts.get(domain, 0) + 1
            if counts[domain] <= max_per_domain:
                capped.append(r)
        filtered = capped

    for r in filtered:
        r.pop("_domain", None)
        r.pop("_preferred", None)
    return filtered


def _error_md(*, query: str, error: str, hint: str = "") -> str:
    """返回结构化的错误 Markdown，让调用方（LLM）能读懂并自行决定下一步。"""
    lines = [
        f"# 检索失败",
        "",
        f"> 查询：`{query}`",
        f"> 时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**错误**：{error}",
    ]
    if hint:
        lines.append("")
        lines.append(f"**建议**：{hint}")
    lines.append("")
    return "\n".join(lines)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def md_escape(text: str) -> str:
    return text.replace("\n", " ").strip()


def render_digest_md(
    *,
    title: str,
    generated_at: str,
    sections: List[Dict],
) -> str:
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> 生成时间：{generated_at}")
    lines.append("")
    for s in sections:
        lines.append(f"## {s['name']}")
        lines.append("")
        lines.append(f"- 查询：`{s['query']}`")
        if s.get("error"):
            lines.append("")
            lines.append(f"- 状态：{md_escape(str(s['error']))}")
            lines.append("")
            continue
        if s.get("cn_block"):
            lines.append("")
            lines.append(s["cn_block"].strip())
            lines.append("")
            continue
        if s.get("summary"):
            lines.append("")
            lines.append("### 摘要")
            lines.append("")
            lines.append(md_escape(s["summary"]))
            lines.append("")
        lines.append("### 来源")
        lines.append("")
        if not s["results"]:
            lines.append("- （无结果）")
        else:
            for r in s["results"]:
                title_text = r["title"] or r["url"] or "(untitled)"
                desc = r["description"]
                age = r["age"]
                suffix_parts = []
                if age:
                    suffix_parts.append(age)
                if desc:
                    suffix_parts.append(desc)
                suffix = " — " + md_escape(" | ".join(suffix_parts)) if suffix_parts else ""
                lines.append(f"- {title_text}: {r['url']}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_watchlist(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def cmd_digest(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else resolve_data_dir()
    config_path = Path(args.config).resolve() if args.config else repo_root / "config" / "watchlist.json"
    cfg = load_watchlist(config_path)

    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        print("Missing env var BRAVE_SEARCH_API_KEY", file=sys.stderr)
        return 2

    defaults = cfg.get("defaults") or {}
    use_answers_cn = bool(cfg.get("use_answers_cn", False))
    translate_to_zh = bool(cfg.get("translate_to_zh", False))
    default_domain_policy = defaults.get("domain_policy") or {}
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = dt.date.today().strftime("%Y-%m-%d")
    out_dir = repo_root / (cfg.get("output_dir") or "research/daily-digest")
    out_path = out_dir / f"{today}-daily-digest.md"

    sections: List[Dict] = []
    for item in cfg.get("watchlist") or []:
        name = item.get("name") or item.get("query") or "Untitled"
        query = item.get("query") or ""
        if not query:
            continue

        count = int(item.get("count") or defaults.get("count") or 10)
        freshness = item.get("freshness") or defaults.get("freshness")
        country = item.get("country") or defaults.get("country")
        search_lang = item.get("search_lang") or defaults.get("search_lang")
        ui_lang = item.get("ui_lang") or defaults.get("ui_lang")
        safesearch = item.get("safesearch") or defaults.get("safesearch")
        want_summary = bool(item.get("summary") if "summary" in item else defaults.get("summary", True))
        item_use_answers_cn = bool(item.get("use_answers_cn") if "use_answers_cn" in item else use_answers_cn)
        item_translate_to_zh = bool(item.get("translate_to_zh") if "translate_to_zh" in item else translate_to_zh)
        domain_policy = item.get("domain_policy") or default_domain_policy
        prefer_domains = domain_policy.get("prefer_domains") or []
        exclude_domains = domain_policy.get("exclude_domains") or []
        max_per_domain = int(domain_policy.get("max_per_domain") or 2)

        summary_text = None
        results: List[Dict] = []
        cn_block = None
        error_note = None
        try:
            data, summary_text = brave_search(
                api_key=api_key,
                query=query,
                count=count,
                freshness=freshness,
                country=country,
                search_lang=search_lang,
                ui_lang=ui_lang,
                safesearch=safesearch,
                want_summary=want_summary,
            )
            results = extract_web_results(data)
            filtered = apply_domain_policy(
                results,
                prefer_domains=prefer_domains,
                exclude_domains=exclude_domains,
                max_per_domain=max_per_domain,
            )
            if not filtered and exclude_domains:
                filtered = apply_domain_policy(
                    results,
                    prefer_domains=prefer_domains,
                    exclude_domains=[],
                    max_per_domain=max_per_domain,
                )
            results = filtered or results
            if item_translate_to_zh:
                for r in results:
                    t = translate_zh(r.get("title") or "")
                    if t:
                        r["title"] = t
                    d = translate_zh(r.get("description") or "")
                    if d:
                        r["description"] = d
                if summary_text:
                    ts = translate_zh(summary_text)
                    if ts:
                        summary_text = ts
            if item_use_answers_cn and results:
                cn_block = brave_answers_cn_section(api_key=api_key, section_name=name, query=query, results=results)
        except Exception as e:
            error_note = f"获取失败：{e}"
        sections.append(
            {
                "name": name,
                "query": query,
                "summary": summary_text,
                "results": results,
                "cn_block": cn_block,
                "error": error_note,
            }
        )

    md = render_digest_md(title=f"每日简报 - {today}", generated_at=generated_at, sections=sections)
    ensure_parent_dir(out_path)
    out_path.write_text(md, encoding="utf-8")
    print(str(out_path))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        md = _error_md(
            query="(unknown)",
            error="环境变量 BRAVE_SEARCH_API_KEY 未设置。请在 .env 文件中配置后重试。",
        )
        sys.stdout.write(md)
        return 0  # 返回 0 让 LLM 能读到错误信息，而非静默崩溃

    query = args.query.strip()
    if not query:
        md = _error_md(query="(empty)", error="搜索关键词为空，请提供 --query 参数。")
        sys.stdout.write(md)
        return 0

    try:
        data, summary_text = brave_search(
            api_key=api_key,
            query=query,
            count=args.count,
            freshness=args.freshness,
            country=args.country,
            search_lang=args.search_lang,
            ui_lang=args.ui_lang,
            safesearch=args.safesearch,
            want_summary=args.summary,
        )
        results = extract_web_results(data)
    except Exception as e:
        md = _error_md(
            query=query,
            error=f"Brave Search 请求失败：{e}",
            hint="可能原因：网络不可达、API Key 无效、请求超时。可尝试换个关键词或稍后重试。",
        )
        sys.stdout.write(md)
        return 0

    # Apply domain policy (preset + extra prefer domains)
    preset_name = getattr(args, "domain_preset", None) or "general"
    if preset_name != "none":
        preset = _load_domain_preset(preset_name) or {}
        prefer = list(preset.get("prefer_domains") or [])
        extra = getattr(args, "extra_prefer_domains", None)
        if extra:
            prefer.extend(extra)
        results = apply_domain_policy(
            results,
            prefer_domains=prefer,
            exclude_domains=preset.get("exclude_domains", []),
            max_per_domain=preset.get("max_per_domain", 3),
        )

    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = args.title or f"临时检索 - {dt.date.today().strftime('%Y-%m-%d')}"
    sections = [{"name": "Results", "query": query, "summary": summary_text, "results": results}]
    md = render_digest_md(title=title, generated_at=generated_at, sections=sections)

    if args.out:
        out_path = Path(args.out).resolve()
        ensure_parent_dir(out_path)
        out_path.write_text(md, encoding="utf-8")
        print(str(out_path))
    else:
        sys.stdout.write(md)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pmagent_web.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Web research utilities for PMagent (Brave Search API).",
        epilog=textwrap.dedent(
            """
            Env:
              BRAVE_SEARCH_API_KEY  Brave Search API subscription token
            """
        ).strip(),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("digest", help="Generate daily digest from a watchlist config")
    d.add_argument("--repo-root", default=None, help="PM Agent data directory (default: resolve from config)")
    d.add_argument("--config", default=None, help="Watchlist config JSON path")
    d.set_defaults(func=cmd_digest)

    s = sub.add_parser("search", help="Run an ad-hoc web search and output markdown")
    s.add_argument("--query", required=True, help="Search query")
    s.add_argument("--count", type=int, default=10, help="Number of results (default: 10)")
    s.add_argument("--freshness", default="pd", help="pd|pw|pm|py or custom (default: pd)")
    s.add_argument("--country", default=None)
    s.add_argument("--search-lang", default=None)
    s.add_argument("--ui-lang", default=None)
    s.add_argument("--safesearch", default=None)
    s.add_argument("--summary", action="store_true", help="Try Brave summarizer (if available)")
    s.add_argument("--domain-preset", default="general", help="Domain policy preset (ai/product/fintech/design/general/none)")
    s.add_argument("--extra-prefer-domains", nargs="*", default=None, help="Extra preferred domains for this search")
    s.add_argument("--title", default=None, help="Markdown title override")
    s.add_argument("--out", default=None, help="Write markdown to path instead of stdout")
    s.set_defaults(func=cmd_search)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
