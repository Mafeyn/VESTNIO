"""Public Telegram channels via Telegram's own web preview (https://t.me/s/<channel>).

The preview is the public, read-only HTML page Telegram serves for every public
channel (t.me has no robots.txt restrictions). Private channels and invite links
(t.me/+...) have no preview and cannot be used.

Each post becomes an article:
  title    first line of the post (leading emoji stripped, shortened at a sentence
           or word boundary when long)
  summary  the rest of the text (the normalizer cleans and truncates it)
  image    the first photo / video thumbnail
  url      https://t.me/<channel>/<post id>
Advertising posts (erid / #реклама markers) and channel self-promo lines are dropped.

options:
  max_items:  newest posts to take per poll (default 20, the page shows ~20)
  skip_ads:   default true
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from ..domain import RawItem, SourceConfig
from ..fetcher import Fetcher
from .base import AdapterResult, CacheState, ParseError

TITLE_MAX = 140
_BG_URL = re.compile(r"background-image:\s*url\(['\"]?(.*?)['\"]?\)")
_AD = re.compile(r"\berid\b|#реклама|#ad\b|#промо|на правах рекламы", re.I)
_PROMO_LINE = re.compile(
    r"подпис(аться|ывайся|ывайтесь|ись)|підпис(атися|уйся|уйтесь)|subscribe|наш канал|канал с анонсами|"
    r"предложк|прислать новость|надіслати новину|сообщить новость|прислати новину",
    re.I,
)
SIGNATURE_MAX = 90  # promo/signature lines are short; long lines are real text
_LEADING_JUNK = re.compile(r"^[^\w«\"(]+", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")


def channel_from_url(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "s":
        return parts[1]
    if parts:
        return parts[0]
    raise ParseError(f"not a t.me channel URL: {url}")


class TelegramChannelAdapter:
    name = "telegram"

    async def fetch(self, source: SourceConfig, fetcher: Fetcher, cache: CacheState) -> AdapterResult:
        channel = channel_from_url(str(source.url))
        res = await fetcher.get(f"https://t.me/s/{channel}")
        if "/s/" not in urlsplit(res.url).path:
            raise ParseError(f"@{channel} has no public web preview (private channel or preview disabled)")
        items = parse_channel_page(
            res.text,
            channel,
            source_name=source.name,
            max_items=int(source.options.get("max_items", 20)),
            skip_ads=bool(source.options.get("skip_ads", True)),
        )
        return AdapterResult(items=items)


def _message_text(node: Tag) -> str:
    """Post text with line breaks preserved (<br> -> newline)."""
    for br in node.find_all("br"):
        br.replace_with(NavigableString("\n"))
    return node.get_text("", strip=False)


def _image(msg: Tag) -> str | None:
    for sel in (".tgme_widget_message_photo_wrap", ".tgme_widget_message_video_thumb", ".link_preview_image"):
        el = msg.select_one(sel)
        if el and el.get("style"):
            m = _BG_URL.search(str(el["style"]))
            if m:
                url = m.group(1)
                return "https:" + url if url.startswith("//") else url
    return None


def split_title(text: str) -> tuple[str, str]:
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return "", ""
    first = _LEADING_JUNK.sub("", lines[0]).strip() or lines[0]
    rest = "\n".join(lines[1:])
    if len(first) <= TITLE_MAX:
        return first, rest
    # long first line: cut at the last sentence end that fits, else at a word boundary
    head = first[: TITLE_MAX + 1]
    ends = [m.end() for m in _SENTENCE_END.finditer(head) if m.end() >= 40]
    cut = ends[-1] if ends else (head.rfind(" ") if " " in head[40:] else TITLE_MAX)
    title = first[:cut].rstrip(" ,;:—-")
    if not ends:
        title += "…"
    remainder = first[cut:].strip()
    return title, (remainder + ("\n" + rest if rest else "")).strip()


def _is_signature(line: str, channel: str, names: list[str]) -> bool:
    """Channel sign-offs: '👉 Подписаться', '❤️ PDA', '⚡️Короче | Игровой', '@channel'."""
    s = line.strip()
    if not s or len(s) > SIGNATURE_MAX:
        return False
    low = s.lower()
    if _PROMO_LINE.search(s) or f"@{channel.lower()}" in low or f"t.me/{channel.lower()}" in low:
        return True
    core = _LEADING_JUNK.sub("", s).strip().lower()
    if len(core) >= 3 and (core in channel.lower() or any(core in n for n in names)):
        return True  # abbreviated sign-off: "PDA" for "4PDA Community" / @pda_4
    return any(n and (core == n or (len(core) <= 40 and n in core)) for n in names)


def parse_channel_page(
    html: str, channel: str, *, source_name: str = "", max_items: int = 20, skip_ads: bool = True
) -> list[RawItem]:
    names = {source_name.lower()}
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".tgme_channel_info_header_title")
    if title_el:
        full = title_el.get_text(" ", strip=True).lower()
        names |= {full, full.split("|")[0].strip(), full.split(" - ")[0].strip(), full.split(" — ")[0].strip()}
    # short channel nicknames used in signatures ("PDA" for "4PDA Community", "IT Memes")
    for n in list(names):
        for word in re.split(r"[\s|—\-:&]+", n):
            if len(word) >= 3 and word not in {"the", "and", "новости", "новини", "канал"}:
                names.add(word)
    names_list = sorted((n for n in names if n), key=len, reverse=True)
    messages = soup.select(".tgme_widget_message[data-post]")
    if not messages and not soup.select_one(".tgme_channel_info"):
        raise ParseError("page is not a Telegram channel preview")

    items: list[RawItem] = []
    for msg in reversed(messages):  # page is oldest → newest
        if len(items) >= max_items:
            break
        post = str(msg["data-post"])  # "channel/123"
        if "service_message" in (msg.get("class") or []):
            continue
        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            continue  # photo/video without caption: nothing to headline
        text = _message_text(text_el)
        if skip_ads and _AD.search(text):
            continue
        lines = text.splitlines()
        # drop sign-off lines, but never the first line (it is the headline)
        first_idx = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
        kept = [ln for i, ln in enumerate(lines) if i <= first_idx or not _is_signature(ln, channel, names_list)]
        title, rest = split_title("\n".join(kept))
        if not title:
            continue
        time_el = msg.select_one(".tgme_widget_message_date time[datetime]")
        items.append(
            RawItem(
                external_id=f"tg:{post}",
                title=title,
                url=f"https://t.me/{post}",
                summary=rest or None,
                image_url=_image(msg),
                published=str(time_el["datetime"]) if time_el else None,
            )
        )
    return items
