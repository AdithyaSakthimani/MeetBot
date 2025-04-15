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
#from DiarizationFile import DiarizationHelper
import torch
load_dotenv()

ssl._create_default_https_context = ssl._create_unverified_context
WEBSOCKET_SERVER_URL = os.getenv("WEBSOCKET_SERVER_URL")
AWS_EC2_URL = os.getenv("AWS_EC2_URL")

class AudioTranscriber():
    def __init__(self):
        self.p = pyaudio.PyAudio()
        super().__init__()
        self.stream = None
        self.recording = False
        self.transcript_text = ""
        self.chunk_duration = 4  # seconds
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
        
        # # Load the Whisper model (using tiny.en for faster performance)
        # try:
        #     print("Loading Whisper model (tiny.en)...")
        #     self.whisper_model = whisper.load_model("small.en", device="cpu")
        #     self.whisper_model = self.whisper_model.to(dtype=torch.float32)

        # except Exception as e:
        #     print(f"Error loading Whisper model: {e}")
        #     self.whisper_model = None
            
        # Create a WebSocket connection to the Node.js backend
        try:
            print(f"Connecting to WebSocket server at {WEBSOCKET_SERVER_URL} ...")
            self.ws = websocket.create_connection(WEBSOCKET_SERVER_URL)
            print("WebSocket connection established.")
        except Exception as e:
            print(f"Failed to connect to WebSocket server: {e}")
            self.ws = None
    # def _get_action_item(self, text  ):
    #     URL = os.getenv("ACTION_URL")
    #     response = requests.post(URL,json={"transcription": text, "trigger" : "manual"})
    #     return response.json()
    # def _send_transcription_s3(self,text):
    #     URL = os.getenv("S3_URL")
    #     try:
    #         response = requests.post(URL,json={"text": text})
    #         print("data sent successfully")
    #         print(response)
    #     except:
    #         print("error cannot send data to s3")
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
                print(f"Transcript for chunk {chunk_index} sent to WebSocket server")
            except Exception as e:
                print(f"❌ Failed to send transcript over WebSocket: {e}")
        else:
            print("WebSocket connection not available.")

    def _transcribe_and_diarize_chunk(self, chunk_data, chunk_index):
        try:
            temp_file = f"chunk_{chunk_index}.pcm"
            wav_file = f"chunk_{chunk_index}.wav"

            # Save audio chunk as PCM data
            with open(temp_file, "wb") as f:
                f.write(chunk_data)

            # Convert PCM to WAV using correct ffmpeg parameter names
            # 'ac' for audio channels and 'ar' for audio rate
            ffmpeg.input(
                temp_file, 
                format='s16le',  # PCM format
                ac=self.CHANNEL_NUMS,  # Use 'ac' instead of 'channels'
                ar=self.SAMPLE_RATE    # Use 'ar' instead of 'rate'
            ).output(wav_file).run(overwrite_output=True, quiet=True)  # Added 'quiet=True' to reduce output

            # Send to cloud API
            print(f"Sending chunk {chunk_index} to EC2 server for processing...")
            files = {"file": open(wav_file, "rb")}
            response = requests.post(f"{AWS_EC2_URL}/transcribe", files=files)
            
            if response.status_code == 200:
                
                result = response.json()
                transcription = result.get("transcription", "")
                
                # Store transcript for final output
                if transcription:
                    self.transcript_text += " " + transcription
                
                # Send the transcript to your WebSocket
                self._send_transcript(transcription, chunk_index)
                
                # Log diarization results if available
                diarization = result.get("diarization", [])
                if diarization:
                    print("Diarization results:")
                    for entry in diarization:
                        print(entry)
                
                # Log action items if available
                actions = result.get("actions", {})
                if actions:
                    print("Action items detected:")
                    print(actions)
            else:
                print(f"Transcription failed: {response.text}")

            # Clean up temporary files
            os.remove(temp_file)
            os.remove(wav_file)

        except Exception as e:
            import traceback
            print(f"Error in remote transcription: {e}")
            print(traceback.format_exc())  # Print the full traceback for better debugging
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
            
            # You could send the full recording to the EC2 server for final processing if desired
            # But that's optional
        
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