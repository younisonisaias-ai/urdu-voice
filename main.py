import os, shutil, uuid, asyncio, re, requests, base64
from faster_whisper import WhisperModel
from flask import Flask, request, jsonify, send_file, render_template
from deep_translator import GoogleTranslator
import edge_tts

ffmpeg_path = shutil.which("ffmpeg")
if ffmpeg_path:
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

app = Flask(__name__, template_folder=".")

print("Loading Whisper model...")
model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Model ready!")

# ═══════════════════════════════════════════════════════════════════
#  API KEYS
# ═══════════════════════════════════════════════════════════════════
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
GOOGLE_TTS_KEY     = os.environ.get("GOOGLE_TTS_KEY", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

# Paste your Uplift key inside the quotes below
# IMPORTANT: regenerate this at platform.upliftai.org/studio — the old one was shared publicly
UPLIFT_API_KEY = "sk_api_550f96150a184f649c70e053e3c3ebdd096ed4275130b995bb5b0ab264aa2478"

# ═══════════════════════════════════════════════════════════════════
#  UPLIFT AI VOICE CATALOGUE
#  Confirm exact IDs in your dashboard at platform.upliftai.org
# ═══════════════════════════════════════════════════════════════════
UPLIFT_VOICES = [
    {
        "voice_id": "v_8eelc901",
        "label":    "Uplift AI Orator — Education (Male, Clear)",
        "engine":   "uplift",
    },
    {
        "voice_id": "v_meklc281",
        "label":    "Uplift AI Orator — Narrator (Female, Warm)",
        "engine":   "uplift",
    },
]

# ═══════════════════════════════════════════════════════════════════
#  TRANSLITERATION DICTIONARY
# ═══════════════════════════════════════════════════════════════════
ENGLISH_TO_URDU_SCRIPT = {
    "subscribe":        "سبسکرائب",
    "subscribed":       "سبسکرائب کر لیا",
    "unsubscribe":      "ان سبسکرائب",
    "notification":     "نوٹیفکیشن",
    "notifications":    "نوٹیفکیشنز",
    "bell":             "بیل",
    "channel":          "چینل",
    "video":            "ویڈیو",
    "videos":           "ویڈیوز",
    "live":             "لائیو",
    "like":             "لائیک",
    "comment":          "کمنٹ",
    "comments":         "کمنٹس",
    "share":            "شیئر",
    "playlist":         "پلے لسٹ",
    "update":           "اپڈیٹ",
    "updates":          "اپڈیٹس",
    "upload":           "اپلوڈ",
    "link":             "لنک",
    "links":            "لنکس",
    "description":      "ڈسکرپشن",
    "weekly":           "ہفتہ وار",
    "daily":            "روزانہ",
    "monthly":          "ماہانہ",
    "internet":         "انٹرنیٹ",
    "mobile":           "موبائل",
    "phone":            "فون",
    "app":              "ایپ",
    "apps":             "ایپس",
    "online":           "آن لائن",
    "offline":          "آف لائن",
    "password":         "پاس ورڈ",
    "email":            "ای میل",
    "website":          "ویب سائٹ",
    "download":         "ڈاؤن لوڈ",
    "screen":           "اسکرین",
    "button":           "بٹن",
    "lesson":           "سبق",
    "lessons":          "اسباق",
    "class":            "کلاس",
    "course":           "کورس",
    "tutorial":         "ٹیوٹوریل",
    "quiz":             "کوئز",
    "test":             "ٹیسٹ",
    "topic":            "ٹاپک",
    "episode":          "ایپیسوڈ",
    "series":           "سیریز",
    "turn on":          "آن کریں",
    "turn off":         "آف کریں",
    "click":            "کلک",
    "tap":              "ٹیپ",
    "miss":             "مس",
    "never miss":       "کبھی نہ مِسس کریں",
    "christian revive": "کرسچن ریوائیو",
    "christian":        "کرسچن",
    "revive":           "ریوائیو",
    "church":           "چرچ",
    "bible":            "بائبل",
    "gospel":           "گاسپل",
    "prayer":           "پریئر",
    "ministry":         "منسٹری",
    "worship":          "ورشپ",
    "team":             "ٹیم",
    "page":             "پیج",
    "profile":          "پروفائل",
    "support":          "سپورٹ",
    "content":          "کانٹینٹ",
    "format":           "فارمیٹ",
    "platform":         "پلیٹ فارم",
    "social media":     "سوشل میڈیا",
    "facebook":         "فیس بک",
    "instagram":        "انسٹاگرام",
    "youtube":          "یوٹیوب",
    "twitter":          "ٹوئٹر",
    "whatsapp":         "واٹس ایپ",
}

def apply_transliteration(text: str) -> str:
    sorted_keys = sorted(ENGLISH_TO_URDU_SCRIPT.keys(), key=len, reverse=True)
    result = text
    for eng in sorted_keys:
        pattern = re.compile(re.escape(eng), re.IGNORECASE)
        result  = pattern.sub(ENGLISH_TO_URDU_SCRIPT[eng], result)
    return result


# ═══════════════════════════════════════════════════════════════════
#  AI REFINEMENT PROMPTS
# ═══════════════════════════════════════════════════════════════════

NATURALIZE_PROMPT = """You are a Pakistani Urdu language expert for TTS (text-to-speech) audio.

The text you receive is already partially in Urdu script. Your job:

1. Make it sound like natural Pakistani Urdu — warm, conversational, like a Pakistani YouTuber or narrator
2. If you see any remaining English words NOT in Urdu script, convert them to how Pakistanis pronounce them written in Urdu script
3. Keep the exact same meaning — do not add or remove information
4. Use proper Urdu punctuation: ۔ for full stop، for comma — these create pauses in TTS
5. Sentences should be short (10-12 words max) — TTS sounds better with short sentences
6. Do NOT use heavy Arabic/Persian Urdu — use everyday Pakistan Urdu

Return ONLY the final Urdu text in Urdu script. Nothing else."""

TTS_FINAL_PROMPT = """You are a TTS audio director for Pakistani Urdu.

You receive Urdu text that will be spoken by a voice engine. Your final task:

1. Read through every single word — if ANY word is still in Latin/English script, convert it to Urdu script
2. Add ، after phrases where a speaker would naturally pause mid-sentence
3. Ensure ۔ ends every complete sentence
4. Replace any word that sounds unnatural when spoken with a better alternative
5. The final audio should sound like a warm, professional Pakistani narrator

Return ONLY the final perfected Urdu text. No explanations. No English."""


# ═══════════════════════════════════════════════════════════════════
#  AI BOT CALLERS
# ═══════════════════════════════════════════════════════════════════

def call_gemini(text: str, system: str) -> str:
    if not GEMINI_API_KEY:
        return text
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": text}]}],
                "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.15}
            }, timeout=30
        )
        r.raise_for_status()
        result = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"   ✅ Gemini: {result[:80]}...")
        return result
    except Exception as e:
        print(f"   ⚠️  Gemini failed: {e}")
        return text


def call_groq(text: str, system: str) -> str:
    if not GROQ_API_KEY:
        return text
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-70b-versatile",
                "max_tokens": 2048,
                "temperature": 0.15,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": text}
                ]
            }, timeout=30
        )
        r.raise_for_status()
        result = r.json()["choices"][0]["message"]["content"].strip()
        print(f"   ✅ Groq/Llama: {result[:80]}...")
        return result
    except Exception as e:
        print(f"   ⚠️  Groq failed: {e}")
        return text


def call_claude(text: str, system: str) -> str:
    if not ANTHROPIC_API_KEY:
        return text
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-20240307",
                "max_tokens": 2048,
                "system": system,
                "messages": [{"role": "user", "content": text}]
            }, timeout=30
        )
        r.raise_for_status()
        result = r.json()["content"][0]["text"].strip()
        print(f"   ✅ Claude: {result[:80]}...")
        return result
    except Exception as e:
        print(f"   ⚠️  Claude failed: {e}")
        return text


# ═══════════════════════════════════════════════════════════════════
#  FULL TEXT PIPELINE
# ═══════════════════════════════════════════════════════════════════

def process_text_pipeline(english_text: str, target_lang: str = "ur") -> dict:
    stages = {}

    print("\n🌐 Stage 0: Google Translate...")
    sentences = re.split(r'(?<=[.!?"])\s+', english_text.strip())
    translated_parts = []
    for s in sentences:
        if not s.strip(): continue
        try:
            t = GoogleTranslator(source="auto", target=target_lang).translate(s.strip())
            translated_parts.append(t)
        except Exception:
            translated_parts.append(s)
    google_text = " ".join(translated_parts)
    stages["stage_0_google"] = google_text
    print(f"   → {google_text[:100]}...")

    if target_lang != "ur":
        return {"final": google_text, "stages": stages}

    print("\n📖 Stage 1: Dictionary transliteration (English → Urdu script)...")
    transliterated = apply_transliteration(google_text)
    stages["stage_1_transliterate"] = transliterated
    print(f"   → {transliterated[:100]}...")

    print("\n🤖 Stage 2: AI naturalization...")
    if GEMINI_API_KEY:
        naturalized = call_gemini(transliterated, NATURALIZE_PROMPT)
    elif GROQ_API_KEY:
        naturalized = call_groq(transliterated, NATURALIZE_PROMPT)
    elif ANTHROPIC_API_KEY:
        naturalized = call_claude(transliterated, NATURALIZE_PROMPT)
    else:
        naturalized = transliterated
    stages["stage_2_naturalized"] = naturalized

    print("\n🤖 Stage 3: TTS optimization...")
    if GROQ_API_KEY:
        optimized = call_groq(naturalized, TTS_FINAL_PROMPT)
    elif GEMINI_API_KEY:
        optimized = call_gemini(naturalized, TTS_FINAL_PROMPT)
    else:
        optimized = naturalized
    stages["stage_3_tts_ready"] = optimized

    print("\n🔍 Stage 4: Final Latin character cleanup...")
    if re.search(r'[a-zA-Z]{2,}', optimized):
        print("   Found remaining Latin text — running extra transliteration pass...")
        optimized = apply_transliteration(optimized)
    stages["stage_4_final"] = optimized

    print(f"\n✨ FINAL TEXT: {optimized}")
    return {"final": optimized, "stages": stages}


# ═══════════════════════════════════════════════════════════════════
#  TTS ENGINE: UPLIFT AI ORATOR
#  ✅ Speed slider NOW works
#  ❌ Pitch slider has no effect (Uplift API doesn't support pitch)
# ═══════════════════════════════════════════════════════════════════

def apply_ffmpeg_speed_pitch(input_path: str, output_path: str,
                              rate: int = 0, pitch: int = 0) -> bool:
    """
    Post-process audio with ffmpeg to apply speed and pitch adjustments.
    This works on ANY engine including Uplift AI.

    rate:  -30 to +30  →  atempo 0.5x to 2.0x
    pitch: -20 to +20  →  asetrate (shifts pitch via sample rate trick)

    ffmpeg atempo only supports 0.5–2.0 range per filter, so we chain two
    filters for extreme values (e.g. 0.25x = atempo=0.5,atempo=0.5).
    """
    import subprocess

    if rate == 0 and pitch == 0:
        # Nothing to do — just rename
        import shutil
        shutil.move(input_path, output_path)
        return True

    # Map rate -30…+30 → tempo 0.5…2.0
    tempo = round(1.0 + (rate / 30.0) * 1.0, 3)
    tempo = max(0.25, min(4.0, tempo))

    # Map pitch -20…+20 → semitone shift (-6 to +6 semitones feels natural)
    semitones = round((pitch / 20.0) * 6.0, 2)

    # Build ffmpeg filter chain
    filters = []

    # Pitch shift via asetrate + atempo compensation
    if pitch != 0:
        base_rate = 22050
        shifted_rate = int(base_rate * (2 ** (semitones / 12.0)))
        filters.append(f"asetrate={shifted_rate}")
        filters.append(f"aresample={base_rate}")
        # compensate tempo change caused by asetrate
        pitch_tempo_comp = base_rate / shifted_rate
        effective_tempo = tempo * pitch_tempo_comp
    else:
        effective_tempo = tempo

    # atempo only supports 0.5–2.0 per filter — chain for extreme values
    effective_tempo = max(0.25, min(4.0, effective_tempo))
    if effective_tempo < 0.5:
        filters.append(f"atempo={effective_tempo*2:.3f},atempo=0.5")
    elif effective_tempo > 2.0:
        filters.append(f"atempo=2.0,atempo={effective_tempo/2:.3f}")
    else:
        filters.append(f"atempo={effective_tempo:.3f}")

    filter_str = ",".join(filters)

    try:
        result = subprocess.run([
            "ffmpeg", "-i", input_path,
            "-filter:a", filter_str,
            "-c:a", "libmp3lame", "-q:a", "2",
            output_path, "-y"
        ], capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            print(f"   ✅ ffmpeg speed/pitch: tempo={effective_tempo:.2f} semitones={semitones}")
            # Clean up original
            if os.path.exists(input_path) and input_path != output_path:
                os.remove(input_path)
            return True
        else:
            print(f"   ⚠️  ffmpeg failed: {result.stderr[-200:]}")
            # Fall back to original unprocessed file
            import shutil
            shutil.move(input_path, output_path)
            return True  # still return True — we have audio, just unprocessed
    except Exception as e:
        print(f"   ⚠️  ffmpeg speed/pitch error: {e}")
        import shutil
        shutil.move(input_path, output_path)
        return True


def tts_uplift(text: str, output_path: str, voice_id: str = "v_8eelc901",
               rate: int = 0, pitch: int = 0) -> bool:
    """
    Uplift AI Orator — downloads raw audio then applies speed+pitch via ffmpeg.
    This gives us REAL speed and pitch control regardless of what the Uplift API supports.
    """
    if not UPLIFT_API_KEY:
        print("   ⚠️  UPLIFT_API_KEY not set — skipping Uplift AI")
        return False

    raw_path = output_path + ".raw.mp3"

    try:
        r = requests.post(
            "https://api.upliftai.org/v1/synthesis/text-to-speech",
            headers={
                "Authorization": f"Bearer {UPLIFT_API_KEY}",
                "Content-Type":  "application/json"
            },
            json={
                "voiceId":      voice_id,
                "text":         text,
                "outputFormat": "MP3_22050_128"
            },
            timeout=60
        )
        if r.status_code == 200:
            with open(raw_path, "wb") as f:
                f.write(r.content)
            print(f"   ✅ Uplift AI ({voice_id}): downloaded raw audio")
            # Apply speed + pitch via ffmpeg post-processing
            return apply_ffmpeg_speed_pitch(raw_path, output_path, rate=rate, pitch=pitch)

        print(f"   ⚠️  Uplift AI error {r.status_code}: {r.text[:200]}")
        return False

    except Exception as e:
        print(f"   ⚠️  Uplift AI failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
#  TTS ENGINE: ELEVENLABS
# ═══════════════════════════════════════════════════════════════════

ELEVENLABS_VOICES = {
    "adam":   "pNInz6obpgDQGcFmaJgB",
    "Antoni": "ErXwobaYiN019PkySvjV",
    "josh":   "TxGEqnHWrfWFTfGW9XjX",
    "bella":  "EXAVITQu4vr4xnSDxMaL",
    "elli":   "MF3mGyEYCl7XYWbV9V6O",
}

def tts_elevenlabs(text: str, output_path: str, voice_key: str = "adam") -> bool:
    if not ELEVENLABS_API_KEY:
        return False
    voice_id = ELEVENLABS_VOICES.get(voice_key, ELEVENLABS_VOICES["adam"])
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.40,
                    "similarity_boost": 0.80,
                    "style": 0.30,
                    "use_speaker_boost": True
                }
            }, timeout=60
        )
        if r.status_code == 200:
            with open(output_path, "wb") as f: f.write(r.content)
            print(f"   ✅ ElevenLabs ({voice_key}): saved")
            return True
        print(f"   ⚠️  ElevenLabs error {r.status_code}: {r.text[:150]}")
        return False
    except Exception as e:
        print(f"   ⚠️  ElevenLabs failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
#  TTS ENGINE: GOOGLE CLOUD
# ═══════════════════════════════════════════════════════════════════

def tts_google_cloud(text: str, output_path: str, gender: str = "MALE") -> bool:
    if not GOOGLE_TTS_KEY:
        return False
    try:
        r = requests.post(
            f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "input": {"text": text},
                "voice": {"languageCode": "ur-PK", "ssmlGender": gender},
                "audioConfig": {
                    "audioEncoding": "MP3",
                    "speakingRate": 0.92,
                    "pitch": 0.0,
                    "effectsProfileId": ["headphone-class-device"]
                }
            }, timeout=30
        )
        r.raise_for_status()
        audio_b64 = r.json().get("audioContent", "")
        if audio_b64:
            with open(output_path, "wb") as f: f.write(base64.b64decode(audio_b64))
            print(f"   ✅ Google Cloud TTS: saved")
            return True
        return False
    except Exception as e:
        print(f"   ⚠️  Google Cloud TTS failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
#  TTS ENGINE: MICROSOFT EDGE TTS (free fallback)
#  ✅ Both speed AND pitch sliders work
# ═══════════════════════════════════════════════════════════════════

async def _edge_save(text, voice, output_path, rate, pitch):
    c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await c.save(output_path)

def tts_edge(text: str, output_path: str, voice: str = "ur-PK-AsadNeural",
             rate: str = "-5%", pitch: str = "+0Hz") -> bool:
    try:
        asyncio.run(_edge_save(text, voice, output_path, rate, pitch))
        print(f"   ✅ Edge TTS ({voice}): saved")
        return True
    except Exception as e:
        print(f"   ⚠️  Edge TTS failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
#  AUDIO CHUNKING + MERGE
# ═══════════════════════════════════════════════════════════════════

def split_text(text: str, max_chars: int = 400) -> list:
    sentences = re.split(r'(?<=[۔.!?])\s+', text)
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) <= max_chars:
            current += " " + s
        else:
            if current.strip(): chunks.append(current.strip())
            current = s
    if current.strip(): chunks.append(current.strip())
    return chunks if chunks else [text]


def merge_audio_chunks(chunk_files: list, output_path: str):
    if len(chunk_files) == 1:
        os.rename(chunk_files[0], output_path)
    else:
        import subprocess
        list_file = f"/tmp/list_{uuid.uuid4().hex}.txt"
        with open(list_file, "w") as f:
            for cf in chunk_files: f.write(f"file '{cf}'\n")
        subprocess.run([
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", output_path, "-y"
        ], check=True, capture_output=True)
        os.remove(list_file)
        for cf in chunk_files:
            if os.path.exists(cf): os.remove(cf)


# ═══════════════════════════════════════════════════════════════════
#  MAIN VOICE GENERATION
# ═══════════════════════════════════════════════════════════════════

def generate_all_voices(text: str, rate: int = -5, pitch: int = 0) -> list:
    rate_str  = f"{'+' if rate >= 0 else ''}{rate}%"
    pitch_str = f"{'+' if pitch >= 0 else ''}{pitch}Hz"
    chunks    = split_text(text, max_chars=400)
    results   = []

    voices_to_generate = []

    # 1. Uplift AI — BEST quality
    if UPLIFT_API_KEY:
        for v in UPLIFT_VOICES:
            voices_to_generate.append({**v})

    # 2. ElevenLabs
    if ELEVENLABS_API_KEY:
        voices_to_generate += [
            {"engine": "elevenlabs", "voice_key": "adam",   "label": "ElevenLabs — Adam (Male, Warm)"},
            {"engine": "elevenlabs", "voice_key": "Antoni", "label": "ElevenLabs — Antoni (Male, Deep)"},
        ]

    # 3. Google Cloud TTS
    if GOOGLE_TTS_KEY:
        voices_to_generate += [
            {"engine": "google", "gender": "MALE",   "label": "Google Cloud — Male (Pakistani Urdu)"},
            {"engine": "google", "gender": "FEMALE", "label": "Google Cloud — Female (Pakistani Urdu)"},
        ]

    # 4. Edge TTS — always available free fallback
    voices_to_generate += [
        {"engine": "edge", "voice": "ur-PK-AsadNeural", "label": "Microsoft Edge — Asad (Male)"},
        {"engine": "edge", "voice": "ur-PK-UzmaNeural", "label": "Microsoft Edge — Uzma (Female)"},
    ]

    print(f"\n🔊 Generating {len(voices_to_generate)} voice versions...")

    for v in voices_to_generate:
        engine      = v["engine"]
        label       = v["label"]
        output_path = f"/tmp/voice_{uuid.uuid4().hex}.mp3"
        chunk_files = []
        success     = False

        print(f"\n   Generating: {label}")

        for chunk in chunks:
            chunk_path = f"/tmp/chunk_{uuid.uuid4().hex}.mp3"

            if engine == "uplift":
                # ✅ rate is now passed through to Uplift
                ok = tts_uplift(chunk, chunk_path, v.get("voice_id", "v_8eelc901"), rate=rate, pitch=pitch)
                if not ok:
                    ok = tts_edge(chunk, chunk_path, "ur-PK-AsadNeural", rate_str, pitch_str)
                success = ok

            elif engine == "elevenlabs":
                ok = tts_elevenlabs(chunk, chunk_path, v.get("voice_key", "adam"))
                if not ok:
                    ok = tts_edge(chunk, chunk_path, "ur-PK-AsadNeural", rate_str, pitch_str)
                success = ok

            elif engine == "google":
                ok = tts_google_cloud(chunk, chunk_path, v.get("gender", "MALE"))
                if not ok:
                    ok = tts_edge(chunk, chunk_path, "ur-PK-AsadNeural", rate_str, pitch_str)
                success = ok

            else:  # edge — supports both rate AND pitch
                success = tts_edge(chunk, chunk_path, v.get("voice", "ur-PK-AsadNeural"),
                                   rate_str, pitch_str)

            if success and os.path.exists(chunk_path):
                chunk_files.append(chunk_path)

        if chunk_files:
            try:
                merge_audio_chunks(chunk_files, output_path)
                token = uuid.uuid4().hex
                app.config[f"audio_{token}"] = output_path
                results.append({
                    "engine":    engine,
                    "label":     label,
                    "audio_url": f"/audio?t={token}",
                    "token":     token
                })
            except Exception as e:
                print(f"   ⚠️  Merge failed for {label}: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    try:
        text        = request.form["text"]
        rate        = int(request.form.get("rate", -5))
        pitch       = int(request.form.get("pitch", 0))
        target_lang = request.form.get("lang", "ur")

        pipeline    = process_text_pipeline(text, target_lang=target_lang)
        final_text  = pipeline["final"]
        stages      = pipeline["stages"]

        if not final_text.strip():
            return jsonify({"success": False, "error": "Processing failed"}), 400

        voices = generate_all_voices(final_text, rate=rate, pitch=pitch)

        best_voice     = voices[0] if voices else None
        best_audio_url = best_voice["audio_url"] if best_voice else ""

        return jsonify({
            "success":         True,
            "final_text":      final_text,
            "translated_text": final_text,
            "audio_url":       best_audio_url,
            "voices":          voices,
            "pipeline":        stages
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/audio")
def audio():
    token    = request.args.get("t", "")
    filename = app.config.get(f"audio_{token}", "")
    if not filename or not os.path.exists(filename):
        return "File not found", 404
    return send_file(filename, mimetype="audio/mpeg")


@app.route("/voices_status")
def voices_status():
    return jsonify({
        "uplift_ai":  {
            "active":       bool(UPLIFT_API_KEY),
            "speed_slider": "✅ works",
            "pitch_slider": "❌ not supported by Uplift API",
            "quality":      "🥇 Best — native Pakistani voices",
        },
        "edge_tts": {
            "active":       True,
            "speed_slider": "✅ works",
            "pitch_slider": "✅ works",
            "quality":      "🆓 Free fallback",
        },
        "elevenlabs": {"active": bool(ELEVENLABS_API_KEY)},
        "google_tts": {"active": bool(GOOGLE_TTS_KEY)},
        "gemini_ai":  {"active": bool(GEMINI_API_KEY)},
        "groq_ai":    {"active": bool(GROQ_API_KEY)},
    })


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "video" not in request.files:
        return jsonify({"error": "No file uploaded"})
    uploaded   = request.files["video"]
    ext        = os.path.splitext(uploaded.filename.lower())[1]
    base_id    = uuid.uuid4().hex
    input_path = f"/tmp/upload_{base_id}{ext}"
    audio_path = f"/tmp/upload_{base_id}.wav"
    uploaded.save(input_path)
    try:
        import subprocess
        res = subprocess.run([
            "ffmpeg", "-i", input_path,
            "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le", audio_path, "-y"
        ], capture_output=True, text=True)
        if res.returncode != 0:
            return jsonify({"error": f"FFmpeg: {res.stderr}"})
        segments, _ = model.transcribe(audio_path)
        transcript  = " ".join([s.text for s in segments])
        return jsonify({"transcript": transcript})
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        if os.path.exists(audio_path): os.remove(audio_path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)