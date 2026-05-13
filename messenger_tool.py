from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import tkinter as tk
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from urllib.parse import quote, urlparse


APP_DIR = Path(__file__).resolve().parent
PROFILE_DIR = APP_DIR / "edge_profile"
CONTACTS_FILE = APP_DIR / "contacts.json"
DEFAULT_AI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://llm.wokushop.com/v1")
DEFAULT_AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
API_USER_AGENT = "MessengerTool/1.0 (+https://llm.wokushop.com)"
BROWSER_CHANNEL = os.environ.get("MESSENGER_BROWSER_CHANNEL", "msedge")
BROWSER_NAME = "Microsoft Edge"


@dataclass
class Contact:
    name: str
    target: str


class MessengerSession:
    def __init__(self, log):
        self.log = log
        self.playwright = None
        self.context = None
        self.page = None

    def start(self):
        if self.context:
            return

        try:
            from playwright.sync_api import Error, TimeoutError, sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Chua cai Playwright. Hay chay file setup.ps1 truoc, roi mo lai tool."
            ) from exc

        self._pw_error = Error
        self._pw_timeout = TimeoutError
        PROFILE_DIR.mkdir(exist_ok=True)
        self.log(f"Dang mo {BROWSER_NAME}...")
        self.playwright = sync_playwright().start()

        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel=BROWSER_CHANNEL,
                headless=False,
                viewport=None,
                accept_downloads=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            )
        except Exception as exc:
            self.stop()
            raise RuntimeError(
                f"Khong mo duoc {BROWSER_NAME}. Hay cai Edge ban desktop, "
                "hoac dam bao Edge khong bi chan boi antivirus."
            ) from exc

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.log(f"{BROWSER_NAME} da san sang. Lan dau dung thi dang nhap Messenger trong cua so vua mo.")

    def stop(self):
        try:
            if self.context:
                self.context.close()
        finally:
            self.context = None
            self.page = None
            try:
                if self.playwright:
                    self.playwright.stop()
            finally:
                self.playwright = None

    def open_conversation(self, target: str):
        self.start()
        url = normalize_target(target)
        self.log(f"Dang mo: {url}")
        self._goto_messenger(url)
        self.page.bring_to_front()
        self.log("Da mo Messenger. Neu thay man hinh dang nhap, hay dang nhap xong roi bam lai nut.")

    def _goto_messenger(self, url: str):
        try:
            current_url = self.page.url or ""
        except Exception:
            current_url = ""

        if self._same_messenger_target(current_url, url):
            self.log("Cuoc tro chuyen da dang mo, bo qua tai lai trang.")
            return

        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            message = str(exc)
            if "ERR_TOO_MANY_REDIRECTS" in message:
                fallback_url = normalize_target(url)
                if fallback_url != url:
                    self.log("Messenger bi lap chuyen huong voi link e2ee, thu lai bang link /t/...")
                    self.page.goto(fallback_url, wait_until="domcontentloaded", timeout=60000)
                    self._wait_after_navigation()
                    return
            if "interrupted by another navigation" not in message:
                raise
            self.log("Messenger tu chuyen trang trong luc mo chat, dang cho trang on dinh...")
            self._wait_after_navigation()

    def _wait_after_navigation(self):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        try:
            self.page.wait_for_timeout(1200)
        except Exception:
            time.sleep(1.2)

    def _same_messenger_target(self, current_url: str, target_url: str) -> bool:
        current_key = _messenger_thread_key(current_url)
        target_key = _messenger_thread_key(target_url)
        return bool(current_key and target_key and current_key == target_key)

    def fill_message(self, target: str, message: str, clear_first: bool = True):
        self.open_conversation(target)
        editor = self._wait_for_message_editor()
        editor.click(timeout=10000)
        time.sleep(0.2)
        if clear_first:
            self.page.keyboard.press("Control+A")
            time.sleep(0.1)
        self.page.keyboard.insert_text(message)
        self.log("Da dien tin nhan vao o chat.")

    def send_message(self, target: str, message: str, clear_first: bool = True):
        self.fill_message(target, message, clear_first=clear_first)
        time.sleep(0.2)
        self.page.keyboard.press("Enter")
        self.log("Da bam Enter de gui tin nhan.")

    def read_chat_context(self, target: str, max_lines: int = 30) -> str:
        self.open_conversation(target)
        self._wait_for_message_editor()
        context = ""
        for attempt in range(3):
            self._scroll_chat_to_latest()
            try:
                self.page.wait_for_timeout(500 + attempt * 400)
            except Exception:
                time.sleep((500 + attempt * 400) / 1000)
            context = self._extract_visible_chat_context(max_lines=max_lines)
            if context:
                break
        if not context:
            raise RuntimeError(
                "Chua doc duoc noi dung chat. Hay keo Messenger den doan tin gan nhat roi bam lai."
            )
        self.log(f"Da doc ngu canh chat: {len(context.splitlines())} dong.")
        return context

    def _scroll_chat_to_latest(self):
        try:
            self.page.evaluate(
                """
                () => {
                    const editor = document.querySelector('[contenteditable="true"]');
                    const editorRect = editor ? editor.getBoundingClientRect() : null;
                    const chatCenter = editorRect ? editorRect.left + editorRect.width / 2 : window.innerWidth / 2;
                    const scrollables = Array.from(document.querySelectorAll('div, section, main')).filter((el) => {
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        if (el.scrollHeight <= el.clientHeight + 40) return false;
                        if (rect.height < 120 || rect.width < 180) return false;
                        if (rect.bottom < 120 || rect.top > window.innerHeight - 120) return false;
                        return rect.left - 80 <= chatCenter && rect.right + 80 >= chatCenter;
                    });
                    let best = null;
                    let bestScore = -1;
                    for (const el of scrollables) {
                        const rect = el.getBoundingClientRect();
                        const score = rect.height + Math.min(el.scrollHeight - el.clientHeight, 2000);
                        if (score > bestScore) {
                            best = el;
                            bestScore = score;
                        }
                    }
                    if (best) {
                        best.scrollTop = best.scrollHeight;
                    } else {
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                }
                """
            )
        except Exception:
            pass

    def _extract_visible_chat_context(self, max_lines: int = 30) -> str:
        lines = self.page.evaluate(
            """
            ({ maxLines }) => {
                const editor = document.querySelector('[contenteditable="true"]');
                const editorRect = editor ? editor.getBoundingClientRect() : null;
                const bottomLimit = editorRect ? editorRect.top - 8 : window.innerHeight - 80;
                const banned = new Set([
                    'messenger', 'search', 'active now', 'message', 'new message',
                    'write a message', 'type a message', 'send', 'like', 'more',
                    'calls', 'chats', 'people', 'settings', 'seen', 'delivered',
                    'sent', 'sending', 'typing'
                ]);
                const chatMargin = editorRect ? Math.max(90, Math.min(240, window.innerWidth * 0.16)) : 0;
                const chatLeft = editorRect ? Math.max(0, editorRect.left - chatMargin) : 40;
                const chatRight = editorRect ? Math.min(window.innerWidth, editorRect.right + chatMargin) : window.innerWidth - 20;
                const maxChatTextWidth = editorRect
                    ? Math.min(window.innerWidth * 0.78, editorRect.width + chatMargin * 2 + 120)
                    : window.innerWidth - 80;

                function visible(el) {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                        return false;
                    }
                    const rect = el.getBoundingClientRect();
                    const center = rect.left + rect.width / 2;
                    return rect.width > 18
                        && rect.height > 8
                        && rect.bottom > 70
                        && rect.top < bottomLimit
                        && center >= chatLeft
                        && center <= chatRight
                        && rect.width <= maxChatTextWidth;
                }

                function clean(text) {
                    return (text || '')
                        .replace(/\\s+/g, ' ')
                        .replace(/\\u00a0/g, ' ')
                        .trim();
                }

                function addRow(text, rect) {
                    text = clean(text);
                    if (!text || text.length < 1 || text.length > 600) return;
                    const lower = text.toLowerCase();
                    if (banned.has(lower)) return;
                    if (
                        lower.includes('conversation with') ||
                        lower.includes('messages loading') ||
                        lower.includes('compose write to') ||
                        lower.includes('end-to-end encrypted') ||
                        lower.includes('media & files') ||
                        lower.includes('privacy & support') ||
                        lower.includes('mute search') ||
                        lower.includes('groups') ||
                        lower.includes('communities')
                    ) return;
                    if (/^(\\d{1,2}:\\d{2}|\\d{1,2}:\\d{2}\\s?(am|pm)|mon|tue|wed|thu|fri|sat|sun)$/i.test(text)) return;
                    const myRightEdge = editorRect
                        ? editorRect.right - Math.max(70, editorRect.width * 0.14)
                        : window.innerWidth * 0.58;
                    const speaker = rect.right >= myRightEdge ? 'Me' : 'Them';
                    rows.push({ text: `${speaker}: ${text}`, top: Math.round(rect.top), left: Math.round(rect.left), width: Math.round(rect.width) });
                }

                const candidates = Array.from(document.querySelectorAll(
                    '[role="row"], div[dir="auto"], span[dir="auto"]'
                ));
                const rows = [];

                for (const el of candidates) {
                    if (!visible(el)) continue;
                    if (editor && (editor.contains(el) || el.contains(editor))) continue;
                    const text = clean(el.innerText || el.textContent);
                    const rect = el.getBoundingClientRect();
                    addRow(text, rect);
                }

                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                    const text = clean(node.nodeValue);
                    if (!text) continue;
                    const parent = node.parentElement;
                    if (!parent || !visible(parent)) continue;
                    if (editor && editor.contains(parent)) continue;
                    const rect = parent.getBoundingClientRect();
                    addRow(text, rect);
                }

                rows.sort((a, b) => a.top - b.top || a.left - b.left);

                const result = [];
                const seen = new Set();
                for (const row of rows) {
                    const key = `${row.text.toLowerCase()}::${Math.round(row.top / 8)}`;
                    if (seen.has(key)) continue;
                    const parentAlreadyHasText = result.some((prev) => {
                        return prev.text !== row.text
                            && Math.abs(prev.top - row.top) < 4
                            && (prev.text.includes(row.text) || row.text.includes(prev.text));
                    });
                    if (parentAlreadyHasText) continue;
                    seen.add(key);
                    result.push(row);
                }

                return result.slice(-maxLines).map((row) => row.text);
            }
            """,
            {"maxLines": max_lines},
        )
        if not isinstance(lines, list):
            return ""
        cleaned = []
        for line in lines:
            text = str(line).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return "\n".join(cleaned[-max_lines:])

    def _wait_for_message_editor(self):
        deadline = time.time() + 90
        last_count = 0

        while time.time() < deadline:
            handles = self.page.query_selector_all('[contenteditable="true"]')
            candidates = []

            for handle in handles:
                try:
                    if not handle.is_visible():
                        continue
                    box = handle.bounding_box()
                    if not box or box["width"] < 120 or box["height"] < 15:
                        continue
                    aria = (handle.get_attribute("aria-label") or "").lower()
                    text = ""
                    try:
                        text = (handle.inner_text(timeout=500) or "").lower()
                    except Exception:
                        pass

                    score = box["y"]
                    haystack = f"{aria} {text}"
                    if "message" in haystack or "tin nhan" in haystack or "tin nháº¯n" in haystack:
                        score += 5000
                    if box["height"] > 180:
                        score -= 1000
                    candidates.append((score, handle))
                except Exception:
                    continue

            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                return candidates[0][1]

            if len(handles) != last_count:
                last_count = len(handles)
                self.log("Dang tim o nhap tin nhan...")
            self.page.wait_for_timeout(1000)

        raise RuntimeError(
            "Khong tim thay o nhap tin nhan. Hay kiem tra ban da dang nhap Messenger "
            "va da mo dung cuoc tro chuyen."
        )


def _messenger_thread_key(raw_target: str) -> str:
    target = raw_target.strip()
    if not target:
        return ""
    try:
        parsed = urlparse(target)
    except Exception:
        return target.lstrip("@").strip("/")

    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host in ("messenger.com", "www.messenger.com"):
        if len(parts) >= 2 and parts[0] == "t":
            return parts[1]
        if len(parts) >= 3 and parts[0] == "e2ee" and parts[1] == "t":
            return parts[2]
    if host in ("facebook.com", "www.facebook.com"):
        if len(parts) >= 3 and parts[0] == "messages" and parts[1] == "t":
            return parts[2]
        if len(parts) >= 4 and parts[0] == "messages" and parts[1] == "e2ee" and parts[2] == "t":
            return parts[3]
    if host in ("m.me", "www.m.me") and parts:
        return parts[0]
    if not parsed.scheme and not parsed.netloc:
        return target.lstrip("@").strip("/")
    return ""


def normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    if not target:
        raise ValueError("Hay nhap link Messenger hoac username/id cua nguoi nhan.")

    if target.startswith(("http://", "https://")):
        parsed = urlparse(target)
        host = parsed.netloc.lower()
        allowed_hosts = (
            "messenger.com",
            "www.messenger.com",
            "facebook.com",
            "www.facebook.com",
            "m.me",
            "www.m.me",
        )
        if host not in allowed_hosts:
            raise ValueError("Link phai la messenger.com, facebook.com/messages, hoac m.me.")
        parts = [part for part in parsed.path.split("/") if part]
        thread_key = _messenger_thread_key(target)
        if thread_key:
            return f"https://www.messenger.com/t/{quote(thread_key)}"
        if host in ("messenger.com", "www.messenger.com") and len(parts) >= 3 and parts[0] == "e2ee" and parts[1] == "t":
            return f"https://www.messenger.com/t/{quote(parts[2])}"
        if host in ("m.me", "www.m.me") and parts:
            return f"https://www.messenger.com/t/{quote(parts[0])}"
        return target

    cleaned = target.lstrip("@").strip("/")
    return f"https://www.messenger.com/t/{quote(cleaned)}"


def load_contacts() -> list[Contact]:
    if not CONTACTS_FILE.exists():
        return []
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
        return [Contact(str(item["name"]), str(item["target"])) for item in data]
    except Exception:
        return []


def save_contacts(contacts: list[Contact]):
    data = [{"name": contact.name, "target": contact.target} for contact in contacts]
    CONTACTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_ai_draft(
    *,
    api_key: str,
    model: str,
    recipient_name: str,
    tone: str,
    goal: str,
    context: str,
    base_url: str | None = None,
) -> str:
    return generate_openai_draft(
        api_key=api_key,
        base_url=base_url,
        model=model,
        recipient_name=recipient_name,
        tone=tone,
        goal=goal,
        context=context,
    )


def _extract_api_error(raw_detail: str) -> str:
    try:
        data = json.loads(raw_detail)
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    except Exception:
        pass
    return raw_detail[:500] or "KhÃ´ng rÃµ lá»—i."


def _extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    parts: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts)


def generate_openai_draft(
    *,
    api_key: str,
    model: str,
    recipient_name: str,
    tone: str,
    goal: str,
    context: str,
    base_url: str | None = None,
) -> str:
    if not api_key:
        raise RuntimeError(
            "Thieu API key. Dan key vao o API key, hoac dat bien moi truong OPENAI_API_KEY."
        )
    if not goal and not context:
        raise RuntimeError("Nhap y muon noi hoac boi canh truoc da.")

    instructions = (
        "You draft short Messenger replies for the user. Return only the message text, "
        "with no explanation and no quotation marks. Write in natural Vietnamese with proper "
        "diacritics when possible. Keep it respectful, honest, and not pushy. Do not spam, "
        "manipulate emotions, pressure the recipient, or pretend feelings/events that were not provided. "
        "The chat context may contain one or several ideas in the latest message; infer the relevant intent "
        "and answer the important parts in one single Messenger message. Do not split the answer into multiple "
        "messages or numbered alternatives. Chat lines may be prefixed with Me: and Them:. Reply to the latest "
        "Them: message when present, and do not answer your own Me: messages. Never say that you cannot see a new "
        "message; if context is short, answer the latest visible Them: message. If the latest message mentions "
        "someone dying, passing away, or slang like 'chet', 'mat', 'qua doi', 'ngom', reply with sincere condolences "
        "and support; do not joke or ask for a different message. "
        "If the request looks like harassment or repeated unwanted contact, write one brief respectful "
        "message that gives space."
    )
    user_input = (
        f"Recipient name: {recipient_name or 'ban'}\n"
        f"Tone: {tone or 'tu nhien, lich su'}\n"
        f"Known chat context:\n{context or '(none)'}\n\n"
        f"What the user wants to say:\n{goal}\n\n"
        "Draft exactly 1 short Messenger message, max 3 sentences. If there are multiple ideas, combine them into this one message."
    )
    endpoint = f"{(base_url or DEFAULT_AI_BASE_URL).strip().rstrip('/')}/chat/completions"
    payload = {
        "model": (model or DEFAULT_AI_MODEL).strip(),
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_input},
        ],
        "max_tokens": 220,
        "temperature": 0.8,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": API_USER_AGENT,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API loi {exc.code}: {_extract_api_error(detail)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Khong ket noi duoc API: {exc.reason}") from exc

    draft = _extract_chat_completion_text(data).strip()
    if not draft:
        raise RuntimeError("API tra ve rong. Thu lai voi y muon noi cu the hon.")
    return draft


def _extract_chat_completion_text(data: dict) -> str:
    choices = data.get("choices", [])
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
    return _extract_response_text(data)


def _last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return ""


def _strip_chat_speaker(text: str) -> str:
    return re.sub(r"^(me|them|ban|ho|bạn|họ)\s*:\s*", "", text.strip(), flags=re.IGNORECASE)


def _auto_context_signature(text: str) -> str:
    def status_key(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value.lower())
        without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return without_marks.replace("đ", "d")

    volatile_exact = {
        "seen",
        "delivered",
        "sent",
        "sending",
        "you sent",
        "active now",
        "typing",
        "is typing",
        "ban da xem",
        "da xem",
        "da gui",
        "da nhan",
        "dang gui",
        "dang nhap",
        "dang hoat dong",
        "vua xong",
    }
    volatile_prefixes = (
        "seen ",
        "seen by ",
        "delivered ",
        "sent ",
        "you sent",
        "you saw",
        "active ",
        "typing ",
        "is typing",
        "ban da xem",
        "da xem ",
        "da gui ",
        "da nhan ",
        "dang nhap",
    )
    signature_lines = []
    for line in text.splitlines():
        cleaned = " ".join(line.strip().split())
        if not cleaned:
            continue
        lower = cleaned.lower()
        key = status_key(lower)
        status_part = _strip_chat_speaker(key)
        if status_part in volatile_exact or status_part.startswith(volatile_prefixes):
            continue
        if status_part in {"am", "pm"}:
            continue
        if any(token in status_part for token in ("reacted ", "da bay to cam xuc")):
            continue
        if re.match(r"^\d{1,2}:\d{2}(\s?(am|pm))?$", status_part):
            continue
        if re.match(r"^\d{1,2}/\d{1,2}(/\d{2,4})?$", status_part):
            continue
        signature_lines.append(lower)
    return "\n".join(signature_lines)


def _latest_incoming_line(signature: str) -> str:
    fallback = ""
    for line in reversed(signature.splitlines()):
        cleaned = line.strip()
        if not cleaned:
            continue
        if not fallback:
            fallback = cleaned
        if cleaned.lower().startswith(("them:", "ho:", "họ:")):
            return cleaned
    return "" if fallback.lower().startswith(("me:", "ban:", "bạn:")) else fallback


def _same_message_text(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        return " ".join(_strip_chat_speaker(value).lower().split())

    return bool(left and right and normalize(left) == normalize(right))


class MessengerToolApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Messenger Edge Tool")
        self.geometry("760x560")
        self.minsize(700, 500)

        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.session = MessengerSession(self.thread_log)
        self.contacts = load_contacts()
        self.busy = False

        self.contact_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.clear_var = tk.BooleanVar(value=True)
        self.ai_key_var = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        self.ai_base_url_var = tk.StringVar(value=DEFAULT_AI_BASE_URL)
        self.ai_model_var = tk.StringVar(value=DEFAULT_AI_MODEL)
        self.ai_tone_var = tk.StringVar(value="Tá»± nhiÃªn, thÃ¢n thiá»‡n")

        self._build_ui()
        self._refresh_contacts()
        self.after(150, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(4, weight=1)
        self.geometry("860x760")
        self.minsize(760, 650)

        top = ttk.Frame(self, padding=16)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="LiÃªn há»‡ Ä‘Ã£ lÆ°u").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.contact_box = ttk.Combobox(top, textvariable=self.contact_var, state="readonly")
        self.contact_box.grid(row=0, column=1, sticky="ew")
        self.contact_box.bind("<<ComboboxSelected>>", self._select_contact)

        ttk.Label(top, text="TÃªn gá»£i nhá»›").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        ttk.Entry(top, textvariable=self.name_var).grid(row=1, column=1, sticky="ew", pady=(10, 0))

        ttk.Label(top, text="Link / username / id").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        ttk.Entry(top, textvariable=self.target_var).grid(row=2, column=1, sticky="ew", pady=(10, 0))

        buttons = ttk.Frame(top)
        buttons.grid(row=3, column=1, sticky="w", pady=(12, 0))
        ttk.Button(buttons, text="LÆ°u liÃªn há»‡", command=self.save_contact).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Má»Ÿ Messenger", command=self.open_chat).grid(row=0, column=1, padx=(0, 8))
        ttk.Checkbutton(buttons, text="XÃ³a Ã´ chat trÆ°á»›c khi Ä‘iá»n", variable=self.clear_var).grid(row=0, column=2)

        ai_frame = ttk.LabelFrame(self, text="AI soáº¡n tin", padding=(16, 10))
        ai_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        ai_frame.columnconfigure(1, weight=1)
        ai_frame.columnconfigure(3, weight=1)

        ttk.Label(ai_frame, text="OpenAI API key").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(ai_frame, textvariable=self.ai_key_var, show="*").grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Label(ai_frame, text="Model").grid(row=0, column=2, sticky="w", padx=(0, 10))
        ttk.Entry(ai_frame, textvariable=self.ai_model_var, width=18).grid(row=0, column=3, sticky="ew")

        ttk.Label(ai_frame, text="Giá»ng vÄƒn").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        self.ai_tone_box = ttk.Combobox(
            ai_frame,
            textvariable=self.ai_tone_var,
            values=[
                "Tá»± nhiÃªn, thÃ¢n thiá»‡n",
                "Dá»… thÆ°Æ¡ng, vá»«a pháº£i",
                "Lá»‹ch sá»±, tinh táº¿",
                "HÃ i hÆ°á»›c nháº¹",
                "Ngáº¯n gá»n, rÃµ Ã½",
            ],
        )
        self.ai_tone_box.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(10, 0))

        ttk.Label(ai_frame, text="Bá»‘i cáº£nh").grid(row=2, column=0, sticky="nw", padx=(0, 10), pady=(10, 0))
        self.ai_context_text = tk.Text(ai_frame, height=3, wrap="word", undo=True)
        self.ai_context_text.grid(row=2, column=1, columnspan=3, sticky="ew", pady=(10, 0))

        ttk.Label(ai_frame, text="Ã muá»‘n nÃ³i").grid(row=3, column=0, sticky="nw", padx=(0, 10), pady=(10, 0))
        self.ai_goal_text = tk.Text(ai_frame, height=3, wrap="word", undo=True)
        self.ai_goal_text.grid(row=3, column=1, columnspan=3, sticky="ew", pady=(10, 0))

        ai_buttons = ttk.Frame(ai_frame)
        ai_buttons.grid(row=4, column=1, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(ai_buttons, text="Láº¥y Ã´ tin nháº¯n lÃ m Ã½", command=self.use_message_as_goal).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(ai_buttons, text="AI soáº¡n nhÃ¡p", command=self.draft_with_ai).grid(row=0, column=1)

        message_frame = ttk.Frame(self, padding=(16, 0, 16, 12))
        message_frame.grid(row=2, column=0, sticky="nsew")
        message_frame.columnconfigure(0, weight=1)
        message_frame.rowconfigure(1, weight=1)

        ttk.Label(message_frame, text="Tin nháº¯n").grid(row=0, column=0, sticky="w")
        self.message_text = tk.Text(message_frame, height=11, wrap="word", undo=True)
        self.message_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        action_frame = ttk.Frame(self, padding=(16, 0, 16, 12))
        action_frame.grid(row=3, column=0, sticky="ew")
        action_frame.columnconfigure(0, weight=1)
        ttk.Button(action_frame, text="Äiá»n tin nháº¯n", command=self.fill_message).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_frame, text="Gá»­i cÃ³ xÃ¡c nháº­n", command=self.confirm_and_send).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(action_frame, text="ÄÃ³ng Edge", command=self.close_browser).grid(row=0, column=3)

        log_frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        ttk.Label(log_frame, text="Tráº¡ng thÃ¡i").grid(row=0, column=0, sticky="w")
        self.log_text = tk.Text(log_frame, height=7, wrap="word", state="disabled")
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.log("Sáºµn sÃ ng. Láº§n Ä‘áº§u cháº¡y hÃ£y Ä‘Äƒng nháº­p Messenger trong Edge do tool má»Ÿ.")

    def _refresh_contacts(self):
        names = [contact.name for contact in self.contacts]
        self.contact_box["values"] = names

    def _select_contact(self, _event=None):
        selected = self.contact_var.get()
        for contact in self.contacts:
            if contact.name == selected:
                self.name_var.set(contact.name)
                self.target_var.set(contact.target)
                return

    def save_contact(self):
        name = self.name_var.get().strip()
        target = self.target_var.get().strip()
        if not name or not target:
            messagebox.showwarning("Thiáº¿u thÃ´ng tin", "Nháº­p tÃªn gá»£i nhá»› vÃ  link/username/id trÆ°á»›c Ä‘Ã£.")
            return

        try:
            normalize_target(target)
        except ValueError as exc:
            messagebox.showwarning("Link chÆ°a Ä‘Ãºng", str(exc))
            return

        for index, contact in enumerate(self.contacts):
            if contact.name == name:
                self.contacts[index] = Contact(name, target)
                break
        else:
            self.contacts.append(Contact(name, target))

        save_contacts(self.contacts)
        self._refresh_contacts()
        self.contact_var.set(name)
        self.log(f"ÄÃ£ lÆ°u liÃªn há»‡: {name}")

    def open_chat(self):
        target = self._require_target()
        if target:
            self._run_task(lambda: self.session.open_conversation(target))

    def fill_message(self):
        target = self._require_target()
        message = self._require_message()
        if target and message:
            self._run_task(lambda: self.session.fill_message(target, message, self.clear_var.get()))

    def confirm_and_send(self):
        target = self._require_target()
        message = self._require_message()
        if not target or not message:
            return
        ok = messagebox.askyesno(
            "XÃ¡c nháº­n gá»­i",
            "Tool sáº½ Ä‘iá»n tin nháº¯n rá»“i báº¥m Enter trong Messenger. Báº¡n cháº¯c muá»‘n gá»­i chá»©?",
        )
        if ok:
            self._run_task(lambda: self.session.send_message(target, message, self.clear_var.get()))

    def use_message_as_goal(self):
        message = self.message_text.get("1.0", "end").strip()
        if not message:
            messagebox.showwarning("Thiáº¿u ná»™i dung", "Ã” tin nháº¯n Ä‘ang trá»‘ng.")
            return
        self.ai_goal_text.delete("1.0", "end")
        self.ai_goal_text.insert("1.0", message)
        self.log("ÄÃ£ Ä‘Æ°a ná»™i dung Ã´ tin nháº¯n sang Ã½ muá»‘n nÃ³i cho AI.")

    def draft_with_ai(self):
        api_key = self.ai_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = self.ai_base_url_var.get().strip() or DEFAULT_AI_BASE_URL
        model = self.ai_model_var.get().strip() or DEFAULT_AI_MODEL
        recipient_name = self.name_var.get().strip() or self.contact_var.get().strip()
        tone = self.ai_tone_var.get().strip()
        context = self.ai_context_text.get("1.0", "end").strip()
        goal = self.ai_goal_text.get("1.0", "end").strip()

        def task():
            self.thread_log("AI Ä‘ang soáº¡n báº£n nhÃ¡p...")
            draft = generate_ai_draft(
                api_key=api_key,
                model=model,
                recipient_name=recipient_name,
                tone=tone,
                goal=goal,
                context=context,
            )
            self.events.put(("ai_draft", draft))

        self._run_task(task)

    def close_browser(self):
        self._run_task(self.session.stop)

    def _require_target(self) -> str | None:
        target = self.target_var.get().strip()
        try:
            normalize_target(target)
        except ValueError as exc:
            messagebox.showwarning("Thiáº¿u ngÆ°á»i nháº­n", str(exc))
            return None
        return target

    def _require_message(self) -> str | None:
        message = self.message_text.get("1.0", "end").strip()
        if not message:
            messagebox.showwarning("Thiáº¿u tin nháº¯n", "Nháº­p ná»™i dung tin nháº¯n trÆ°á»›c Ä‘Ã£.")
            return None
        return message

    def _run_task(self, task):
        if self.busy:
            messagebox.showinfo("Äang cháº¡y", "Äá»£i thao tÃ¡c hiá»‡n táº¡i xong má»™t chÃºt nha.")
            return
        self.busy = True
        self.log("Äang xá»­ lÃ½...")

        def worker():
            try:
                task()
            except Exception as exc:
                self.thread_log(f"Lá»—i: {exc}")
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("done", ""))

        threading.Thread(target=worker, daemon=True).start()

    def thread_log(self, message: str):
        self.events.put(("log", message))

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_events(self):
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "log":
                    self.log(message)
                elif kind == "error":
                    messagebox.showerror("CÃ³ lá»—i", message)
                elif kind == "ai_draft":
                    self.message_text.delete("1.0", "end")
                    self.message_text.insert("1.0", message)
                    self.log("AI Ä‘Ã£ soáº¡n báº£n nhÃ¡p vÃ o Ã´ tin nháº¯n.")
                elif kind == "done":
                    self.busy = False
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _on_close(self):
        try:
            self.session.stop()
        finally:
            self.destroy()


def generate_ai_draft_clean(
    *,
    api_key: str,
    model: str,
    recipient_name: str,
    tone: str,
    goal: str,
    context: str,
    base_url: str | None = None,
) -> str:
    return generate_openai_draft(
        api_key=api_key,
        base_url=base_url,
        model=model,
        recipient_name=recipient_name,
        tone=tone,
        goal=goal,
        context=context,
    )


class ModernMessengerToolApp(tk.Tk):
    BG = "#f4f7fb"
    PANEL = "#ffffff"
    TEXT = "#111827"
    MUTED = "#526070"
    BORDER = "#d8dee9"
    BLUE = "#2563eb"
    BLUE_DARK = "#1d4ed8"
    GREEN = "#0f8b5f"
    RED = "#b42318"
    INPUT = "#fbfdff"

    def __init__(self):
        super().__init__()
        self.title("Messenger Edge Tool")
        self.geometry("980x720")
        self.minsize(860, 640)
        self.configure(bg=self.BG)

        self.base_font = tkfont.Font(family="Segoe UI", size=10)
        self.label_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
        self.button_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.text_font = tkfont.Font(family="Segoe UI", size=11)

        self.option_add("*Font", self.base_font)
        self._setup_ttk()

        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.tasks: queue.Queue = queue.Queue()
        self.session = MessengerSession(self.thread_log)
        self.contacts = load_contacts()
        self.busy = False
        self.closing = False
        self.auto_draft_enabled = False
        self.auto_after_id = None
        self.auto_last_context = ""
        self.auto_last_sent_text = ""
        self.auto_last_replied_incoming = ""
        self.auto_sent_count = 0
        self.auto_interval_ms = 12000
        self.active_page = "compose"

        self.contact_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.clear_var = tk.BooleanVar(value=True)
        self.auto_send_demo_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.ai_key_var = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        self.ai_base_url_var = tk.StringVar(value=DEFAULT_AI_BASE_URL)
        self.ai_model_var = tk.StringVar(value=DEFAULT_AI_MODEL)
        self.ai_tone_var = tk.StringVar(value="Tu nhien, than thien")

        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.auto_button = None

        self._build_ui()
        self._refresh_contacts()
        self.worker_thread = threading.Thread(target=self._task_worker, daemon=True)
        self.worker_thread.start()
        self.after(150, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log("San sang. Lan dau chay hay dang nhap Messenger trong Edge do tool mo.")

    def _setup_ttk(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure(
            "Tool.TCombobox",
            fieldbackground=self.INPUT,
            background=self.PANEL,
            foreground=self.TEXT,
            bordercolor=self.BORDER,
            arrowsize=14,
        )

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg="#101827", width=190)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        brand = tk.Label(
            sidebar,
            text="Messenger\nTool",
            bg="#101827",
            fg="#f8fafc",
            font=tkfont.Font(family="Segoe UI", size=16, weight="bold"),
            justify="left",
            anchor="w",
        )
        brand.pack(fill="x", padx=18, pady=(22, 20))

        self._nav_button(sidebar, "compose", "Soan tin")
        self._nav_button(sidebar, "ai", "AI viet nhap")
        self._nav_button(sidebar, "log", "Nhat ky")

        main = tk.Frame(self, bg=self.BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        header = tk.Frame(main, bg=self.BG)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 10))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Nhan tin Messenger qua Edge",
            bg=self.BG,
            fg=self.TEXT,
            font=self.title_font,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.status_label = tk.Label(
            header,
            textvariable=self.status_var,
            bg="#e8f2ff",
            fg=self.BLUE_DARK,
            font=self.label_font,
            padx=12,
            pady=6,
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        page_area = tk.Frame(main, bg=self.BG)
        page_area.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 20))
        page_area.columnconfigure(0, weight=1)
        page_area.rowconfigure(0, weight=1)

        self.pages["compose"] = self._compose_page(page_area)
        self.pages["ai"] = self._ai_page(page_area)
        self.pages["log"] = self._log_page(page_area)
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self._show_page("compose")

    def _nav_button(self, parent: tk.Frame, page: str, text: str):
        button = tk.Button(
            parent,
            text=text,
            command=lambda: self._show_page(page),
            anchor="w",
            relief="flat",
            bd=0,
            padx=18,
            pady=12,
            bg="#101827",
            fg="#cbd5e1",
            activebackground="#1f2a44",
            activeforeground="#ffffff",
            font=self.button_font,
            cursor="hand2",
        )
        button.pack(fill="x", padx=10, pady=3)
        self.nav_buttons[page] = button

    def _show_page(self, page: str):
        self.active_page = page
        self.pages[page].tkraise()
        for key, button in self.nav_buttons.items():
            if key == page:
                button.configure(bg=self.BLUE, fg="#ffffff", activebackground=self.BLUE_DARK)
            else:
                button.configure(bg="#101827", fg="#cbd5e1", activebackground="#1f2a44")

    def _panel(self, parent: tk.Frame) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL, highlightthickness=1, highlightbackground=self.BORDER)
        frame.columnconfigure(0, weight=1)
        return frame

    def _section_title(self, parent: tk.Frame, text: str):
        tk.Label(parent, text=text, bg=self.PANEL, fg=self.TEXT, font=self.label_font, anchor="w").pack(
            fill="x", padx=18, pady=(16, 8)
        )

    def _label(self, parent: tk.Frame, text: str, row: int, column: int = 0, sticky: str = "w"):
        tk.Label(parent, text=text, bg=self.PANEL, fg=self.MUTED, font=self.label_font, anchor="w").grid(
            row=row, column=column, sticky=sticky, padx=(0, 10), pady=(8, 4)
        )

    def _entry(self, parent: tk.Frame, textvariable: tk.StringVar, show: str | None = None) -> tk.Entry:
        entry = tk.Entry(
            parent,
            textvariable=textvariable,
            show=show,
            bg=self.INPUT,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            highlightcolor=self.BLUE,
        )
        return entry

    def _text_box(self, parent: tk.Frame, height: int) -> tuple[tk.Text, tk.Frame]:
        wrapper = tk.Frame(parent, bg=self.PANEL)
        wrapper.columnconfigure(0, weight=1)
        wrapper.rowconfigure(0, weight=1)
        text = tk.Text(
            wrapper,
            height=height,
            wrap="word",
            undo=True,
            bg=self.INPUT,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground="#bfdbfe",
            selectforeground=self.TEXT,
            relief="solid",
            bd=1,
            padx=10,
            pady=10,
            font=self.text_font,
        )
        scroll = tk.Scrollbar(wrapper, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return text, wrapper

    def _button(self, parent: tk.Frame, text: str, command, kind: str = "secondary") -> tk.Button:
        colors = {
            "primary": (self.BLUE, "#ffffff", self.BLUE_DARK),
            "success": (self.GREEN, "#ffffff", "#0a6f4b"),
            "danger": (self.RED, "#ffffff", "#8a1f16"),
            "secondary": ("#edf2f7", self.TEXT, "#dbe4ee"),
        }
        bg, fg, active = colors[kind]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=14,
            pady=9,
            font=self.button_font,
            cursor="hand2",
        )

    def _compose_page(self, parent: tk.Frame) -> tk.Frame:
        page = tk.Frame(parent, bg=self.BG)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        contact = self._panel(page)
        contact.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        contact.columnconfigure(1, weight=1)
        contact.columnconfigure(3, weight=1)

        form = tk.Frame(contact, bg=self.PANEL)
        form.pack(fill="x", padx=18, pady=12)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        self._label(form, "Lien he da luu", 0, 0)
        self.contact_box = ttk.Combobox(form, textvariable=self.contact_var, state="readonly", style="Tool.TCombobox")
        self.contact_box.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(0, 8))
        self.contact_box.bind("<<ComboboxSelected>>", self._select_contact)

        self._label(form, "Ten goi nho", 0, 1)
        self._entry(form, self.name_var).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 8))

        self._label(form, "Link / username / id", 0, 2)
        self._entry(form, self.target_var).grid(row=1, column=2, columnspan=2, sticky="ew", pady=(0, 8))

        row2 = tk.Frame(form, bg=self.PANEL)
        row2.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self._button(row2, "Luu lien he", self.save_contact).pack(side="left", padx=(0, 8))
        self._button(row2, "Mo Messenger", self.open_chat, "primary").pack(side="left", padx=(0, 14))
        tk.Checkbutton(
            row2,
            text="Xoa o chat truoc khi dien",
            variable=self.clear_var,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.PANEL,
            activeforeground=self.TEXT,
            selectcolor=self.PANEL,
        ).pack(side="left")

        message = self._panel(page)
        message.grid(row=1, column=0, sticky="nsew")
        message.rowconfigure(1, weight=1)
        self._section_title(message, "Tin nhan")
        self.message_text, message_box = self._text_box(message, 12)
        message_box.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        actions = tk.Frame(message, bg=self.PANEL)
        actions.pack(fill="x", padx=18, pady=(0, 18))
        self._button(actions, "Dien tin nhan", self.fill_message, "primary").pack(side="left", padx=(0, 8))
        self._button(actions, "Gui co xac nhan", self.confirm_and_send, "success").pack(side="left", padx=(0, 8))
        self._button(actions, "Dong Edge", self.close_browser, "danger").pack(side="right")

        return page

    def _ai_page(self, parent: tk.Frame) -> tk.Frame:
        page = tk.Frame(parent, bg=self.BG)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)

        panel = self._panel(page)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.rowconfigure(2, weight=1)
        panel.rowconfigure(4, weight=1)

        self._section_title(panel, "AI soan ban nhap")

        form = tk.Frame(panel, bg=self.PANEL)
        form.pack(fill="x", padx=18, pady=(0, 8))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        self._label(form, "API key", 0, 0)
        self._entry(form, self.ai_key_var, show="*").grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 12))
        self._label(form, "Model", 0, 2)
        self._entry(form, self.ai_model_var).grid(row=1, column=2, columnspan=2, sticky="ew")

        self._label(form, "Base URL", 2, 0)
        self._entry(form, self.ai_base_url_var).grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 8))

        self._label(form, "Giong van", 4, 0)
        tone_box = ttk.Combobox(
            form,
            textvariable=self.ai_tone_var,
            values=[
                "Tu nhien, than thien",
                "De thuong, vua phai",
                "Lich su, tinh te",
                "Hai huoc nhe",
                "Ngan gon, ro y",
            ],
            style="Tool.TCombobox",
        )
        tone_box.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(0, 8))

        text_area = tk.Frame(panel, bg=self.PANEL)
        text_area.pack(fill="both", expand=True, padx=18, pady=(4, 12))
        text_area.columnconfigure(0, weight=1)
        text_area.columnconfigure(1, weight=1)
        text_area.rowconfigure(1, weight=1)

        tk.Label(text_area, text="Boi canh", bg=self.PANEL, fg=self.MUTED, font=self.label_font).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        tk.Label(text_area, text="Y muon noi", bg=self.PANEL, fg=self.MUTED, font=self.label_font).grid(
            row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 6)
        )
        self.ai_context_text, context_box = self._text_box(text_area, 10)
        context_box.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.ai_goal_text, goal_box = self._text_box(text_area, 10)
        goal_box.grid(row=1, column=1, sticky="nsew", padx=(6, 0))

        actions = tk.Frame(panel, bg=self.PANEL)
        actions.pack(fill="x", padx=18, pady=(0, 18))
        self._button(actions, "Doc chat", self.read_chat_context_from_messenger).pack(side="left", padx=(0, 8))
        self._button(actions, "Doc chat + dien tra loi", self.reply_from_chat_context, "success").pack(
            side="left", padx=(0, 8)
        )
        self.auto_button = self._button(actions, "Bat auto khi co tin moi", self.toggle_auto_draft, "secondary")
        self.auto_button.pack(side="left", padx=(0, 8))
        self._button(actions, "Lay o tin nhan lam y", self.use_message_as_goal).pack(side="left", padx=(0, 8))
        self._button(actions, "AI soan nhap", self.draft_with_ai, "primary").pack(side="left")

        demo_row = tk.Frame(panel, bg=self.PANEL)
        demo_row.pack(fill="x", padx=18, pady=(0, 18))
        tk.Checkbutton(
            demo_row,
            text="Demo auto gui: tu bam Enter sau khi AI soan",
            variable=self.auto_send_demo_var,
            bg=self.PANEL,
            fg=self.RED,
            activebackground=self.PANEL,
            activeforeground=self.RED,
            selectcolor=self.PANEL,
            font=self.label_font,
        ).pack(side="left")

        return page

    def _log_page(self, parent: tk.Frame) -> tk.Frame:
        page = tk.Frame(parent, bg=self.BG)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)

        panel = self._panel(page)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.rowconfigure(1, weight=1)
        self._section_title(panel, "Nhat ky trang thai")
        self.log_text, log_box = self._text_box(panel, 22)
        self.log_text.configure(state="disabled", font=tkfont.Font(family="Consolas", size=10))
        log_box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        return page

    def _refresh_contacts(self):
        names = [contact.name for contact in self.contacts]
        self.contact_box["values"] = names

    def _select_contact(self, _event=None):
        selected = self.contact_var.get()
        for contact in self.contacts:
            if contact.name == selected:
                self.name_var.set(contact.name)
                self.target_var.set(contact.target)
                return

    def save_contact(self):
        name = self.name_var.get().strip()
        target = self.target_var.get().strip()
        if not name or not target:
            messagebox.showwarning("Thieu thong tin", "Nhap ten goi nho va link/username/id truoc da.")
            return

        try:
            normalize_target(target)
        except ValueError as exc:
            messagebox.showwarning("Link chua dung", str(exc))
            return

        for index, contact in enumerate(self.contacts):
            if contact.name == name:
                self.contacts[index] = Contact(name, target)
                break
        else:
            self.contacts.append(Contact(name, target))

        save_contacts(self.contacts)
        self._refresh_contacts()
        self.contact_var.set(name)
        self.log(f"Da luu lien he: {name}")

    def open_chat(self):
        target = self._require_target()
        if target:
            self._run_task(lambda: self.session.open_conversation(target))

    def fill_message(self):
        target = self._require_target()
        message = self._require_message()
        if target and message:
            self._run_task(lambda: self.session.fill_message(target, message, self.clear_var.get()))

    def confirm_and_send(self):
        target = self._require_target()
        message = self._require_message()
        if not target or not message:
            return
        ok = messagebox.askyesno(
            "Xac nhan gui",
            "Tool se dien tin nhan roi bam Enter trong Messenger. Ban chac muon gui chu?",
        )
        if ok:
            self._run_task(lambda: self.session.send_message(target, message, self.clear_var.get()))

    def use_message_as_goal(self):
        message = self.message_text.get("1.0", "end").strip()
        if not message:
            messagebox.showwarning("Thieu noi dung", "O tin nhan dang trong.")
            return
        self.ai_goal_text.delete("1.0", "end")
        self.ai_goal_text.insert("1.0", message)
        self.log("Da dua noi dung o tin nhan sang y muon noi cho AI.")
        self._show_page("ai")

    def read_chat_context_from_messenger(self):
        target = self._require_target()
        if not target:
            return

        def task():
            self.thread_log("Dang doc ngu canh tu Messenger...")
            context = self.session.read_chat_context(target)
            self.events.put(("chat_context", context))

        self._run_task(task)

    def reply_from_chat_context(self):
        target = self._require_target()
        if not target:
            return

        api_key = self.ai_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = self.ai_base_url_var.get().strip() or DEFAULT_AI_BASE_URL
        model = self.ai_model_var.get().strip() or DEFAULT_AI_MODEL
        recipient_name = self.name_var.get().strip() or self.contact_var.get().strip()
        tone = self.ai_tone_var.get().strip()
        extra_goal = self.ai_goal_text.get("1.0", "end").strip()
        goal = extra_goal or (
            "Doc ngu canh doan chat va viet cau tra loi phu hop cho tin nhan moi nhat. "
            "Neu co dong 'Them:' thi uu tien tra loi dong 'Them:' moi nhat, khong tra loi dong 'Me:'. "
            "Khong duoc noi la chua thay tin nhan moi. Tra loi ngan gon, tu nhien, khong hoi don dap."
        )

        def task():
            self.thread_log("Dang doc chat va soan cau tra loi...")
            context = self.session.read_chat_context(target)
            self.events.put(("chat_context", context))
            draft = generate_ai_draft_clean(
                api_key=api_key,
                model=model,
                recipient_name=recipient_name,
                tone=tone,
                goal=goal,
                context=context,
                base_url=base_url,
            )
            self.session.fill_message(target, draft, self.clear_var.get())
            self.events.put(("ai_draft", draft))

        self._run_task(task)

    def toggle_auto_draft(self):
        if self.auto_draft_enabled:
            self.stop_auto_draft()
            return

        target = self._require_target()
        if not target:
            return
        api_key = self.ai_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = self.ai_base_url_var.get().strip() or DEFAULT_AI_BASE_URL
        if not api_key:
            messagebox.showwarning("Thieu API key", "Nhap API key truoc khi bat auto.")
            return

        if self.auto_send_demo_var.get():
            ok = messagebox.askyesno(
                "Bat demo auto gui",
                "Che do demo se tu bam Enter gui tin sau khi AI soan. "
                "Chi nen dung voi nick/chat test hoac nguoi da dong y. Bat che do nay chu?",
            )
            if not ok:
                self.auto_send_demo_var.set(False)
                return

        self.auto_draft_enabled = True
        self.auto_last_context = ""
        self.auto_last_sent_text = ""
        self.auto_last_replied_incoming = ""
        self.auto_sent_count = 0
        if self.auto_button:
            button_text = "Tat demo auto gui" if self.auto_send_demo_var.get() else "Tat auto dien nhap"
            self.auto_button.configure(text=button_text, bg=self.RED, fg="#ffffff", activebackground="#8a1f16")
        if self.auto_send_demo_var.get():
            self.log("Da bat Demo auto gui. Tool se ghi nho chat hien tai, moi tin moi chi tu gui 1 lan va tiep tuc cho tin ke tiep.")
            self._set_status("Demo auto gui dang bat", busy=True)
        else:
            self.log("Da bat Auto dien nhap. Tool se ghi nho chat hien tai va chi dien khi co tin moi.")
            self._set_status("Auto dien nhap dang bat", busy=True)
        self._schedule_auto_draft_tick(100)

    def stop_auto_draft(self):
        self.auto_draft_enabled = False
        if self.auto_after_id is not None:
            try:
                self.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        if self.auto_button:
            self.auto_button.configure(
                text="Bat auto khi co tin moi",
                bg="#edf2f7",
                fg=self.TEXT,
                activebackground="#dbe4ee",
            )
        self._set_status("Ready")
        self.log("Da tat Auto.")

    def _schedule_auto_draft_tick(self, delay_ms: int | None = None):
        if not self.auto_draft_enabled or self.closing or self.auto_after_id is not None:
            return
        self.auto_after_id = self.after(delay_ms or self.auto_interval_ms, self._auto_draft_tick)

    def _auto_draft_tick(self):
        self.auto_after_id = None
        if not self.auto_draft_enabled or self.closing:
            return
        if self.busy:
            self._schedule_auto_draft_tick(2000)
            return

        target = self.target_var.get().strip()
        try:
            normalize_target(target)
        except ValueError as exc:
            self.thread_log(f"Auto: {exc}. Auto van dang bat, se thu lai sau.")
            self._schedule_auto_draft_tick()
            return

        api_key = self.ai_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = self.ai_base_url_var.get().strip() or DEFAULT_AI_BASE_URL
        model = self.ai_model_var.get().strip() or DEFAULT_AI_MODEL
        recipient_name = self.name_var.get().strip() or self.contact_var.get().strip()
        tone = self.ai_tone_var.get().strip()
        extra_goal = self.ai_goal_text.get("1.0", "end").strip()
        goal = extra_goal or (
            "Doc ngu canh doan chat va viet cau tra loi phu hop cho tin nhan moi nhat. "
            "Neu co dong 'Them:' thi uu tien tra loi dong 'Them:' moi nhat, khong tra loi dong 'Me:'. "
            "Khong duoc noi la chua thay tin nhan moi. Tra loi ngan gon, tu nhien, khong hoi don dap, khong gay ap luc."
        )
        previous_context = self.auto_last_context.strip()
        previous_signature = _auto_context_signature(previous_context)
        previous_latest_incoming = _latest_incoming_line(previous_signature)
        previous_sent_text = self.auto_last_sent_text.strip()
        previous_replied_incoming = self.auto_last_replied_incoming.strip()
        auto_send_demo = self.auto_send_demo_var.get()

        def task():
            try:
                self.thread_log("Auto: dang doc chat...")
                context = self.session.read_chat_context(target).strip()
                if not context:
                    self.events.put(("auto_skip", "Auto: chua thay tin moi."))
                    return
                current_signature = _auto_context_signature(context)
                if not current_signature:
                    self.events.put(("auto_context_seen", context))
                    self.events.put(("auto_skip", "Auto: chi thay trang thai Messenger, chua thay noi dung tin moi."))
                    return
                current_latest_incoming = _latest_incoming_line(current_signature)
                if not current_latest_incoming:
                    self.events.put(("auto_context_seen", context))
                    self.events.put(("auto_skip", "Auto: chua thay tin moi tu doi phuong."))
                    return
                if not previous_latest_incoming:
                    self.events.put(("auto_context_seen", context))
                    self.events.put(("auto_skip", "Auto: da ghi nho ngu canh hien tai, dang cho tin moi."))
                    return
                if current_latest_incoming == previous_latest_incoming:
                    self.events.put(("auto_context_seen", context))
                    self.events.put(("auto_skip", "Auto: chua thay tin moi."))
                    return
                last_line = current_latest_incoming
                if previous_sent_text and _same_message_text(last_line, previous_sent_text):
                    self.events.put(("auto_context_seen", context))
                    self.events.put(("auto_skip", "Auto: tin cuoi la tin tool vua gui, dang cho doi phuong tra loi."))
                    return
                if previous_replied_incoming and current_latest_incoming == previous_replied_incoming:
                    self.events.put(("auto_context_seen", context))
                    self.events.put(("auto_skip", "Auto: tin moi nay da duoc tra loi roi, dang cho tin ke tiep."))
                    return
                self.events.put(("chat_context", context))
                reply_context = (
                    f"Tin moi nhat cua doi phuong:\n{_strip_chat_speaker(last_line)}\n\n"
                    f"Ngu canh chat dang thay:\n{context}"
                )
                draft = generate_ai_draft_clean(
                    api_key=api_key,
                    model=model,
                    recipient_name=recipient_name,
                    tone=tone,
                    goal=goal,
                    context=reply_context,
                    base_url=base_url,
                )
                if auto_send_demo:
                    self.session.send_message(target, draft, self.clear_var.get())
                    self.auto_sent_count += 1
                    self.events.put(("auto_sent", draft))
                else:
                    self.session.fill_message(target, draft, self.clear_var.get())
                    self.auto_sent_count += 1
                    self.events.put(("auto_filled", draft))
                self.events.put(("auto_replied_incoming", current_latest_incoming))
                self.events.put(("auto_context_seen", context))
                self.events.put(("ai_draft", draft))
            except Exception as exc:
                self.events.put(("auto_error", f"Auto loi: {exc}. Auto van dang bat, se thu lai sau."))

        status = "Demo auto: dang doc va gui..." if auto_send_demo else "Auto: dang doc va dien ban nhap..."
        self._run_background_task(task, status)

    def draft_with_ai(self):
        api_key = self.ai_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = self.ai_base_url_var.get().strip() or DEFAULT_AI_BASE_URL
        model = self.ai_model_var.get().strip() or DEFAULT_AI_MODEL
        recipient_name = self.name_var.get().strip() or self.contact_var.get().strip()
        tone = self.ai_tone_var.get().strip()
        context = self.ai_context_text.get("1.0", "end").strip()
        goal = self.ai_goal_text.get("1.0", "end").strip()

        def task():
            self.thread_log("AI dang soan ban nhap...")
            draft = generate_ai_draft_clean(
                api_key=api_key,
                model=model,
                recipient_name=recipient_name,
                tone=tone,
                goal=goal,
                context=context,
                base_url=base_url,
            )
            self.events.put(("ai_draft", draft))

        self._run_task(task)

    def close_browser(self):
        self._run_task(self.session.stop)

    def _require_target(self) -> str | None:
        target = self.target_var.get().strip()
        try:
            normalize_target(target)
        except ValueError as exc:
            messagebox.showwarning("Thieu nguoi nhan", str(exc))
            return None
        return target

    def _require_message(self) -> str | None:
        message = self.message_text.get("1.0", "end").strip()
        if not message:
            messagebox.showwarning("Thieu tin nhan", "Nhap noi dung tin nhan truoc da.")
            return None
        return message

    def _run_task(self, task):
        if self.busy:
            messagebox.showinfo("Dang chay", "Doi thao tac hien tai xong mot chut nha.")
            return
        self._run_background_task(task, "Dang xu ly...")

    def _run_background_task(self, task, status_message: str):
        if self.busy:
            return False
        self.busy = True
        self._set_status(status_message, busy=True)
        self.log(status_message)
        self.tasks.put(task)
        return True

    def _task_worker(self):
        while True:
            task = self.tasks.get()
            if task is None:
                self.tasks.task_done()
                break
            try:
                task()
            except Exception as exc:
                self.thread_log(f"Loi: {exc}")
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("done", ""))
                self.tasks.task_done()

    def thread_log(self, message: str):
        self.events.put(("log", message))

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_status(self, message: str, busy: bool = False, error: bool = False):
        self.status_var.set(message)
        if error:
            self.status_label.configure(bg="#fee2e2", fg=self.RED)
        elif busy:
            self.status_label.configure(bg="#fff4cc", fg="#7a4d00")
        else:
            self.status_label.configure(bg="#e8f2ff", fg=self.BLUE_DARK)

    def _drain_events(self):
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "log":
                    self.log(message)
                elif kind == "error":
                    if self.auto_draft_enabled:
                        self.log(f"Auto loi: {message}. Auto van dang bat, se thu lai sau.")
                        self._set_status("Auto dang bat, se thu lai", busy=True)
                    else:
                        self._set_status("Co loi", error=True)
                        messagebox.showerror("Co loi", message)
                elif kind == "ai_draft":
                    self.message_text.delete("1.0", "end")
                    self.message_text.insert("1.0", message)
                    self.log("AI da soan ban nhap vao o tin nhan.")
                    self._show_page("compose")
                elif kind == "chat_context":
                    self.ai_context_text.delete("1.0", "end")
                    self.ai_context_text.insert("1.0", message)
                    if self.auto_draft_enabled:
                        self.auto_last_context = message.strip()
                    self.log("Da dua ngu canh chat vao tab AI.")
                elif kind == "auto_context_seen":
                    self.auto_last_context = message.strip()
                elif kind == "auto_replied_incoming":
                    self.auto_last_replied_incoming = message.strip()
                elif kind == "auto_skip":
                    self.log(message)
                elif kind == "auto_error":
                    self.log(message)
                elif kind == "auto_sent":
                    self.auto_last_sent_text = message.strip()
                    self.log(f"Demo auto da gui {self.auto_sent_count} tin tu luc bat auto.")
                elif kind == "auto_filled":
                    self.log(f"Auto da tao {self.auto_sent_count} tin tu luc bat auto.")
                elif kind == "done":
                    self.busy = False
                    if self.auto_draft_enabled:
                        if self.auto_send_demo_var.get():
                            self._set_status("Demo auto gui dang bat", busy=True)
                        else:
                            self._set_status("Auto dien nhap dang bat", busy=True)
                        self._schedule_auto_draft_tick()
                    else:
                        self._set_status("Ready")
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _on_close(self):
        if self.closing:
            return
        self.closing = True
        self.auto_draft_enabled = False
        if self.auto_after_id is not None:
            try:
                self.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        self._set_status("Dang dong...", busy=True)
        self.log("Dang dong Edge va thoat tool...")
        self.tasks.put(self.session.stop)
        self.tasks.put(None)
        self.after(150, self._finish_close)

    def _finish_close(self):
        if self.worker_thread.is_alive():
            self.after(150, self._finish_close)
            return
        self.destroy()


if __name__ == "__main__":
    app = ModernMessengerToolApp()
    app.mainloop()
