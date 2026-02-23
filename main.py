import os, sys, uuid, asyncio, shutil
from faster_whisper import WhisperModel
from flask import Flask, request, jsonify, send_file, render_template
from deep_translator import GoogleTranslator
import edge_tts

app = Flask(__name__, template_folder=".")

print("Loading Whisper model...")
model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Model ready!")

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
        target_lang = "ur" if language == "urdu" else "sd"
        translated_text = GoogleTranslator(source="auto", target=target_lang).translate(text)
        if not translated_text or not translated_text.strip():
            return jsonify({"success": False, "error": "Translation returned empty."}), 400
        output_file = f"output_{uuid.uuid4().hex}.mp3"
        async def save_audio():
            communicate = edge_tts.Communicate(translated_text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(output_file)
        asyncio.run(save_audio())
        for f in os.listdir("."):
            if f.startswith("output_") and f.endswith(".mp3") and f != output_file:
                try: os.remove(f)
                except: pass
        token = uuid.uuid4().hex
        app.config[f"audio_{token}"] = output_file
        sindhi_note = "(Sindhi text narrated using Urdu voice)" if language == "sindhi" else ""
        return jsonify({"success": True, "translated_text": translated_text, "audio_url": f"/audio?t={token}", "note": sindhi_note})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/audio")
def audio():
    token = request.args.get("t", "")
    filename = app.config.get(f"audio_{token}", "output.mp3")
    if not os.path.exists(filename):
        return "File not found", 404
    return send_file(filename, mimetype="audio/mpeg")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "video" not in request.files:
        return jsonify({"error": "No file uploaded"})
    
    uploaded = request.files["video"]
    filename = uploaded.filename.lower()
    input_path = f"upload_{uuid.uuid4().hex}"
    audio_path = input_path + ".wav"
    
    # Save uploaded file
    ext = os.path.splitext(filename)[1]
    raw_path = input_path + ext
    uploaded.save(raw_path)
    
    try:
        # Convert to wav using ffmpeg (handles both audio and video)
        os.system(f'ffmpeg -i "{raw_path}" -ar 16000 -ac 1 -c:a pcm_s16le "{audio_path}" -y -loglevel error')
        
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            return jsonify({"error": "Could not extract audio from file"})
        
        segments, _ = model.transcribe(audio_path)
        transcript = " ".join([s.text for s in segments])
        return jsonify({"transcript": transcript})
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if os.path.exists(raw_path): os.remove(raw_path)
        if os.path.exists(audio_path): os.remove(audio_path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
