from flask import Flask, request, render_template, jsonify, send_file
from deep_translator import GoogleTranslator
import edge_tts, asyncio, uuid, os

app = Flask(__name__, template_folder=".")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate", methods=["POST"])
def generate():
    try:
        text     = request.form["text"]
        voice    = request.form["voice"]
        rate     = int(request.form.get("rate", 0))
        pitch    = int(request.form.get("pitch", 0))
        language = request.form.get("language", "urdu")

        rate_str  = f"{'+' if rate  >= 0 else ''}{rate}%"
        pitch_str = f"{'+' if pitch >= 0 else ''}{pitch}Hz"

        # Google Translate codes
        target_lang = "ur" if language == "urdu" else "sd"
        translated_text = GoogleTranslator(source="auto", target=target_lang).translate(text)

        if not translated_text or not translated_text.strip():
            return jsonify({"success": False, "error": "Translation returned empty. Try different text."}), 400

        output_file = f"output_{uuid.uuid4().hex}.mp3"

        async def save_audio():
            communicate = edge_tts.Communicate(translated_text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(output_file)

        asyncio.run(save_audio())

        if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            return jsonify({"success": False, "error": "Audio generation failed — voice may not support this text."}), 500

        # Cleanup old files
        for f in os.listdir("."):
            if f.startswith("output_") and f.endswith(".mp3") and f != output_file:
                try: os.remove(f)
                except: pass

        token = uuid.uuid4().hex
        app.config[f"audio_{token}"] = output_file

        sindhi_note = " (Sindhi text narrated using Urdu voice — same Nastaliq script)" if language == "sindhi" else ""

        return jsonify({
            "success": True,
            "translated_text": translated_text,
            "audio_url": f"/audio?t={token}",
            "note": sindhi_note
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/audio")
def audio():
    token = request.args.get("t", "")
    filename = app.config.get(f"audio_{token}", "output.mp3")
    if not os.path.exists(filename):
        return "File not found", 404
    return send_file(filename, mimetype="audio/mpeg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)