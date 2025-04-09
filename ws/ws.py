import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import ssl
import os
import pyaudio
import threading
from datetime import datetime
from dotenv import load_dotenv
import whisper
import ffmpeg
import websocket  # import the websocket client

ssl._create_default_https_context = ssl._create_unverified_context
WEBSOCKET_SERVER_URL = "ws://localhost:3000"

class AudioTranscriber:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.recording = False
        self.transcript_text = ""
        
        # AWS credentials placeholder (not used here)
        self.aws_access_key = os.getenv("AWS_ID")
        self.aws_secret_key = os.getenv("AWS_SECRET")
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        
        self.SAMPLE_RATE = 16000
        self.BYTES_PER_SAMPLE = 2
        self.CHANNEL_NUMS = 1
        
        # Create output directory for recordings
        self.output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recordings')
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        # Generate a session ID and set file paths for full recordings
        self.session_id = f"session-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}-{random.randint(1000, 9999)}"
        self.pcm_file_path = os.path.join(self.output_dir, f"{self.session_id}.pcm")
        self.filestream = open(self.pcm_file_path, 'wb')
        
        # Load the Whisper model (using tiny.en for faster performance)
        try:
            print("Loading Whisper model (tiny.en)...")
            self.whisper_model = whisper.load_model("tiny.en")
        except Exception as e:
            print(f"Error loading Whisper model: {e}")
            self.whisper_model = None

        # Create a WebSocket connection to the Node.js backend
        try:
            print(f"Connecting to WebSocket server at {WEBSOCKET_SERVER_URL} ...")
            self.ws = websocket.create_connection(WEBSOCKET_SERVER_URL)
            print("WebSocket connection established.")
        except Exception as e:
            print(f"Failed to connect to WebSocket server: {e}")
            self.ws = None

    def _transcribe_chunk(self, chunk_data, index):
        """
        Save a PCM chunk to file, convert it to WAV, transcribe it using Whisper,
        and send the transcription result over the WebSocket connection.
        """
        chunk_pcm_path = os.path.join(self.output_dir, f"{self.session_id}_chunk_{index}.pcm")
        chunk_wav_path = chunk_pcm_path.replace(".pcm", ".wav")

        # Save the PCM chunk
        with open(chunk_pcm_path, 'wb') as f:
            f.write(chunk_data)

        # Convert PCM to WAV using ffmpeg
        try:
            ffmpeg.input(chunk_pcm_path, f='s16le', ac=1, ar=self.SAMPLE_RATE)\
                  .output(chunk_wav_path).run(quiet=True, overwrite_output=True)
        except Exception as e:
            print(f"❌ Error converting chunk {index} to WAV: {e}")
            return

        # Transcribe with Whisper
        if not self.whisper_model:
            print("Whisper model not loaded; cannot transcribe chunk.")
            return
        try:
            result = self.whisper_model.transcribe(chunk_wav_path)
            transcript = result['text'].strip()
            print(f"🗣 [Live] Chunk {index} Transcript:\n{transcript}\n")
            self.transcript_text += transcript + " "
            self._send_transcript(transcript, index)
        except Exception as e:
            print(f"❌ Error in Whisper transcription for chunk {index}: {e}")

    def _send_transcript(self, transcript, chunk_index):
        """
        Send the transcription text for this chunk to the WebSocket server.
        """
        if self.ws:
            payload = {
                "session_id": self.session_id,
                "chunk": chunk_index,
                "transcript": transcript,
                "timestamp": datetime.now().isoformat()
            }
            try:
                self.ws.send(str(payload))
            except Exception as e:
                print(f"❌ Failed to send transcript over WebSocket: {e}")
        else:
            print("WebSocket connection not available.")

    def start_streaming(self):
        """Start audio streaming and live transcription."""
        self.recording = True
        
        try:
            print("\nAvailable audio input devices:")
            for i in range(self.p.get_device_count()):
                dev_info = self.p.get_device_info_by_index(i)
                if dev_info['maxInputChannels'] > 0:
                    print(f"Device {i}: {dev_info['name']}")
                    
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.SAMPLE_RATE,
                input=True,
                frames_per_buffer=1024
            )
            
            # Start the recording thread
            threading.Thread(target=self._record, daemon=True).start()
            print("Audio streaming and live transcription started")
            
        except Exception as e:
            print(f"Error setting up audio stream: {e}")
            self.recording = False

    def _record(self):
        """Capture audio data in ~5-second chunks for live transcription."""
        buffer = bytearray()
        chunk_index = 0
        start_time = time.time()

        while self.recording:
            try:
                data = self.stream.read(1024, exception_on_overflow=False)
                buffer.extend(data)
                self.filestream.write(data)

                if time.time() - start_time >= 5:
                    chunk_data = bytes(buffer)
                    threading.Thread(
                        target=self._transcribe_chunk,
                        args=(chunk_data, chunk_index),
                        daemon=True
                    ).start()
                    chunk_index += 1
                    buffer.clear()
                    start_time = time.time()

            except Exception as e:
                print(f"❌ Error reading audio: {e}")
                time.sleep(0.1)

    def stop_streaming(self):
        """Stop streaming and clean up resources."""
        print("Stopping audio streaming and transcription...")
        self.recording = False
        time.sleep(1)
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            print("Audio stream closed")

        if self.filestream:
            self.filestream.close()
            print(f"PCM recording saved to {self.pcm_file_path}")

        if self.p:
            self.p.terminate()
            print("PyAudio terminated")
        
        if self.ws:
            try:
                self.ws.close()
                print("WebSocket connection closed.")
            except Exception as e:
                print(f"❌ Error closing WebSocket connection: {e}")

        print("Final transcript:")
        print(self.transcript_text)

def human_delay(min_time=2, max_time=5):
    time.sleep(random.uniform(min_time, max_time))

def join_and_stream_meet(meet_link):
    audio_transcriber = AudioTranscriber()
    audio_transcriber.start_streaming()
    
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--use-fake-ui-for-media-stream")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-notifications")

    driver = None  
    try:
        driver = uc.Chrome(options=chrome_options, version_main=134)
        driver.get(meet_link)
        human_delay(5, 10)

        name_inputs = [
            '//input[@aria-label="Your name"]',
            '//input[@placeholder="Enter your name"]',
            '//input[contains(@class, "name-input")]'
        ]
        name_input = None
        for xpath in name_inputs:
            try:
                name_input = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
                if name_input:
                    break
            except:
                continue
        
        if name_input:
            guest_name = "Guest" + str(random.randint(100, 999))
            name_input.clear()
            name_input.send_keys(guest_name)
            human_delay(2, 4)
            print(f"Name entered: {guest_name}")
        else:
            print("⚠ Could not find name input field")
        
        join_buttons = [
            "//span[contains(text(), 'Ask to join')]",
            "//span[contains(text(), 'Join')]",
            "//button[contains(@aria-label, 'Join')]",
            "//div[contains(text(), 'Ask to join')]"
        ]
        join_btn = None
        for button_xpath in join_buttons:
            try:
                join_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, button_xpath))
                )
                if join_btn:
                    join_btn.click()
                    break
            except:
                continue
        
        if join_btn:
            human_delay(4, 7)
            print("✅ Joined the Google Meet")
            try:
                print("\nStreaming audio from Google Meet...\nPress Enter to stop streaming and exit...")
                input()
            except KeyboardInterrupt:
                print("\nKeyboard interrupt detected, stopping...")
        else:
            print("⚠ Could not find a join button")
    
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    
    finally:
        if audio_transcriber:
            audio_transcriber.stop_streaming()       
        if driver:
            driver.quit()

if __name__ == "__main__":
    MEET_LINK = "https://meet.google.com/owt-ubst-scr"
    join_and_stream_meet(MEET_LINK)
