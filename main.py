import os
import shutil
import subprocess
import uuid
import asyncio
from faster_whisper import WhisperModel
from flask import Flask, request, jsonify, send_file, render_template
from deep_translator import GoogleTranslator
import edge_tts

# 1. SETUP SYSTEM PATHS FOR RAILWAY
ffmpeg_exe = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_exe

app = Flask(__name__, template_folder=".")

# 2. LOAD MODEL
print("Loading Whisper model...")
# Using CPU and int8 for lower memory usage on Railway
model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Model ready!")

@app.route("/")
def index():
    return render_template("index.html")

def split_text(text, max_chars=1000):
    """Split text into chunks at sentence boundaries"""
    sentences = text.replace('۔', '۔|').replace('.', '.|').replace('!', '!|').replace('?', '?|').split('|')
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) <= max_chars:
            current += s
        else:
            if current: chunks.append(current.strip())
            current = s
    if current: chunks.append(current.strip())
    return [c for c in chunks if c]

@app.route("/generate", methods=["POST"])
def generate():
    try:
        text = request.form["text"]
        voice = request.form["voice"]
        rate = int(request.form.get("rate", 0))
        pitch = int(request.form.get("pitch", 0))
        language = request.form.get("language", "urdu")

        rate_str = f"{'+' if rate >= 0 else ''}{rate}%"
        pitch_str = f"{'+' if pitch >= 0 else ''}{pitch}Hz"
        target_lang = "ur" if language == "urdu" else "sd"

        # Translation Logic
        if len(text) > 4000:
            words = text.split()
            parts = [' '.join(words[i:i + 500]) for i in range(0, len(words), 500)]
            translated_text = ' '.join([
                GoogleTranslator(source="auto", target=target_lang).translate(p)
                for p in parts
            ])
        else:
            translated_text = GoogleTranslator(source="auto", target=target_lang).translate(text)

        if not translated_text or not translated_text.strip():
            return jsonify({"success": False, "error": "Translation empty."}), 400

        # TTS Logic
        chunks = split_text(translated_text, max_chars=1000)
        chunk_files = []

        async def save_chunks():
            for chunk in chunks:
                chunk_file = f"/tmp/chunk_{uuid.uuid4().hex}.mp3"
                communicate = edge_tts.Communicate(chunk, voice, rate=rate_str, pitch=pitch_str)
                await communicate.save(chunk_file)
                chunk_files.append(chunk_file)

        asyncio.run(save_chunks())

        # Combine Audio Chunks using the correct FFmpeg path
        output_file = f"/tmp/output_{uuid.uuid4().hex}.mp3"
        if len(chunk_files) == 1:
            os.rename(chunk_files[0], output_file)
        else:
            list_file = f"/tmp/list_{uuid.uuid4().hex}.txt"
            with open(list_file, "w") as f:
                for cf in chunk_files:
                    f.write(f"file '{cf}'\n")

            subprocess.run([
                ffmpeg_exe, "-f", "concat", "-safe", "0", 
                "-i", list_file, "-c", "copy", output_file, "-y"
            ], check=True)

            os.remove(list_file)
            for cf in chunk_files:
                if os.path.exists(cf): os.remove(cf)

        # Cleanup old tmp files
        for f in os.listdir("/tmp"):
            if f.startswith("output_") and f.endswith(".mp3"):
                full_path = os.path.join("/tmp", f)
                if full_path != output_file:
                    try: os.remove(full_path)
                    except: pass

        token = uuid.uuid4().hex
        app.config[f"audio_{token}"] = output_file
        sindhi_note = "(Sindhi text narrated using Urdu voice)" if language == "sindhi" else ""

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
    filename = app.config.get(f"audio_{token}")
    if not filename or not os.path.exists(filename):
        return "File not found", 404
    return send_file(filename, mimetype="audio/mpeg")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "video" not in request.files:
        return jsonify({"error": "No file uploaded"})

    uploaded = request.files["video"]
    ext = os.path.splitext(uploaded.filename.lower())[1]
    base_id = uuid.uuid4().hex
    input_path = f"/tmp/upload_{base_id}{ext}"
    audio_path = f"/tmp/upload_{base_id}.wav"

    uploaded.save(input_path)

    try:
        # Extract Audio using FFmpeg
        ffmpeg_cmd = [
            ffmpeg_exe, "-i", input_path, 
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", 
            audio_path, "-y"
        ]

        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({"error": f"Audio extraction failed: {result.stderr}"})

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            return jsonify({"error": "Final audio file is empty."})

        # Run Whisper Transcription
        segments, _ = model.transcribe(audio_path)
        transcript = " ".join([s.text for s in segments])

        return jsonify({"transcript": transcript})

    except Exception as e:
        return jsonify({"error": str(e)})

    finally:
        # Final cleanup
        if os.path.exists(input_path): os.remove(input_path)
        if os.path.exists(audio_path): os.remove(audio_path)

if __name__ == "__main__":
    # Important: Railway uses the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)