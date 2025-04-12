import time
import ssl
import os
import random
import pyaudio
import threading
from datetime import datetime
from dotenv import load_dotenv
import whisper
import websocket
import ffmpeg
import asyncio
import requests
from DiarizationFile import DiarizationHelper
load_dotenv()

ssl._create_default_https_context = ssl._create_unverified_context
WEBSOCKET_SERVER_URL = os.getenv("WEBSOCKET_SERVER_URL")

class AudioTranscriber(DiarizationHelper):
    def __init__(self):
        self.p = pyaudio.PyAudio()
        super().__init__()
        self.stream = None
        self.recording = False
        self.transcript_text = ""
        self.chunk_duration = 2  # seconds
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
    def _get_action_item(self, text  ):
        URL = os.getenv("ACTION_URL")
        response = requests.post(URL,json={"transcription": text, "trigger" : "manual"})
        return response.json()
    def _send_transcription_s3(self,text):
        URL = os.getenv("S3_URL")
        try:
            response = requests.post(URL,json={"text": text})
            print("data sent successfully")
            print(response)
        except:
            print("error cannot send data to s3")
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
                actionText = self._get_action_item(transcript)
                self._send_transcription_s3(transcript)
                print("action Text is : ")
                print(actionText)
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
        """Capture audio data in chunks for live transcription and diarization."""
        buffer = bytearray()
        chunk_index = 0
        start_time = time.time()

        while self.recording:
            try:
                data = self.stream.read(1024, exception_on_overflow=False)
                buffer.extend(data)
                self.filestream.write(data)

                if time.time() - start_time >= self.chunk_duration:
                    chunk_data = bytes(buffer)
                    threading.Thread(
                        target=self._transcribe_and_diarize_chunk,
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
            
            # Process the full recording for better diarization results
            if self.diarization_pipeline and os.path.exists(self.pcm_file_path):
                try:
                    print("Performing full diarization on the complete recording...")
                    full_wav_path = self.pcm_file_path.replace(".pcm", ".wav")
                    
                    # Convert full PCM to WAV
                    ffmpeg.input(self.pcm_file_path, f='s16le', ac=1, ar=self.SAMPLE_RATE)\
                          .output(full_wav_path).run(quiet=True, overwrite_output=True)
                          
                    # Process the full recording for a more accurate diarization
                    diarization = self.diarization_pipeline(full_wav_path)
                    
                    # Save diarization results
                    diarization_output = os.path.join(self.output_dir, f"{self.session_id}-diarization.txt")
                    with open(diarization_output, "w") as f:
                        for turn, _, speaker in diarization.itertracks(yield_label=True):
                            f.write(f"[{turn.start:.2f} → {turn.end:.2f}] {speaker}\n")
                    
                    print(f"Full diarization saved to {diarization_output}")
                    
                except Exception as e:
                    print(f"❌ Error in full recording diarization: {e}")

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
    
