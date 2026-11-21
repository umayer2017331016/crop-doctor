"""
ফসল ডাক্তার — ওয়েব অ্যাপ (ক্যামেরা + বাংলা ভয়েস + ইতিহাস + প্রশ্ন)
=================================================================
চালান:
    python app.py
ব্রাউজারে:  http://localhost:5000
ফোনে (একই নেটওয়ার্ক):  http://<পিসির-IP>:5000
"""

import os
import json
import time
import tempfile
from datetime import datetime

try:
    from flask import Flask, request, jsonify, render_template, send_from_directory
except ImportError:
    raise SystemExit("Flask নেই। চালান:  pip install flask")

from crop_doctor import analyze_image, ask_question

app = Flask(__name__, template_folder=".")  # HTML মূল ফোল্ডারেই (হোস্টিং সহজ করতে)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # সর্বোচ্চ ১২ MB

# সেভ করা ছবি ও রিপোর্ট এখানে জমা হবে (আপনার নিজের ডেটাসেট)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
IMG_DIR = os.path.join(DATA_DIR, "images")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SHOPS_FILE = os.path.join(DATA_DIR, "shops.json")
os.makedirs(IMG_DIR, exist_ok=True)


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_history():
    return _load_json(HISTORY_FILE, [])


def _save_history(records):
    _save_json(HISTORY_FILE, records)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    if "image" not in request.files or not request.files["image"].filename:
        return jsonify({"ok": False, "error": "ছবি পাওয়া যায়নি।"}), 400

    file = request.files["image"]
    crop = (request.form.get("crop") or "").strip() or None
    land = (request.form.get("land") or "").strip() or None

    rec_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + str(int(time.time() * 1000) % 1000)
    img_name = f"{rec_id}.jpg"
    img_path = os.path.join(IMG_DIR, img_name)

    try:
        file.save(img_path)
        result = analyze_image(img_path, crop, land)

        # ইতিহাসে ও ডেটাসেটে যোগ করি
        records = _load_history()
        records.insert(0, {
            "id": rec_id,
            "time": datetime.now().strftime("%d/%m/%Y %I:%M %p"),
            "image": img_name,
            "crop": crop or result.get("fosol", ""),
            "fosol": result.get("fosol", ""),
            "rog_naam": result.get("rog_naam", ""),
            "confidence": result.get("confidence", ""),
            "report": result,
        })
        _save_history(records[:200])  # সর্বশেষ ২০০টি রাখি

        return jsonify({"ok": True, "data": result, "id": rec_id, "image": img_name})
    except Exception as e:
        # বিশ্লেষণ ব্যর্থ হলে সেভ করা ছবি মুছে ফেলি
        if os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/history")
def history():
    recs = _load_history()
    # হালকা লিস্ট (রিপোর্টসহ, যাতে ট্যাপ করলেই পুরোটা দেখা যায়)
    return jsonify({"ok": True, "items": recs})


@app.route("/saved/<name>")
def saved_image(name):
    return send_from_directory(IMG_DIR, name)


@app.route("/ask", methods=["POST"])
def ask():
    q = (request.json or {}).get("question", "").strip()
    if not q:
        return jsonify({"ok": False, "error": "প্রশ্ন পাওয়া যায়নি।"}), 400
    try:
        answer = ask_question(q)
        return jsonify({"ok": True, "answer": answer})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------- কৃষি দোকান (এলাকাভিত্তিক) ----------
# অ্যাডমিন পেজের গোপন PIN (পরিবর্তন করতে: $env:ADMIN_PIN = "আপনার-পিন")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")


@app.route("/shops")
def shops():
    return jsonify({"ok": True, "items": _load_json(SHOPS_FILE, [])})


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/admin/shops", methods=["POST"])
def add_shop():
    data = request.json or {}
    if data.get("pin") != ADMIN_PIN:
        return jsonify({"ok": False, "error": "ভুল PIN।"}), 403

    name = (data.get("name") or "").strip()
    area = (data.get("area") or "").strip()
    phone = (data.get("phone") or "").strip()
    if not name or not area:
        return jsonify({"ok": False, "error": "দোকানের নাম ও এলাকা দিন।"}), 400

    shops_list = _load_json(SHOPS_FILE, [])
    shops_list.append({
        "id": str(int(time.time() * 1000)),
        "name": name,
        "area": area,
        "phone": phone,
        "address": (data.get("address") or "").strip(),
        "map": (data.get("map") or "").strip(),
    })
    _save_json(SHOPS_FILE, shops_list)
    return jsonify({"ok": True, "items": shops_list})


@app.route("/admin/shops/delete", methods=["POST"])
def delete_shop():
    data = request.json or {}
    if data.get("pin") != ADMIN_PIN:
        return jsonify({"ok": False, "error": "ভুল PIN।"}), 403
    shop_id = data.get("id")
    shops_list = [s for s in _load_json(SHOPS_FILE, []) if s.get("id") != shop_id]
    _save_json(SHOPS_FILE, shops_list)
    return jsonify({"ok": True, "items": shops_list})


if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️  GEMINI_API_KEY সেট করা নেই! আগে সেট করুন:")
        print('   $env:GEMINI_API_KEY = "আপনার-key"')

    # https দিলে ফোনে Wake Lock (ঘুম আটকানো), মাইক্রোফোন ও লোকেশন কাজ করে।
    # 'adhoc' = নিজে থেকেই একটা অস্থায়ী সার্টিফিকেট বানায় (cryptography লাগে)।
    # টানেল (Cloudflare) দিয়ে পাবলিক করতে চাইলে:  $env:NO_HTTPS = "1"  (তখন টানেলই https দেবে)
    ssl_ctx = None
    if not os.environ.get("NO_HTTPS"):
        try:
            import cryptography  # noqa: F401
            ssl_ctx = "adhoc"
        except ImportError:
            pass

    port = int(os.environ.get("PORT", 5000))  # হোস্টিং-এ PORT আলাদা হতে পারে
    proto = "https" if ssl_ctx else "http"
    print("\n🌾 ফসল ডাক্তার চালু হচ্ছে...")
    print(f"   কম্পিউটারে:  {proto}://localhost:{port}")
    print(f"   ফোনে (একই নেটওয়ার্ক): {proto}://<পিসির-IP>:{port}")
    if ssl_ctx:
        print("   ⚠️ ফোনে প্রথমবার 'Not secure' সতর্কতা আসবে →")
        print("      'Advanced' → 'Proceed / চালিয়ে যান' চাপুন। এটা স্বাভাবিক।\n")

    app.run(host="0.0.0.0", port=port, debug=False, ssl_context=ssl_ctx)
