"""Try a local open model on a Persian summarising task (experiment)."""
import json, os, sys, time, urllib.request

MODEL = os.environ["AI_MODEL"]
BASE = "http://127.0.0.1:11434"

TEXT = """[صفحه 7]
3- حشو و انواع آن
حشو یعنی آوردن واژه یا عبارتی که معنای آن پیش از این در جمله آمده است و حذف آن به معنای جمله آسیبی نمی زند. نویسنده باید بداند که هر حشوی نادرست نیست.
3 -1 - حشو ملیح
حشوی است که به زیبایی سخن می افزاید و معمولاً دعا یا توضیحی کوتاه است. مثال: «استاد، که عمرش دراز باد، امروز به کلاس آمد.» این نوع حشو پذیرفته است.
3 -2- حشو متوسط
حشوی است که نه به زیبایی جمله کمک می کند و نه آن را زشت می سازد. مثال: «او با چشم خود دید.» بهتر است در نوشته رسمی حذف شود.
[صفحه 8]
3 -3- حشو قبیح
حشوی است که تکرار بی فایده است و نوشته را سست می کند. باید همیشه حذف شود. نمونه ها: «سوال پرسیدن» به جای «پرسیدن»، «فریضه واجب» به جای «فریضه»، «سال عام الفیل» به جای «عام الفیل»، «شب لیله القدر» به جای «لیله القدر». توجه: در آزمون ها بیشترین پرسش از همین نوع می آید."""

SYSTEM = (
    "تو دستیار خلاصه نویسی برای دانشجو هستی. فقط از متن داده شده استفاده کن و چیزی از خودت اضافه نکن. "
    "پاسخ را فقط به شکل JSON معتبر بده، بدون هیچ توضیح دیگر. ساختار: "
    '{"key_points":[{"text":"...","page":7}],'
    '"tables":[{"title":"...","columns":["..."],"rows":[["..."]],"page":7}],'
    '"warnings":[{"text":"...","page":8}]}. '
    "اگر متن چند چیز را با هم مقایسه می کند، آن را در tables بیاور. شماره صفحه را از نشانه [صفحه N] بردار."
)
USER = "متن این بخش:\n\n" + TEXT

def notice(title, message):
    print(f"::notice title={title}::{str(message).replace(chr(10), ' ⏎ ')[:3500]}", flush=True)

def post(path, body, timeout=1200):
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=timeout))

def try_call(name, path, body, pick):
    started = time.time()
    try:
        raw = post(path, body)
        text = pick(raw)
        took = time.time() - started
        try:
            data = json.loads(text)
            shape = {k: len(v) for k, v in data.items() if isinstance(v, list)}
            notice(f"{MODEL} {name}", f"OK {took:.0f}s valid_json shape={shape} usage={raw.get('usage') or {k: raw.get(k) for k in ('prompt_eval_count','eval_count')}} :: {text}")
        except Exception as error:
            notice(f"{MODEL} {name}", f"INVALID JSON {took:.0f}s ({error}) :: {text}")
    except Exception as error:
        detail = getattr(error, "read", lambda: b"")()
        notice(f"{MODEL} {name}", f"CALL FAILED {time.time() - started:.0f}s {error} {detail[:300]}")

messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
try_call("v1 json_object", "/v1/chat/completions",
         {"model": MODEL, "messages": messages, "temperature": 0, "response_format": {"type": "json_object"}},
         lambda r: r["choices"][0]["message"]["content"])
try_call("v1 plain", "/v1/chat/completions",
         {"model": MODEL, "messages": messages, "temperature": 0},
         lambda r: r["choices"][0]["message"]["content"])
try_call("native json num_ctx 8192", "/api/chat",
         {"model": MODEL, "messages": messages, "stream": False, "format": "json", "options": {"temperature": 0, "num_ctx": 8192}},
         lambda r: r["message"]["content"])
try:
    notice(f"{MODEL} show", json.dumps({k: v for k, v in post("/api/show", {"model": MODEL}).get("model_info", {}).items() if "context" in k or "parameter_count" in k}))
except Exception as error:
    notice(f"{MODEL} show", f"failed {error}")
