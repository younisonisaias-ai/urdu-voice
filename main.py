from flask import Flask, request, render_template, jsonify, send_file
from deep_translator import GoogleTranslator
import edge_tts, asyncio, uuid

app = Flask(__name__, template_folder=".")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate", methods=["POST"])
def generate():
    try:
        text = request.form["text"]
        voice = request.form["voice"]
        rate = int(request.form.get("rate", 0))
        pitch = int(request.form.get("pitch", 0))

        rate_str = f"{'+' if rate >= 0 else ''}{rate}%"
        pitch_str = f"{'+' if pitch >= 0 else ''}{pitch}Hz"

        urdu_text = GoogleTranslator(source='auto', target='ur').translate(text)

        async def save_audio():
            communicate = edge_tts.Communicate(urdu_text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save("output.mp3")

        asyncio.run(save_audio())
        return jsonify({"success": True, "urdu_text": urdu_text, "audio_url": "/audio?t=" + uuid.uuid4().hex})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/audio")
def audio():
    return send_file("output.mp3", mimetype="audio/mpeg")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
