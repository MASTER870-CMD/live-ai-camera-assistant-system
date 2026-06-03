import os
import webbrowser
import asyncio
import io
import traceback
import cv2
import pyaudio
import PIL.Image
import argparse
import threading
import http.server
import socketserver
import time
import json
import urllib.parse

try:
    import psutil
except ImportError:
    print("[ERROR] Please install psutil: pip install psutil")
    exit(1)

from google import genai
from google.genai import types

# =====================================================================
# GLOBAL VARIABLES FOR SYSTEM STATE & COMMLINK
# =====================================================================
LATEST_JPEG = b""  
TARGET_CAM_SOURCE = "0" 
TEXT_PROMPT_QUEUE = []  
AI_CHAT_QUEUE = []      

# =====================================================================
# AUDIO & AI SETTINGS
# =====================================================================
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
MODEL = "models/gemini-3.1-flash-live-preview"

# --- API CLIENT ---
client = genai.Client(
    http_options={"api_version": "v1beta"},
    api_key="AIzaSyA27SuEolvO5toOw2ipPrKhi-outcio9mA", 
)

# ---------------------------------------------------------------------
# CRITICAL FIX: THE NEXUS SYSTEM OVERRIDE PROMPT
# ---------------------------------------------------------------------
CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"], 
    system_instruction=types.Content(
        parts=[
            types.Part.from_text(
                text=(
                    "You are NEXUS, an advanced AI assistant built for Shashank Gowda NB. "
                    "You have FULL REAL-TIME MULTIMODAL VISION. "
                    "CRITICAL RULES: "
                    "1. NEVER say 'I am just a language model' or 'I cannot see'. "
                    "2. If the user asks about an object (e.g., 'What laptop is this?', 'What company bottle is this?'), YOU MUST LOOK AT THE CAMERA FEED and accurately describe the brand, text, logos, and details you see. "
                    "3. Always analyze the single MOST RECENT frame. "
                    "4. If the user sends a typed message, it is high priority. You MUST answer it out loud immediately."
                )
            )
        ]
    ),
    media_resolution="MEDIA_RESOLUTION_MEDIUM",
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
        )
    ),
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=104857,
        sliding_window=types.SlidingWindow(target_tokens=52428),
    ),
)

pya = pyaudio.PyAudio()

# =====================================================================
# HARDWARE TELEMETRY FUNCTION
# =====================================================================
def get_hardware_stats():
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    batt = psutil.sensors_battery()
    batt_str = f"{batt.percent}%" if batt else "AC/DESKTOP"
    return json.dumps({
        "cpu": cpu,
        "ram_used": round(ram.used / (1024**3), 2),
        "ram_total": round(ram.total / (1024**3), 2),
        "battery": batt_str
    })

# =====================================================================
# EMBEDDED HTML DASHBOARD (NEXUS SYSTEM PREMIUM UI)
# =====================================================================
HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NEXUS SYSTEM CORE</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <style>
        :root { 
            --bg-color: #050505; 
            --panel-bg: rgba(20, 20, 20, 0.4); 
            --gold: #d4af37; 
            --gold-glow: #f9d77e;
            --dark-gold: #8a7322;
            --red: #ff4444; 
            --green: #00ff66; 
            --text-main: #e0e0e0; 
        }
        
        body { 
            background-color: var(--bg-color); 
            color: var(--text-main); 
            font-family: 'Share Tech Mono', monospace; 
            height: 100vh; 
            overflow: hidden; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            background-image: radial-gradient(circle at center, #1a1a1a 0%, #000 100%); 
            margin: 0; 
        }
        
        .hud-container { 
            width: 98vw; 
            height: 96vh; 
            border: 1px solid var(--dark-gold); 
            border-radius: 20px; 
            padding: 15px; 
            box-shadow: 0 0 40px rgba(212, 175, 55, 0.1), inset 0 0 30px rgba(212, 175, 55, 0.05); 
            position: relative; 
            display: flex; 
            flex-direction: column; 
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
        }
        
        .hud-container::before, .hud-container::after { 
            content: ''; position: absolute; width: 40px; height: 40px; border: 2px solid var(--gold); border-radius: 8px; 
        }
        .hud-container::before { top: -2px; left: -2px; border-right: none; border-bottom: none; }
        .hud-container::after { bottom: -2px; right: -2px; border-left: none; border-top: none; }
        
        .panel { 
            background: var(--panel-bg); 
            border: 1px solid rgba(212, 175, 55, 0.2); 
            border-radius: 12px; 
            padding: 15px; 
            box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.5); 
            margin-bottom: 12px; 
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: all 0.3s ease;
        }
        .panel:hover { border-color: rgba(212, 175, 55, 0.5); }
        
        .panel-title { 
            color: var(--gold); 
            font-size: 0.9rem; 
            letter-spacing: 2px; 
            text-transform: uppercase; 
            border-bottom: 1px solid rgba(212, 175, 55, 0.3); 
            padding-bottom: 6px; 
            margin-bottom: 12px; 
            display: flex; 
            align-items: center; 
            text-shadow: 0 0 10px rgba(212, 175, 55, 0.3);
        }
        
        .status-row { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 8px; align-items: center;}
        
        .val-highlight { color: var(--gold-glow); font-weight: bold; }
        .text-green { color: var(--green); text-shadow: 0 0 8px rgba(0,255,102,0.5); } 
        .text-gold { color: var(--gold); text-shadow: 0 0 8px rgba(212,175,55,0.5); } 
        
        .video-container { 
            position: relative; width: 100%; height: 100%; 
            border: 1px solid rgba(212, 175, 55, 0.3); 
            border-radius: 8px; overflow: hidden; background: #000; 
            display: flex; align-items: center; justify-content: center; 
        }
        
        .reticle { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 140px; height: 140px; border: 1px solid rgba(212, 175, 55, 0.2); pointer-events: none; border-radius: 50%; }
        .reticle::before, .reticle::after { content: ''; position: absolute; width: 30px; height: 30px; border: 2px solid var(--gold); }
        .reticle::before { top: 0; left: 0; border-right: none; border-bottom: none; border-top-left-radius: 100%;}
        .reticle::after { bottom: 0; right: 0; border-left: none; border-top: none; border-bottom-right-radius: 100%;}
        
        .chat-box { height: 100%; overflow-y: auto; font-size: 0.85rem; display: flex; flex-direction: column; gap: 10px; padding-right: 5px; word-wrap: break-word;}
        .msg-sys { color: #888; font-style: italic; } 
        
        .cam-controls { display: flex; gap: 10px; margin-top: 15px; }
        .cam-controls input { flex: 1; background: rgba(0,0,0,0.5); border: 1px solid var(--dark-gold); color: var(--gold-glow); padding: 8px 12px; font-family: inherit; font-size: 0.8rem; border-radius: 6px;}
        .cam-controls input:focus { outline: none; border-color: var(--gold); box-shadow: 0 0 12px rgba(212, 175, 55, 0.3); }
        
        .input-group-cyber { display: flex; gap: 10px; margin-top: 15px; }
        .input-group-cyber input { flex: 1; background: rgba(0,0,0,0.5); border: 1px solid var(--dark-gold); color: #fff; padding: 10px 12px; font-family: inherit; font-size: 0.9rem; border-radius: 6px; }
        .input-group-cyber input:focus { outline: none; border-color: var(--gold); box-shadow: 0 0 12px rgba(212, 175, 55, 0.3); }
        
        .btn-cyber { 
            background: rgba(212, 175, 55, 0.05); 
            border: 1px solid var(--dark-gold); 
            color: var(--gold); 
            padding: 8px 18px; 
            font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: all 0.3s; 
            text-transform: uppercase; border-radius: 6px; letter-spacing: 1px;
        }
        .btn-cyber:hover { background: rgba(212, 175, 55, 0.2); box-shadow: 0 0 15px rgba(212, 175, 55, 0.4); border-color: var(--gold); color: #fff;}
        .btn-send { font-weight: bold; background: rgba(212, 175, 55, 0.1); }

        ::-webkit-scrollbar { width: 6px; } 
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.3); border-radius: 3px; } 
        ::-webkit-scrollbar-thumb { background: var(--dark-gold); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--gold); }
    </style>
</head>
<body>
<div class="hud-container">
    <div class="row h-100 m-0">
        <!-- LEFT COLUMN: STATUS & REAL TELEMETRY -->
        <div class="col-md-3 d-flex flex-column p-2">
            <div class="panel">
                <div class="panel-title">▤ HARDWARE TELEMETRY</div>
                <div class="status-row"><span>CPU LOAD:</span> <span id="stat-cpu" class="val-highlight">--%</span></div>
                <div class="status-row"><span>RAM USAGE:</span> <span id="stat-ram" class="val-highlight">--GB / --GB</span></div>
                <div class="status-row"><span>BATTERY:</span> <span id="stat-batt" class="val-highlight">--</span></div>
            </div>

            <div class="panel">
                <div class="panel-title">✦ NEXUS STATUS</div>
                <div class="status-row"><span>API:</span> <span class="text-green">[CONNECTED]</span></div>
                <div class="status-row"><span>VISION:</span> <span class="text-gold" id="vision-status">[STREAMING]</span></div>
                <div class="status-row"><span>AUDIO/TEXT:</span> <span class="text-gold">[LISTENING]</span></div>
            </div>

            <div class="panel flex-grow-1">
                <div class="panel-title">✧ SYSTEM CONFIG</div>
                <div class="status-row"><span>USER:</span> <span>SHASHANK GOWDA NB</span></div>
                <div class="status-row"><span>MODEL:</span> <span>GEMINI-3.1-FLASH</span></div>
                <div class="status-row"><span>RESOLUTION:</span> <span>MEDIUM</span></div>
            </div>
        </div>

        <!-- CENTER COLUMN: VIDEO & CAMERA CONTROLS -->
        <div class="col-md-6 d-flex flex-column p-2">
            <div class="panel d-flex flex-column" style="flex: 1;">
                <div class="panel-title">(•) NEXUS OPTICAL SENSOR</div>
                <div class="video-container flex-grow-1">
                    <img id="webcam" src="/video_feed" alt="Awaiting Video Stream..." style="width: 100%; height: 100%; object-fit: contain;">
                    <div class="reticle"></div>
                    <div style="position: absolute; top: 15px; left: 15px; font-size: 0.75rem; color: var(--gold); background: rgba(0,0,0,0.6); padding: 4px 8px; border-radius: 4px; border: 1px solid var(--dark-gold);">AI SYNC: ACTIVE</div>
                </div>
                
                <div class="cam-controls">
                    <button class="btn-cyber" onclick="switchCamera('0')">LOCAL CAM</button>
                    <input type="text" id="ipCamUrl" placeholder="Enter IP (e.g., http://10.41.231.31:8080)">
                    <button class="btn-cyber" onclick="connectIPCam()">LINK IP CAM</button>
                </div>
            </div>
        </div>

        <!-- RIGHT COLUMN: CHAT LOG & KEYBOARD INPUT -->
        <div class="col-md-3 d-flex flex-column p-2">
            <div class="panel flex-grow-1 d-flex flex-column">
                <div class="panel-title">🗨 NEXUS COMMLINK</div>
                
                <div class="chat-box" id="chatBox">
                    <div class="msg-sys">SYS_MSG: NEXUS SYSTEM INITIALIZED.</div>
                    <div class="msg-sys">SYS_MSG: WELCOME, SHASHANK.</div>
                    <div class="msg-sys">SYS_MSG: AWAITING AUDIO OR TEXT INPUT...</div>
                </div>
                
                <div class="input-group-cyber">
                    <input type="text" id="textInput" placeholder="Type message to Nexus..." autocomplete="off" onkeypress="handleEnter(event)">
                    <button class="btn-cyber btn-send" onclick="sendText()">SEND</button>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    setInterval(async () => {
        try {
            let res = await fetch('/stats');
            let data = await res.json();
            document.getElementById('stat-cpu').innerText = data.cpu + '%';
            document.getElementById('stat-ram').innerText = data.ram_used + 'GB / ' + data.ram_total + 'GB';
            document.getElementById('stat-batt').innerText = data.battery;
        } catch(e) { }

        try {
            let chatRes = await fetch('/get_chat');
            let chatData = await chatRes.json();
            if(chatData.text) {
                appendAiText(chatData.text);
            }
        } catch(e) {}
    }, 1000); 

    let currentAiSpan = null;
    let aiTextTimeout = null;

    function handleEnter(e) {
        if(e.key === 'Enter') sendText();
    }

    function sendText() {
        let inputField = document.getElementById('textInput');
        let val = inputField.value.trim();
        if(!val) return;
        
        logMsg(`<span class="text-main" style="color: #fff;"><strong>USER:</strong> ${val}</span>`);
        inputField.value = '';
        
        fetch('/send_message', { method: 'POST', body: val });
    }

    function appendAiText(text) {
        const cb = document.getElementById('chatBox');
        
        if(!currentAiSpan) {
            let div = document.createElement('div');
            div.innerHTML = `<strong style="color: var(--gold-glow);">NEXUS:</strong> <span class="ai-text-stream" style="color: #ccc;"></span>`;
            cb.appendChild(div);
            currentAiSpan = div.querySelector('.ai-text-stream');
        }
        
        currentAiSpan.innerText += text;
        cb.scrollTop = cb.scrollHeight;
        
        clearTimeout(aiTextTimeout);
        aiTextTimeout = setTimeout(() => { currentAiSpan = null; }, 3000);
    }

    function logMsg(html) {
        const cb = document.getElementById('chatBox');
        cb.innerHTML += `<div>${html}</div>`;
        cb.scrollTop = cb.scrollHeight;
    }

    function switchCamera(src) {
        document.getElementById('vision-status').innerText = '[RECALIBRATING]';
        document.getElementById('vision-status').className = 'text-main';
        
        const img = document.getElementById('webcam');
        img.src = ''; 
        
        fetch('/set_camera?src=' + encodeURIComponent(src))
            .then(() => {
                setTimeout(() => {
                    img.src = '/video_feed?' + new Date().getTime(); 
                    document.getElementById('vision-status').innerText = '[STREAMING]';
                    document.getElementById('vision-status').className = 'text-gold';
                    logMsg(`<span class="msg-sys">SYS_MSG: OPTICAL SENSOR ROUTING UPDATED.</span>`);
                }, 1500);
            });
    }

    function connectIPCam() {
        let url = document.getElementById('ipCamUrl').value.trim();
        if(url) {
            if (!url.endsWith('/video') && !url.endsWith('/shot.jpg')) {
                if (!url.endsWith('/')) url += '/';
                url += 'video';
            }
            document.getElementById('ipCamUrl').value = url;
            switchCamera(url);
        } else {
            alert("Please enter a valid IP Camera URL.");
        }
    }
</script>
</body>
</html>
"""

# =====================================================================
# LOCAL WEB SERVER & API HANDLER
# =====================================================================
class WebDashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode('utf-8'))
            
        elif parsed_path.path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                while True:
                    global LATEST_JPEG
                    if LATEST_JPEG:
                        self.wfile.write(b'--frame\r\n')
                        self.send_header('Content-type', 'image/jpeg')
                        self.send_header('Content-length', str(len(LATEST_JPEG)))
                        self.end_headers()
                        self.wfile.write(LATEST_JPEG)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.033) 
            except Exception:
                pass 
                
        elif parsed_path.path == '/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(get_hardware_stats().encode('utf-8'))
            
        elif parsed_path.path == '/get_chat':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            if AI_CHAT_QUEUE:
                msg = "".join(AI_CHAT_QUEUE)
                AI_CHAT_QUEUE.clear()
                self.wfile.write(json.dumps({"text": msg}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"text": ""}).encode('utf-8'))
            
        elif parsed_path.path == '/set_camera':
            global TARGET_CAM_SOURCE
            qs = urllib.parse.parse_qs(parsed_path.query)
            if 'src' in qs:
                TARGET_CAM_SOURCE = qs['src'][0]
            self.send_response(200)
            self.end_headers()
            
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/send_message':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            if post_data.strip():
                TEXT_PROMPT_QUEUE.append(post_data.strip())
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass 

def start_web_server():
    PORT = 8080
    class ReusableTCPServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
    httpd = ReusableTCPServer(("127.0.0.1", PORT), WebDashboardHandler)
    httpd.serve_forever()

# =====================================================================
# CORE AI AUDIO/VIDEO/TEXT LOOP
# =====================================================================
class AudioLoop:
    def __init__(self):
        self.audio_in_queue = None
        self.out_queue = None
        self.session = None
        self.audio_stream = None

    async def send_text_realtime(self):
        """Pulls typed messages from the UI and puts them safely into the main stream queue."""
        while True:
            if TEXT_PROMPT_QUEUE:
                msg = TEXT_PROMPT_QUEUE.pop(0)
                if self.session is not None and self.out_queue is not None:
                    # Place text in the same queue as audio/video to prevent WebSocket collisions
                    await self.out_queue.put({"mime_type": "text/plain", "data": msg})
            await asyncio.sleep(0.1)

    async def get_frames(self):
        global LATEST_JPEG
        global TARGET_CAM_SOURCE
        
        current_source = TARGET_CAM_SOURCE
        source_val = int(current_source) if str(current_source).isdigit() else current_source
        
        if isinstance(source_val, int):
            cap = await asyncio.to_thread(cv2.VideoCapture, source_val, cv2.CAP_DSHOW)
        else:
            cap = await asyncio.to_thread(cv2.VideoCapture, source_val)

        last_ai_send_time = 0
        AI_SEND_INTERVAL = 1.0 

        while True:
            if current_source != TARGET_CAM_SOURCE:
                cap.release()
                LATEST_JPEG = b"" 
                
                current_source = TARGET_CAM_SOURCE
                source_val = int(current_source) if str(current_source).isdigit() else current_source
                
                if isinstance(source_val, int):
                    cap = await asyncio.to_thread(cv2.VideoCapture, source_val, cv2.CAP_DSHOW)
                else:
                    cap = await asyncio.to_thread(cv2.VideoCapture, source_val)
                    
                await asyncio.sleep(0.5) 
                continue

            if cap.isOpened():
                ret, frame = await asyncio.to_thread(cap.read)
                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = PIL.Image.fromarray(frame_rgb)
                    img.thumbnail([640, 480])

                    image_io = io.BytesIO()
                    img.save(image_io, format="jpeg")
                    image_bytes = image_io.getvalue()
                    
                    LATEST_JPEG = image_bytes 
                    
                    current_time = time.time()
                    if current_time - last_ai_send_time >= AI_SEND_INTERVAL:
                        if self.out_queue is not None:
                            await self.out_queue.put({"mime_type": "image/jpeg", "data": image_bytes})
                        last_ai_send_time = current_time

            await asyncio.sleep(0.01)

        cap.release()

    async def send_realtime(self):
        """Safely streams Audio, Video, and Text sequentially to the AI."""
        while True:
            if self.out_queue is not None:
                msg = await self.out_queue.get()
                if self.session is not None:
                    mime = msg.get("mime_type", "")
                    
                    # 1. Handle Keyboard Text Safely
                    if mime == "text/plain":
                        text_data = msg.get("data")
                        print(f"\n[KEYBOARD] Sent to NEXUS: {text_data}")
                        # Force the AI to pay attention to the text over the audio stream
                        forceful_prompt = f"The user just typed this message on their keyboard: '{text_data}'. Please reply to this message immediately out loud."
                        await self.session.send_realtime_input(text=forceful_prompt)
                        
                    # 2. Handle Audio and Video
                    else:
                        blob = types.Blob(mime_type=mime, data=msg.get("data"))
                        if "audio" in mime:
                            await self.session.send_realtime_input(audio=blob)
                        elif "image" in mime:
                            await self.session.send_realtime_input(video=blob)

    async def listen_audio(self):
        mic_info = pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            pya.open, format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
            input=True, input_device_index=mic_info["index"], frames_per_buffer=CHUNK_SIZE,
        )
        kwargs = {"exception_on_overflow": False} if __debug__ else {}
        while True:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)
            if self.out_queue is not None:
                await self.out_queue.put({"data": data, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"})

    async def receive_audio(self):
        while True:
            if self.session is not None:
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)
                        continue
                    if text := response.text:
                        print(text, end="", flush=True)
                        AI_CHAT_QUEUE.append(text)

                while not self.audio_in_queue.empty():
                    self.audio_in_queue.get_nowait()

    async def play_audio(self):
        stream = await asyncio.to_thread(
            pya.open, format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True,
        )
        while True:
            if self.audio_in_queue is not None:
                bytestream = await self.audio_in_queue.get()
                await asyncio.to_thread(stream.write, bytestream)

    async def run(self):
        try:
            async with (
                client.aio.live.connect(model=MODEL, config=CONFIG) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session = session
                self.audio_in_queue = asyncio.Queue()
                self.out_queue = asyncio.Queue(maxsize=5)

                tg.create_task(self.send_text_realtime()) 
                tg.create_task(self.send_realtime())
                tg.create_task(self.listen_audio())
                tg.create_task(self.get_frames())
                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())

                while True:
                    await asyncio.sleep(3600)

        except asyncio.CancelledError:
            pass
        except ExceptionGroup as EG:
            if self.audio_stream is not None:
                self.audio_stream.close()
            traceback.print_exception(EG)

if __name__ == "__main__":
    print("[NEXUS] Booting Local Server...")
    server_thread = threading.Thread(target=start_web_server, daemon=True)
    server_thread.start()
    
    time.sleep(0.5)
    webbrowser.open("http://127.0.0.1:8080")
    
    print("[NEXUS] Establishing Commlink...")
    
    main = AudioLoop()
    asyncio.run(main.run())