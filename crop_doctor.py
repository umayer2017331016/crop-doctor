"""
Crop Doctor (ফসল ডাক্তার) — বাংলা কৃষি পরামর্শ
================================================
একটা পাতার/ফসলের ছবি দিলে রোগ শনাক্ত করে বাংলায় পরামর্শ দেয়।

ব্যবহার:
    python crop_doctor.py path/to/leaf.jpg
    python crop_doctor.py path/to/leaf.jpg --crop ধান

ফ্রি Gemini API key লাগবে: https://aistudio.google.com/apikey
তারপর key টা এনভায়রনমেন্টে দিন:
    Windows (PowerShell):  $env:GEMINI_API_KEY = "আপনার-key"
    Linux/Mac/Colab:       export GEMINI_API_KEY="আপনার-key"
"""

import os
import sys
import json
import time
import argparse
import mimetypes

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("দরকারি লাইব্রেরি নেই। চালান:  pip install google-genai")
    sys.exit(1)


# কম-ব্যস্ত মডেল আগে (দ্রুত উত্তরের জন্য), নতুন/ব্যস্তগুলো পরে
MODELS = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]
MAX_RETRY = 3  # সব মডেল ব্যস্ত হলে, শেষ মডেলে কতবার অপেক্ষা করে চেষ্টা করবে

# মডেল যে কাঠামোয় উত্তর দেবে (এতে উত্তর সবসময় একই ফরম্যাটে আসে)
RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=[
        "is_plant", "fosol", "rog_naam", "confidence",
        "lokkhon", "karon", "protikar", "sar_osudh",
        "sotorkota", "officer_dekhano_uchit",
    ],
    properties={
        "is_plant": types.Schema(
            type=types.Type.BOOLEAN,
            description="ছবিতে গাছ/পাতা/ফসল আছে কিনা",
        ),
        "fosol": types.Schema(type=types.Type.STRING, description="ফসলের নাম (বাংলায়)"),
        "rog_naam": types.Schema(type=types.Type.STRING, description="রোগ/সমস্যার নাম (বাংলায়)"),
        "confidence": types.Schema(
            type=types.Type.STRING,
            enum=["high", "medium", "low"],
            description="মডেল কতটা নিশ্চিত",
        ),
        "lokkhon": types.Schema(type=types.Type.STRING, description="লক্ষণ (বাংলায়)"),
        "karon": types.Schema(type=types.Type.STRING, description="কারণ (বাংলায়)"),
        "protikar": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
            description="করণীয় ধাপ (জৈব + রাসায়নিক), বাংলায়",
        ),
        "sar_osudh": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
            description="সার/বালাইনাশকের নাম ও সাধারণ মাত্রা, বাংলায়",
        ),
        "sotorkota": types.Schema(type=types.Type.STRING, description="নিরাপত্তা সতর্কতা (বাংলায়)"),
        "officer_dekhano_uchit": types.Schema(
            type=types.Type.BOOLEAN,
            description="নিশ্চিত না হলে স্থানীয় কৃষি অফিসারকে দেখানো উচিত কিনা",
        ),
    },
)

PROMPT = """তুমি বাংলাদেশের একজন অভিজ্ঞ কৃষি বিশেষজ্ঞ।
ছবিটি ভালোভাবে দেখে ফসলের রোগ/পোকা/পুষ্টির ঘাটতি শনাক্ত করো।

নিয়ম:
- সব উত্তর সহজ বাংলায় দাও, যেন একজন সাধারণ কৃষক বোঝে।
- ছবিতে গাছ/পাতা না থাকলে is_plant = false দাও এবং বাকি ঘরে "ছবিতে ফসল পাওয়া যায়নি" লেখো।
- নিশ্চিত না হলে confidence = "low" এবং officer_dekhano_uchit = true দাও। আন্দাজে ভুল পরামর্শ দিও না।
- খুব গুরুত্বপূর্ণ: একই রোগের জন্য সবসময় একই রকম, মানসম্মত (বাংলাদেশ কৃষি সম্প্রসারণ অধিদপ্তরের অনুমোদিত) পরামর্শ দাও — প্রতিবার ভিন্ন ওষুধ নয়।
- ওষুধের ক্ষেত্রে আগে সক্রিয় উপাদানের নাম (যেমন: ম্যানকোজেব) বলো, তারপর বন্ধনীতে ১-২টি সাধারণ ব্র্যান্ড উদাহরণ দাও। এতে ব্র্যান্ড বদলালেও কৃষক সঠিক ওষুধ কিনতে পারবে।
- বালাইনাশকের মাত্রা দিলে সাধারণ/আনুমানিক মাত্রা দাও এবং লেবেল দেখে ব্যবহারের কথা বলো।
- সবসময় একটি নিরাপদ জৈব/সাংস্কৃতিক প্রতিকারও দাও (শুধু রাসায়নিক নয়)।
- sotorkota ঘরে বালাইনাশক ব্যবহারে হাত-মুখ ঢাকা, শিশু/পশু দূরে রাখার কথা মনে করিয়ে দাও।
"""

DISCLAIMER = (
    "⚠️  এটি একটি AI পরামর্শ, চূড়ান্ত সিদ্ধান্ত নয়। "
    "ওষুধ ব্যবহারের আগে স্থানীয় কৃষি অফিসার বা ডিলারের সাথে যাচাই করুন।"
)


def _client():
    """Gemini ক্লায়েন্ট তৈরি করে (key যাচাই সহ)।"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY পাওয়া যায়নি।\n"
            "ফ্রি key নিন: https://aistudio.google.com/apikey\n"
            'তারপর:  $env:GEMINI_API_KEY = "আপনার-key"   (PowerShell)'
        )
    return genai.Client(api_key=api_key)


def _generate(client, contents, config):
    """কৌশল: ব্যস্ত পেলে অপেক্ষা না করে সাথে সাথে পরের মডেলে যায় (দ্রুত ফ্রি মডেল খোঁজে)।
    সব মডেল ব্যস্ত হলে তবেই শেষ মডেলে একটু অপেক্ষা করে আবার চেষ্টা করে।"""
    last_error = None
    # ধাপ ১: দ্রুত সব মডেল একবার করে চেষ্টা — যেটা ফ্রি পাবে, সেটাই
    for model in MODELS:
        try:
            resp = client.models.generate_content(
                model=model, contents=contents, config=config,
            )
            return resp.text
        except Exception as e:
            last_error = e
            msg = str(e)
            if any(x in msg for x in ("503", "429", "UNAVAILABLE", "404", "NOT_FOUND")):
                print(f"↪️  {model} এখন ব্যস্ত/নেই, পরেরটায় যাচ্ছি...")
                continue
            raise  # অন্য কোনো সমস্যা (key ভুল ইত্যাদি) হলে থামো

    # ধাপ ২: সব ব্যস্ত ছিল — শেষ মডেলে একটু অপেক্ষা করে আবার চেষ্টা
    model = MODELS[-1]
    for attempt in range(1, MAX_RETRY + 1):
        wait = 2 * attempt  # 2, 4, 6 সেকেন্ড
        print(f"⏳ সব মডেল ব্যস্ত। {wait}s পর আবার চেষ্টা ({attempt}/{MAX_RETRY})...")
        time.sleep(wait)
        try:
            resp = client.models.generate_content(
                model=model, contents=contents, config=config,
            )
            return resp.text
        except Exception as e:
            last_error = e

    raise RuntimeError(
        f"সব মডেল এই মুহূর্তে ব্যস্ত। ৫-১০ মিনিট পর আবার চেষ্টা করুন।\nশেষ ত্রুটি: {last_error}"
    )


def analyze_image(image_path: str, crop_hint: str | None = None,
                  land_area: str | None = None) -> dict:
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"ছবি পাওয়া যায়নি: {image_path}")

    mime, _ = mimetypes.guess_type(image_path)
    if mime is None or not mime.startswith("image/"):
        mime = "image/jpeg"

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    prompt = PROMPT
    if crop_hint:
        prompt += f"\nকৃষক জানিয়েছেন ফসলটি সম্ভবত: {crop_hint}\n"
    if land_area:
        prompt += (
            f"\nকৃষকের জমির পরিমাণ: {land_area} শতক। "
            "sar_osudh ঘরে প্রতি লিটারের মাত্রার পাশাপাশি এই জমির জন্য "
            "আনুমানিক মোট কতটুকু পানি ও ওষুধ লাগবে তাও লিখে দাও।\n"
        )

    client = _client()
    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime),
        prompt,
    ]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        temperature=0.0,  # যতটা সম্ভব একই রকম (consistent) উত্তরের জন্য
    )
    return json.loads(_generate(client, contents, config))


# ভয়েস/লেখা প্রশ্নের উত্তর (ছবি ছাড়া) — সাধারণ কৃষি পরামর্শ
ASK_PROMPT = (
    "তুমি বাংলাদেশের একজন অভিজ্ঞ কৃষি বিশেষজ্ঞ। "
    "কৃষকের প্রশ্নের উত্তর সহজ, সংক্ষিপ্ত বাংলায় দাও (৪-৬ বাক্যে)। "
    "ওষুধের কথা বললে নিরাপত্তা সতর্কতা জুড়ে দাও। "
    "নিশ্চিত না হলে স্থানীয় কৃষি অফিসারের সাথে কথা বলতে বলো।\n\nপ্রশ্ন: "
)


def ask_question(question: str) -> str:
    client = _client()
    config = types.GenerateContentConfig(temperature=0.3)
    return _generate(client, [ASK_PROMPT + question], config).strip()


def print_report(r: dict) -> None:
    line = "─" * 48
    print("\n" + line)
    print("🌾  ফসল ডাক্তার — রিপোর্ট")
    print(line)

    if not r.get("is_plant", True):
        print("❌ ছবিতে ফসল/পাতা পাওয়া যায়নি। স্পষ্ট করে আবার ছবি তুলুন।")
        print(line + "\n")
        return

    conf_bn = {"high": "উচ্চ ✅", "medium": "মাঝারি ⚠️", "low": "কম ❓"}
    print(f"🌱 ফসল        : {r.get('fosol', '-')}")
    print(f"🦠 রোগ/সমস্যা : {r.get('rog_naam', '-')}")
    print(f"📊 নিশ্চয়তা    : {conf_bn.get(r.get('confidence'), r.get('confidence', '-'))}")

    print(f"\n🔍 লক্ষণ:\n   {r.get('lokkhon', '-')}")
    print(f"\n❓ কারণ:\n   {r.get('karon', '-')}")

    print("\n✅ করণীয়:")
    for i, step in enumerate(r.get("protikar", []), 1):
        print(f"   {i}. {step}")

    print("\n💊 সার / ওষুধ:")
    for item in r.get("sar_osudh", []):
        print(f"   • {item}")

    if r.get("sotorkota"):
        print(f"\n🛡️  সতর্কতা:\n   {r['sotorkota']}")

    if r.get("officer_dekhano_uchit"):
        print("\n👨‍🌾 পরামর্শ: নিশ্চিত হতে স্থানীয় কৃষি অফিসারকে ছবিটি দেখান।")

    print("\n" + DISCLAIMER)
    print(line + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="ফসল ডাক্তার — বাংলা কৃষি পরামর্শ")
    parser.add_argument("image", help="পাতার/ফসলের ছবির পথ")
    parser.add_argument("--crop", help="ফসলের নাম (ঐচ্ছিক, যেমন: ধান, আলু, টমেটো)")
    parser.add_argument("--json", action="store_true", help="শুধু কাঁচা JSON দেখাও")
    args = parser.parse_args()

    try:
        result = analyze_image(args.image, args.crop)
    except Exception as e:
        print(f"\n❌ সমস্যা: {e}\n")
        sys.exit(1)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
