# -*- coding: utf-8 -*-
"""
Công cụ làm trắc nghiệm trên màn hình với Google Gemini (Gộp toàn bộ vào 1 file duy nhất).
Chỉ cần chạy: py chay_tool.py
- F8: Chụp vùng câu hỏi đã khoanh và gửi Gemini giải (hỗ trợ cả 1 câu hoặc nhiều câu trong vùng quét).
- F9: Ẩn / hiện ô đáp án.
- Chuột phải vào ô chữ: Mở menu khoanh vùng, cài đặt API Key / Model / Tài liệu.
"""
import base64
from collections import deque
import ctypes
from ctypes import wintypes
import io
import json
import os
from pathlib import Path
import queue
import shutil
import ssl
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import tkinter.font as tkfont
import urllib.error
import urllib.request

from PIL import Image, ImageGrab

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

# ==============================================================================
# CẤU HÌNH & HẰNG SỐ
# ==============================================================================
TRANSPARENT = "#A4EDEB"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
WORK_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = WORK_DIR / "gemini_config.json"
LEGACY_REGION_FILE = WORK_DIR / "vung_theo_doi.json"

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
]
MAX_DOCUMENT_CHARS = 80000
SESSION_MODE = None

PROMPT = """
Trả lời câu hỏi bằng tiếng Việt, cực ngắn.
Đọc kỹ TOÀN BỘ ảnh hoặc văn bản từ trên xuống dưới và giải TẤT CẢ các câu hỏi xuất hiện trong đó:
- QUY TẮC GHI SỐ THỨ TỰ CÂU (BẮT BUỘC):
  + Tìm số thứ tự câu hỏi ở ô trắng bên ngoài khung đề (ví dụ ô "Câu hỏi 64" -> số thứ tự là 64; ưu tiên số ở ô trắng bên ngoài hơn số "Question XX" nằm bên trong nội dung câu hỏi). Nếu không có ô trắng bên ngoài thì lấy số câu trên đề.
  + Luôn ghi CHỈ CON SỐ đó ở đầu câu trả lời, KHÔNG ghi chữ "Câu", "Câu hỏi" hay "Question" (ví dụ: 64: A hoặc 64: A, C).
  + Với câu ghép thẻ / nhiều dòng: ghi con số ở dòng đầu tiên (ví dụ:
    64:
    System test -> Product functionality
    Driver test -> Software/hardware peripheral interface).
- QUY TẮC TRẢ LỜI TRẮC NGHIỆM:
  + Nếu các lựa chọn CÓ sẵn nhãn A, B, C, D (hoặc 1, 2, 3, 4): chỉ xuất nhãn đáp án đúng (ví dụ: 64: A hoặc 64: A, C).
  + Nếu các lựa chọn KHÔNG có nhãn (chỉ có nút tròn, ô vuông, gạch đầu dòng hoặc các dòng lựa chọn trơn — áp dụng cho cả câu chọn 1 đáp án lẫn câu chọn nhiều đáp án): tự đánh nhãn chữ cái A, B, C, D... theo thứ tự từ trên xuống dưới tương ứng với từng lựa chọn, rồi CHỈ trả lời bằng chữ cái vừa đánh đó (ví dụ: đáp án đúng ở dòng thứ 2 -> ghi 12: B; chọn nhiều đáp án ở dòng 1 và 3 -> ghi 12: A, C). Không dùng 1, 2, 3, 4 và không chép lại nội dung đáp án.
- Nếu có NHIỀU câu hỏi trong cùng vùng ảnh: giải ĐẦY ĐỦ từng câu theo thứ tự từ trên xuống dưới, mỗi câu 1 dòng với số thứ tự câu ở đầu:
  12: B
  13: C
  14: A, C
- QUAN TRỌNG: Nếu ở mép trên hoặc mép dưới của ảnh có câu bị cắt khuất không đủ chữ/lựa chọn, hãy BỎ QUA câu bị cắt đó và VẪN TRẢ LỜI BÌNH THƯỜNG tất cả các câu hỏi trọn vẹn còn lại trong ảnh. Tuyệt đối không trả về 'Thiếu dữ kiện' cho cả bức ảnh chỉ vì 1 câu ở rìa bị cắt.
- Ghép thẻ: mỗi dòng Thẻ -> Từ khóa tương ứng.
- Câu hỏi điền từ / trả lời ngắn: chỉ ghi kết quả ngắn nhất.
- Giữ nguyên ngôn ngữ gốc của đáp án trên đề (không dịch đáp án tiếng Anh sang tiếng Việt).
- Không giải thích, không ghi nguồn, không mở đầu, không dùng Markdown.
- Ưu tiên tài liệu đính kèm của người dùng nếu có.
"""

# ==============================================================================
# WIN32 API (PHÍM TẮT F8/F9 & DPI MÀN HÌNH)
# ==============================================================================
if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.RegisterHotKey.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
else:
    user32 = None
    kernel32 = None


def enable_dpi_awareness():
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass


def _hidden_startupinfo():
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        return si
    return None


# ==============================================================================
# QUẢN LÝ CẤU HÌNH & TÀI LIỆU
# ==============================================================================
def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(config):
    try:
        CONFIG_FILE.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_saved_region():
    config = load_config()
    region = config.get("region")
    if not region and LEGACY_REGION_FILE.exists():
        try:
            region = json.loads(LEGACY_REGION_FILE.read_text(encoding="utf-8")).get("region")
        except Exception:
            region = None
    if (
        isinstance(region, list)
        and len(region) == 4
        and all(type(n) is int for n in region)
        and region[2] > region[0]
        and region[3] > region[1]
    ):
        return tuple(region)
    return None


def save_region(region):
    config = load_config()
    config["region"] = list(region)
    save_config(config)


def read_documents(paths):
    sections = []
    total = 0

    for raw_path in paths:
        path = Path(raw_path)
        if path.stat().st_size > 15 * 1024 * 1024:
            raise ValueError(f"{path.name}: vượt giới hạn 15 MB.")

        suffix = path.suffix.lower()
        parts = []

        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError(f"{path.name}: PDF có mật khẩu.")
            for page_number, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or "").strip()
                if text:
                    parts.append(f"[Trang {page_number}]\n{text}")

        elif suffix == ".docx":
            from docx import Document
            doc = Document(str(path))
            parts.extend(p.text for p in doc.paragraphs if p.text.strip())
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text for c in row.cells))

        elif suffix in (".txt", ".md"):
            parts.append(path.read_text(encoding="utf-8-sig"))

        else:
            raise ValueError(f"Chưa hỗ trợ định dạng {suffix}.")

        text = "\n".join(parts).strip()
        if not text:
            raise ValueError(
                f"{path.name}: không đọc được chữ. Nếu là file scan, hãy OCR trước."
            )

        section = f"\n--- TÀI LIỆU: {path.name} ---\n{text}\n"
        total += len(section)
        if total > MAX_DOCUMENT_CHARS:
            raise ValueError("Tổng tài liệu vượt 80.000 ký tự.")
        sections.append(section)

    return "\n".join(sections)


# ==============================================================================
# KẾT NỐI GEMINI API & ANTIGRAVITY CLI
# ==============================================================================
def agy_path():
    for name in ("agy.exe", "agy.cmd", "agy"):
        found = shutil.which(name)
        if found:
            return found

    candidates = []
    local_app = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")

    if local_app:
        base = Path(local_app)
        candidates += [
            base / "agy/bin/agy.exe",
            base / "Antigravity/agy.exe",
            base / "Antigravity/bin/agy.exe",
            base / "Programs/Antigravity/bin/agy.exe",
            base / "Programs/Antigravity/agy.exe",
            base / "Google/Antigravity/bin/agy.exe",
            base / "Microsoft/WindowsApps/agy.exe",
        ]
    if user_profile:
        home = Path(user_profile)
        candidates += [
            home / ".local/bin/agy.exe",
            home / ".antigravity/bin/agy.exe",
            home / ".gemini/bin/agy.exe",
        ]

    candidates = [p for p in candidates if p.is_file()]
    if candidates:
        return str(max(candidates, key=lambda p: p.stat().st_mtime))
    return None


def _configure_agy_permissions():
    try:
        settings_path = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        else:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}

        perms = data.setdefault("permissions", {})
        allow_list = perms.setdefault("allow", [])
        ask_list = perms.setdefault("ask", [])

        changed = False
        for rule in ("read_file(*)", "write_file(*)", "command(*)"):
            if rule not in allow_list:
                allow_list.append(rule)
                changed = True
            if rule in ask_list:
                ask_list.remove(rule)
                changed = True

        if changed:
            settings_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception:
        pass


def has_saved_api_key():
    if os.getenv("GEMINI_API_KEY", "").strip():
        return True
    return bool(load_config().get("api_key", "").strip())


def get_mode():
    global SESSION_MODE
    if SESSION_MODE in ("api", "agy"):
        return SESSION_MODE
    if has_saved_api_key():
        SESSION_MODE = "api"
        return "api"
    if agy_path():
        SESSION_MODE = "agy"
        return "agy"
    SESSION_MODE = "api"
    return "api"


def toggle_mode(parent=None):
    global SESSION_MODE
    config = load_config()
    current = get_mode()
    if current == "api":
        if not agy_path():
            messagebox.showwarning(
                "Chưa tìm thấy Antigravity CLI (agy)",
                "Không tìm thấy tệp lệnh 'agy.exe' trên máy.\n"
                "Hãy dùng chế độ Gemini API Key hoặc cài đặt Antigravity CLI.",
                parent=parent,
            )
            return current
        SESSION_MODE = "agy"
        config["mode"] = "agy"
        save_config(config)
        messagebox.showinfo("Đã chuyển chế độ", "Đã chuyển sang: Antigravity CLI (agy).", parent=parent)
        return "agy"
    else:
        SESSION_MODE = "api"
        config["mode"] = "api"
        save_config(config)
        messagebox.showinfo("Đã chuyển chế độ", "Đã chuyển sang: Gemini API Key trực tiếp.", parent=parent)
        return "api"


def get_gemini_api_key(parent=None):
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    file_key = load_config().get("api_key", "").strip()
    if file_key:
        return file_key
    return prompt_gemini_api_key(parent)


def prompt_gemini_api_key(parent=None):
    global SESSION_MODE
    config = load_config()
    current_key = config.get("api_key", "")
    key = simpledialog.askstring(
        "Cài đặt Gemini API Key",
        "Nhập Google Gemini API Key của bạn:\n(Lấy miễn phí tại: https://aistudio.google.com/)",
        initialvalue=current_key,
        parent=parent,
    )
    if key and key.strip():
        config["api_key"] = key.strip()
        config["mode"] = "api"
        SESSION_MODE = "api"
        save_config(config)
        return key.strip()
    if current_key:
        return current_key
    raise RuntimeError("Chưa có Gemini API Key. Hãy cấu hình để sử dụng.")


def prompt_gemini_model(parent=None):
    config = load_config()
    current_model = config.get("model", "").strip() or DEFAULT_MODEL
    model = simpledialog.askstring(
        "Đổi Model Gemini",
        "Nhập tên model ưu tiên (ví dụ: gemini-3.5-flash-lite hoặc gemini-3.8-flash):",
        initialvalue=current_model,
        parent=parent,
    )
    if model and model.strip():
        config["model"] = model.strip()
        save_config(config)
        return model.strip()
    return current_model


def get_gemini_model():
    model = load_config().get("model", "").strip() or DEFAULT_MODEL
    return DEFAULT_MODEL if model == "gemini-2.5-flash" else model


def prepare_image_part(picture):
    img = picture.convert("RGB")
    max_dim = 2200
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90, optimize=True)
    b64_img = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return {
        "inline_data": {
            "mime_type": "image/jpeg",
            "data": b64_img,
        }
    }


def _call_single_model(api_key, model, parts, timeout):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    gen_config = {
        "temperature": 0.1,
        "maxOutputTokens": 2048,
    }
    if any(tag in model for tag in ("gemini-3", "gemini-4")):
        gen_config["thinkingConfig"] = {"thinkingLevel": "LOW"}

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": gen_config,
    }
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_gemini(api_key, model, prompt_text, picture=None, timeout=45):
    parts = [{"text": prompt_text}]
    if picture is not None:
        parts.append(prepare_image_part(picture))

    candidate_models = [model] + [m for m in FALLBACK_MODELS if m != model]
    data = None
    last_error_msg = ""

    for current_model in candidate_models:
        try:
            data = _call_single_model(api_key, current_model, parts, timeout)
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body

            last_error_msg = f"Lỗi Gemini API ({e.code}): {err_msg}"
            if e.code in (401, 403) or (e.code == 400 and "api_key" in err_body.lower()):
                raise RuntimeError(last_error_msg)
            if e.code in (404, 429, 500, 502, 503, 504):
                time.sleep(0.15)
                continue
            raise RuntimeError(last_error_msg)
        except Exception as e:
            last_error_msg = f"Lỗi kết nối Gemini: {str(e)}"
            time.sleep(0.15)
            continue

    if data is None:
        raise RuntimeError(last_error_msg or "Không thể kết nối tới Gemini API.")

    candidates = data.get("candidates", [])
    if not candidates:
        block_reason = data.get("promptFeedback", {}).get("blockReason")
        if block_reason:
            raise RuntimeError(f"Bị chặn bởi bộ lọc nội dung ({block_reason}).")
        raise RuntimeError("Gemini không trả về kết quả.")

    candidate = candidates[0]
    resp_parts = candidate.get("content", {}).get("parts", [])
    answer = "".join(p.get("text", "") for p in resp_parts if not p.get("thought")).strip()
    if not answer:
        answer = "".join(p.get("text", "") for p in resp_parts).strip()
    if not answer:
        finish_reason = candidate.get("finishReason", "UNKNOWN")
        raise RuntimeError(f"Không có nội dung trả lời ({finish_reason}).")

    return answer


def query_agy_cli(prompt_text, picture=None, timeout=30, owner=None):
    executable = agy_path()
    if not executable:
        if has_saved_api_key():
            return query_gemini(get_gemini_api_key(), get_gemini_model(), prompt_text, picture=picture)
        raise RuntimeError("Không tìm thấy Antigravity CLI (agy). Hãy nhập Gemini API Key.")

    _configure_agy_permissions()
    img_file = WORK_DIR / f"question_{threading.get_ident()}.jpg"
    txt_file = WORK_DIR / f"question_{threading.get_ident()}.txt"

    try:
        if picture is not None:
            img = picture.convert("RGB")
            max_dim = 2200
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            img.save(img_file, format="JPEG", quality=90, optimize=True)
            abs_img = str(img_file.resolve())
            cli_prompt = (
                f"@{abs_img} "
                f"Read the image file at \"{abs_img}\" using view_file (do NOT run any terminal command). "
                "Giải tất cả các câu hỏi xuất hiện trong ảnh từ trên xuống dưới. "
                "Luôn lấy số thứ tự ở ô trắng bên ngoài đề (ví dụ ô Câu hỏi 64 -> ghi 64:) đặt trước đáp án, CHỈ ghi số, KHÔNG ghi chữ Câu hay Câu hỏi. "
                "Nếu lựa chọn không có nhãn (kể cả câu chọn 1 hay nhiều đáp án), tự đánh nhãn A, B, C, D... từ trên xuống và chỉ trả lời bằng chữ cái đó (ví dụ 12: B hoặc 12: A, C). "
                "Ví dụ: 64: A, 12: A, C, hoặc với ghép thẻ ghi 64: rồi xuống dòng từng cặp Thẻ -> Đáp án. "
                "Bỏ qua câu bị cắt dở ở mép ảnh. Không giải thích."
            )
        else:
            txt_file.write_text(prompt_text, encoding="utf-8")
            abs_txt = str(txt_file.resolve())
            cli_prompt = (
                f"@{abs_txt} "
                f"Read the file at \"{abs_txt}\" using view_file (do NOT run any terminal command) "
                "and answer all questions following the exact rules inside it."
            )

        args = [
            executable,
            "--add-dir",
            str(WORK_DIR),
            "--effort",
            "low",
            "--output-format",
            "json",
            "-p",
            cli_prompt,
        ]

        if owner is not None:
            with owner.lock:
                if owner.cancelled.is_set():
                    raise RuntimeError("Đã dừng.")
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(WORK_DIR),
                    startupinfo=_hidden_startupinfo(),
                    creationflags=CREATE_NO_WINDOW,
                )
                owner.proc = process
        else:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(WORK_DIR),
                startupinfo=_hidden_startupinfo(),
                creationflags=CREATE_NO_WINDOW,
            )

        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            if has_saved_api_key():
                return query_gemini(get_gemini_api_key(), get_gemini_model(), prompt_text, picture=picture)
            raise RuntimeError("Quá thời gian chờ Antigravity CLI.")
        finally:
            if owner is not None:
                with owner.lock:
                    owner.proc = None

        if owner is not None and owner.cancelled.is_set():
            raise RuntimeError("Đã dừng yêu cầu.")

        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    resp = (data.get("response") or "").strip()
                    if resp:
                        return resp
                    if has_saved_api_key():
                        return query_gemini(get_gemini_api_key(), get_gemini_model(), prompt_text, picture=picture)
                    if data.get("error"):
                        raise RuntimeError(str(data["error"]))
                except json.JSONDecodeError:
                    continue

        if has_saved_api_key():
            return query_gemini(get_gemini_api_key(), get_gemini_model(), prompt_text, picture=picture)

        raise RuntimeError("Chưa nhận được câu trả lời từ Antigravity CLI. Hãy dùng Gemini API Key.")
    finally:
        for temp_f in (img_file, txt_file):
            try:
                if temp_f.exists():
                    temp_f.unlink()
            except OSError:
                pass


# ==============================================================================
# CHỤP CHỮ BÔI ĐEN / CLIPBOARD
# ==============================================================================
def capture_now():
    if user32 is not None:
        release_deadline = time.monotonic() + 1.5
        while user32.GetAsyncKeyState(0x77) & 0x8000:
            if time.monotonic() >= release_deadline:
                raise RuntimeError("Hãy nhả F8 rồi thử lại.")
            time.sleep(0.01)

    try:
        picture = ImageGrab.grabclipboard()
        picture = picture.copy() if isinstance(picture, Image.Image) else None
    except OSError:
        picture = None

    if user32 is not None and keyboard is not None and pyperclip is not None:
        sequence = user32.GetClipboardSequenceNumber()
        keyboard.send("ctrl+c")
        deadline = time.monotonic() + 1.0

        while time.monotonic() < deadline:
            if user32.GetClipboardSequenceNumber() != sequence:
                try:
                    text = pyperclip.paste().strip()
                except Exception:
                    text = ""
                if text:
                    if len(text) > 20000:
                        raise RuntimeError("Câu hỏi vượt 20.000 ký tự.")
                    return text, None
            time.sleep(0.025)

    try:
        latest_picture = ImageGrab.grabclipboard()
        if isinstance(latest_picture, Image.Image):
            picture = latest_picture.copy()
    except OSError:
        pass

    if picture is not None:
        return (
            "Trả lời tất cả các câu hỏi trong vùng ảnh từ trên xuống dưới. Giữ nguyên ngôn ngữ đáp án.",
            picture,
        )

    raise RuntimeError("Hãy khoanh vùng câu hỏi, bôi đen chữ hoặc chụp ảnh trước khi bấm F8.")


# ==============================================================================
# GIAO DIỆN CHÍNH (OVERLAY + KHOANH VÙNG + HÀNG ĐỢI F8/F9)
# ==============================================================================
class QuizOverlayApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.pending = deque()
        self.batch_results = []
        self.batch_count = 0
        self.active_job = None
        self.busy = False
        self.closing = False
        self.documents = ""
        self.answer = ""
        self.display_text = ""
        self.last_result = ""
        self.proc = None
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.anchor = None
        self.offset = (0, 0)

        # Trạng thái khoanh vùng
        self.watch_enabled = False
        self.watch_region = load_saved_region()
        self.watch_latest = None
        self.watch_captured_at = None
        self.watch_selector = None
        self.watch_timer = None
        self.watch_menu_open = False

        # Phím tắt Windows
        self.hotkey_thread_id = None
        self.hotkey_stop = threading.Event()
        self.hotkey_ready = threading.Event()

        # Thiết lập cửa sổ trong suốt
        root.title("Trợ lý Gemini")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=TRANSPARENT)
        root.attributes("-transparentcolor", TRANSPARENT)

        self.body = tk.Frame(root, bg=TRANSPARENT)
        self.body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            self.body,
            bg=TRANSPARENT,
            highlightthickness=0,
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scroll = tk.Scrollbar(self.body, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.bind(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-int(e.delta / 120), "units"),
        )
        self.canvas.bind("<ButtonPress-1>", self.drag_start)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<Button-3>", lambda e: self.menu())

        self.font = tkfont.Font(family="Tahoma", size=8, weight="normal")
        root.protocol("WM_DELETE_WINDOW", self.close)
        if os.name == "nt":
            try:
                root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
                ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), wintypes.DWORD(0x00000011))
            except Exception:
                pass

        # Khởi động luồng lắng nghe F8 / F9
        self.listener = threading.Thread(target=self.listen_hotkeys, daemon=True)
        self.listener.start()

        self.show(
            "F8: tra vùng đã chọn"
            if self.watch_region
            else "Chuột phải → Khoanh vùng câu hỏi"
        )
        self.root.after(60, self.poll)

    # --------------------------------------------------------------------------
    # Phím tắt hệ thống F8 / F9
    # --------------------------------------------------------------------------
    def listen_hotkeys(self):
        if user32 is None or kernel32 is None:
            return
        registered = []
        try:
            self.hotkey_thread_id = kernel32.GetCurrentThreadId()
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)

            bindings = {
                1: (0x77, "auto", "F8"),
                2: (0x78, "toggle", "F9"),
            }

            for identifier, (key, action, label) in bindings.items():
                success = user32.RegisterHotKey(None, identifier, 0x4000, key)
                if not success:
                    raise RuntimeError(
                        f"{label} đang bị chiếm (lỗi {ctypes.get_last_error()}). Hãy đóng bản tool cũ."
                    )
                registered.append(identifier)

            self.hotkey_ready.set()

            while not self.hotkey_stop.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise RuntimeError("Lỗi nhận phím tắt Windows.")
                if message.message == 0x0312:
                    binding = bindings.get(int(message.wParam))
                    if binding:
                        self.events.put(("request", binding[1]))
        except Exception as error:
            self.events.put(("hotkey_error", str(error)))
        finally:
            for identifier in registered:
                user32.UnregisterHotKey(None, identifier)
            self.hotkey_ready.set()

    # --------------------------------------------------------------------------
    # Hiển thị & Kéo thả
    # --------------------------------------------------------------------------
    def _draw_overlay_text(self, text):
        self.answer = text
        self.canvas.delete("all")

        longest = max(
            (self.font.measure(line) for line in text.splitlines()),
            default=25,
        )
        width = max(38, min(350, longest + 16))

        self.canvas.create_text(
            8,
            6,
            text=text,
            anchor="nw",
            width=width - 16,
            font=self.font,
            fill="#A5EEEC",
        )

        bounds = self.canvas.bbox("all")
        content_height = (bounds[3] if bounds else 20) + 8
        height = min(content_height, 320)
        extra_width = 0

        if content_height > height:
            self.scroll.pack(side="right", fill="y")
            extra_width = self.scroll.winfo_reqwidth()
        else:
            self.scroll.pack_forget()

        self.canvas.configure(
            width=width,
            height=height,
            scrollregion=(0, 0, width, content_height),
        )
        self.canvas.yview_moveto(0)

        total_width = width + extra_width
        if self.anchor is None:
            x = self.root.winfo_screenwidth() - total_width - 25
            y = self.root.winfo_screenheight() - height - 80
        else:
            x, y = self.anchor

        self.root.geometry(f"{total_width}x{height}{int(x):+d}{int(y):+d}")

    def show(self, text):
        self.display_text = text
        self.render()

    def render(self):
        lines = []
        for number, answer in self.batch_results:
            first_line = answer.splitlines()[0].strip() if answer else ""
            has_qnum = bool(first_line and first_line.split(":", 1)[0].strip().isdigit())
            if self.batch_count > 1 and not has_qnum:
                if "\n" in answer:
                    lines.append(f"[{number}]\n{answer}")
                else:
                    lines.append(f"{number}: {answer}")
            else:
                lines.append(answer)
        if self.display_text:
            lines.append(self.display_text)
        text = "\n".join(lines)

        if self.pending:
            text += f"\n({len(self.pending)}) chờ"

        self._draw_overlay_text(text)
        try:
            self.canvas.yview_moveto(1.0)
        except Exception:
            pass

    def drag_start(self, event):
        self.offset = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def drag(self, event):
        x = event.x_root - self.offset[0]
        y = event.y_root - self.offset[1]
        self.anchor = (x, y)
        self.root.geometry(f"{x:+d}{y:+d}")

    def toggle(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
        else:
            self.root.withdraw()

    # --------------------------------------------------------------------------
    # Khoanh vùng câu hỏi trên màn hình
    # --------------------------------------------------------------------------
    def toggle_watch(self):
        if self.watch_enabled:
            self.watch_enabled = False
            self.show("Đã dừng đọc liên tục · F8 vẫn tra được")
        elif self.watch_region is None:
            self.select_region()
        else:
            self.watch_enabled = True
            self.show("Sẵn sàng · F8 để tra")

    def select_region(self):
        if self.watch_selector is not None:
            return
        was_enabled = self.watch_enabled
        self.watch_enabled = False
        window = tk.Toplevel(self.root)
        self.watch_selector = window
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", 0.3)

        if user32 is not None:
            left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
            width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        else:
            left, top = 0, 0
            width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()

        window.geometry(f"{width}x{height}{left:+d}{top:+d}")
        canvas = tk.Canvas(window, bg="black", cursor="crosshair", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            30,
            30,
            anchor="nw",
            fill="white",
            font=("Arial", 18),
            text="Kéo chuột khoanh câu hỏi và các lựa chọn. Esc: hủy.",
        )
        origin = []
        rectangle = [None]

        def finish(region=None):
            window.grab_release()
            window.destroy()
            self.watch_selector = None
            if region is None:
                self.watch_enabled = was_enabled
                return
            self.watch_region = region
            self.watch_latest = None
            self.watch_captured_at = None
            save_region(region)
            self.watch_enabled = True
            self.show("Sẵn sàng · F8 để tra")

        def press(event):
            origin[:] = [event.x, event.y]
            if rectangle[0] is not None:
                canvas.delete(rectangle[0])
            rectangle[0] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y, outline="#00ffff", width=3
            )

        def move(event):
            if origin:
                canvas.coords(rectangle[0], origin[0], origin[1], event.x, event.y)

        def release(event):
            if not origin:
                return
            x1, x2 = sorted((origin[0], max(0, min(width, event.x))))
            y1, y2 = sorted((origin[1], max(0, min(height, event.y))))
            if x2 - x1 >= 80 and y2 - y1 >= 40:
                finish((x1 + left, y1 + top, x2 + left, y2 + top))

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", release)
        window.bind("<Escape>", lambda e: finish())
        window.grab_set()
        window.focus_force()

    def capture_region(self):
        if self.watch_region is None:
            raise RuntimeError("Hãy khoanh vùng câu hỏi trước.")
        if self.watch_selector is not None:
            raise RuntimeError("Hãy khoanh xong vùng trước khi bấm F8.")
        picture = ImageGrab.grab(bbox=self.watch_region, all_screens=True)
        self.watch_latest = picture
        self.watch_captured_at = time.monotonic()
        return picture.copy()

    def watch_tick(self):
        if self.closing:
            return
        try:
            if (
                self.watch_enabled
                and self.watch_region
                and self.watch_selector is None
                and not self.watch_menu_open
            ):
                self.capture_region()
        except Exception as error:
            self.watch_enabled = False
            self.show("Đã tạm dừng đọc vùng: " + str(error))
        finally:
            pass
    # --------------------------------------------------------------------------
    # Xử lý câu hỏi & Hàng đợi
    # --------------------------------------------------------------------------
    def choose_documents(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(
            parent=self.root,
            filetypes=[("Tài liệu", "*.pdf *.docx *.txt *.md")],
        )
        if paths:
            self.busy = True
            self.show("Đang đọc tài liệu...")

            def load_docs():
                try:
                    self.events.put(("done", ("documents", read_documents(paths))))
                except Exception as error:
                    self.events.put(("error", str(error)))

            threading.Thread(target=load_docs, daemon=True).start()

    def clear_documents(self):
        if not self.busy:
            self.documents = ""
            self.show("Đã bỏ tài liệu.")

    def ask(self, mode="auto"):
        if self.closing:
            return
        try:
            if mode != "clipboard" and self.watch_selector is not None:
                return
            if mode != "clipboard" and self.watch_region is not None:
                picture = self.capture_region()
                question = (
                    "Trả lời tất cả các câu hỏi trong vùng ảnh từ trên xuống dưới. "
                    "Giữ nguyên ngôn ngữ đáp án."
                )
            else:
                question, picture = capture_now()
        except Exception as error:
            messagebox.showerror("Chưa nhận được câu hỏi", str(error), parent=self.root)
            return

        self.enqueue_capture(question, picture)

    def clear_history(self):
        self.batch_results.clear()
        self.batch_count = 0
        self.show("Đã xóa danh sách đáp án.")

    def enqueue_capture(self, question, picture):
        if self.closing:
            return
        if not self.busy and not self.pending:
            self.batch_results.clear()
            self.batch_count = 0
        self.batch_count += 1
        self.pending.append((question, picture, self.documents, self.batch_count))
        self.start_next()
        self.render()

    def start_next(self):
        if self.closing or self.busy or not self.pending:
            return

        mode = get_mode()
        api_key = None
        model = None
        if mode != "agy":
            try:
                api_key = get_gemini_api_key(self.root)
                model = get_gemini_model()
            except Exception as error:
                self.pending.popleft()
                self.show("Lỗi: " + str(error))
                return

        self.active_job = self.pending.popleft()
        question, picture, docs, _ = self.active_job
        self.busy = True
        self.cancelled.clear()
        self.show("Đang tra")

        def work():
            try:
                prompt = PROMPT + "\n" + json.dumps(
                    {"question": question, "documents": docs},
                    ensure_ascii=False,
                )
                if self.cancelled.is_set():
                    raise RuntimeError("Đã dừng.")

                if mode == "agy":
                    answer = query_agy_cli(
                        prompt_text=prompt,
                        picture=picture,
                        timeout=30,
                        owner=self,
                    )
                else:
                    answer = query_gemini(
                        api_key=api_key,
                        model=model,
                        prompt_text=prompt,
                        picture=picture,
                        timeout=45,
                    )

                if self.cancelled.is_set():
                    raise RuntimeError("Đã dừng yêu cầu.")

                self.events.put(("done", ("answer", answer.replace("**", "").strip())))
            except Exception as error:
                self.events.put(("error", str(error)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closing:
            return
        try:
            for _ in range(30):
                kind, data = self.events.get_nowait()

                if kind == "request":
                    if data == "toggle":
                        self.toggle()
                    else:
                        self.ask()

                elif kind == "hotkey_error":
                    messagebox.showerror("Phím tắt", data, parent=self.root)

                elif kind == "done":
                    self.busy = False
                    finished_job = self.active_job
                    self.active_job = None
                    result_type, value = data

                    if result_type == "documents":
                        self.documents = value
                        self.show("Đã nạp tài liệu.")
                    else:
                        self.last_result = value
                        if finished_job is not None:
                            self.batch_results.append((finished_job[3], value))
                            self.show("")
                        else:
                            self.show(value)

                    self.start_next()

                elif kind == "error":
                    self.busy = False
                    finished_job = self.active_job
                    self.active_job = None
                    self.last_result = "Lỗi: " + data
                    if finished_job is not None:
                        self.batch_results.append((finished_job[3], self.last_result))
                        self.show("")
                    else:
                        self.show(self.last_result)
                    self.start_next()

        except queue.Empty:
            pass

        self.root.after(60, self.poll)

    # --------------------------------------------------------------------------
    # Menu chuột phải & Đóng ứng dụng
    # --------------------------------------------------------------------------
    def menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Khoanh / chọn lại vùng câu hỏi", command=self.select_region)
        menu.add_separator()
        menu.add_command(label="Tra vùng đang chọn (F8)", command=lambda: self.ask("auto"))
        menu.add_command(
            label="Tra chữ bôi đen / ảnh clipboard",
            command=lambda: self.ask("clipboard"),
        )
        menu.add_command(label="Chọn tài liệu", command=self.choose_documents)
        menu.add_command(label="Bỏ tài liệu", command=self.clear_documents)
        menu.add_separator()
        mode_label = (
            "Chuyển sang Gemini API Key (Đang dùng: agy CLI)"
            if get_mode() == "agy"
            else "Chuyển sang Antigravity CLI (Đang dùng: API Key)"
        )
        menu.add_command(label=mode_label, command=lambda: toggle_mode(self.root))
        menu.add_command(
            label="Cài đặt Gemini API Key",
            command=lambda: prompt_gemini_api_key(self.root),
        )
        menu.add_command(
            label="Đổi Model Gemini",
            command=lambda: prompt_gemini_model(self.root),
        )
        menu.add_separator()
        menu.add_command(
            label="Sao chép đáp án",
            command=lambda: self.root.clipboard_clear() or self.root.clipboard_append(self.answer),
        )
        menu.add_command(label="Xóa danh sách đáp án", command=self.clear_history)
        menu.add_command(label="Dừng tất cả", command=self.stop)
        menu.add_command(label="Ẩn / hiện (F9)", command=self.toggle)
        menu.add_command(label="Thoát", command=self.close)

        self.watch_menu_open = True
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()
            self.watch_menu_open = False

    def stop(self):
        self.watch_enabled = False
        self.pending.clear()
        self.cancelled.set()
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()
        self.render()

    def close(self):
        self.watch_enabled = False
        if self.watch_timer is not None:
            try:
                self.root.after_cancel(self.watch_timer)
            except Exception:
                pass
        if self.watch_selector is not None:
            self.watch_selector.destroy()
            self.watch_selector = None

        self.closing = True
        self.hotkey_stop.set()
        if user32 is not None and self.hotkey_thread_id:
            user32.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)
        self.stop()
        self.root.destroy()


if __name__ == "__main__":
    enable_dpi_awareness()
    root = tk.Tk()
    try:
        app = QuizOverlayApp(root)
        root.mainloop()
    except Exception as error:
        messagebox.showerror("Lỗi công cụ", str(error))
        root.destroy()
