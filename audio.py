import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import ssl
import os
import pyaudio
import wave
import threading
import websocket
import json
import base64

ssl._create_default_https_context = ssl._create_unverified_context

class AudioRecorder:
    def __init__(self, output_filename):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.recording = False
        self.output_filename = output_filename

    def start_recording(self):
        self.recording = True
        self.frames = []
        
        self.stream = self.p.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=44100,
                                  input=True,
                                  frames_per_buffer=1024)
        
        threading.Thread(target=self._record, daemon=True).start()

    def _record(self):
        while self.recording:
            data = self.stream.read(1024)
            self.frames.append(data)

    def stop_recording(self):
        self.recording = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        
        wf = wave.open(self.output_filename, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b''.join(self.frames))
        wf.close()

        print(f"Audio saved to {self.output_filename}")

class AudioWebSocketClient:
    def __init__(self, server_url):
        self.server_url = server_url
        self.ws = None
        self.is_connected = False
        self.send_thread = None
        self.should_send = False
        
        # Audio settings
        self.chunk_size = 1024
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        self.rate = 44100
        self.p = pyaudio.PyAudio()
        
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            print(f"Received message: {data}")
        except Exception as e:
            print(f"Error processing message: {e}")
    
    def on_error(self, ws, error):
        print(f"WebSocket error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        self.is_connected = False
        print("WebSocket connection closed")
    
    def on_open(self, ws):
        self.is_connected = True
        print("WebSocket connection established")
    
    def connect(self):
        websocket.enableTrace(True)
        self.ws = websocket.WebSocketApp(
            self.server_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # Start the WebSocket connection in a separate thread
        threading.Thread(target=self.ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}}, daemon=True).start()
        
        # Wait for connection to establish
        timeout = 10
        start_time = time.time()
        while not self.is_connected and time.time() - start_time < timeout:
            time.sleep(0.1)
            
        if not self.is_connected:
            print("Failed to connect to WebSocket server")
            return False
            
        return True
    
    def disconnect(self):
        if self.ws:
            self.stop_sending_audio()
            self.ws.close()
    
    def send_audio_file(self, filename):
        """Send an audio file to the WebSocket server"""
        if not self.is_connected:
            print("Not connected to WebSocket server")
            return False
            
        try:
            # Open the WAV file
            with wave.open(filename, 'rb') as wf:
                # Read file in chunks
                data = wf.readframes(self.chunk_size)
                while len(data) > 0:
                    # Encode audio data as base64
                    encoded_data = base64.b64encode(data).decode('utf-8')
                    
                    # Create message payload
                    message = {
                        "type": "audio_data",
                        "data": encoded_data,
                        "format": "wav",
                        "channels": wf.getnchannels(),
                        "sample_rate": wf.getframerate(),
                        "sample_width": wf.getsampwidth()
                    }
                    
                    # Send data
                    self.ws.send(json.dumps(message))
                    
                    # Read next chunk
                    data = wf.readframes(self.chunk_size)
                    time.sleep(0.01)  # Small delay to avoid flooding
                
            return True
        except Exception as e:
            print(f"Error sending audio file: {e}")
            return False
    
    def start_sending_live_audio(self):
        """Start streaming live audio to the WebSocket server"""
        if not self.is_connected:
            print("Not connected to WebSocket server")
            return False
            
        if self.send_thread and self.send_thread.is_alive():
            print("Already sending audio")
            return False
            
        self.should_send = True
        self.send_thread = threading.Thread(target=self._stream_audio, daemon=True)
        self.send_thread.start()
        return True
    
    def stop_sending_audio(self):
        """Stop streaming audio"""
        self.should_send = False
        if self.send_thread:
            self.send_thread.join(timeout=2)
    
    def _stream_audio(self):
        """Internal method to stream audio data"""
        try:
            # Open audio stream
            stream = self.p.open(
                format=self.audio_format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            print("Started streaming audio")
            
            # Stream audio data
            while self.should_send and self.is_connected:
                # Read audio data
                data = stream.read(self.chunk_size)
                
                # Encode audio data as base64
                encoded_data = base64.b64encode(data).decode('utf-8')
                
                # Create message payload
                message = {
                    "type": "live_audio",
                    "data": encoded_data,
                    "format": "raw",
                    "channels": self.channels,
                    "sample_rate": self.rate,
                    "sample_width": self.p.get_sample_size(self.audio_format)
                }
                
                # Send data
                self.ws.send(json.dumps(message))
            
            # Close stream
            stream.stop_stream()
            stream.close()
            print("Stopped streaming audio")
            
        except Exception as e:
            print(f"Error streaming audio: {e}")

def human_delay(min_time=2, max_time=5):
    time.sleep(random.uniform(min_time, max_time))

def join_and_record_meet(meet_link, websocket_url, stream_live=False):
    """
    Join a Google Meet session, record audio, and send to WebSocket server
    
    Parameters:
    meet_link (str): The Google Meet URL to join
    websocket_url (str): WebSocket server URL to send audio data
    stream_live (bool): Whether to stream audio live or send after recording
    """
    # Create output directory
    output_dir = "meet_recordings"
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate output filename with timestamp
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_filename = os.path.join(output_dir, f"meet_recording_{timestamp}.wav")

    # Initialize audio recorder
    audio_recorder = AudioRecorder(output_filename)
    
    # Initialize WebSocket client
    ws_client = None
    if stream_live:
        ws_client = AudioWebSocketClient(websocket_url)
        if not ws_client.connect():
            print("Failed to connect to WebSocket server, continuing without streaming")
            ws_client = None

    # Configure Chrome options
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--use-fake-ui-for-media-stream")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-notifications")

    driver = None
    
    try:
        # Initialize Chrome driver
        driver = uc.Chrome(options=chrome_options, version_main=134)
        
        # Navigate to meeting
        driver.get(meet_link)
        human_delay(5, 10)

        # Handle name input
        try:
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
        except Exception as name_error:
            print(f"Name input error: {name_error}")

        # Join button handling
        try:
            # Try multiple potential join button locators
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
                
                # Start audio recording
                audio_recorder.start_recording()
                
                # Start WebSocket streaming if enabled
                if stream_live and ws_client:
                    ws_client.start_sending_live_audio()
                
                # Keep the meeting open for 10 minutes
                time.sleep(600)
                
                # Stop recording and streaming
                audio_recorder.stop_recording()
                if stream_live and ws_client:
                    ws_client.stop_sending_audio()
                    ws_client.disconnect()
                
                # If not streaming live, send the recorded file
                if not stream_live:
                    print(f"Sending recorded audio file to WebSocket server")
                    send_recorded_audio_to_server(output_filename, websocket_url)
            else:
                print("⚠ Could not find a join button")
        
        except Exception as join_error:
            print(f"Join button error: {join_error}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    
    finally:
        # Clean up
        if ws_client:
            ws_client.disconnect()
        
        if driver:
            driver.quit()

def send_recorded_audio_to_server(recording_path, websocket_url):
    """Send a recorded audio file to the WebSocket server"""
    client = AudioWebSocketClient(websocket_url)
    
    if client.connect():
        print(f"Sending audio file: {recording_path}")
        success = client.send_audio_file(recording_path)
        if success:
            print("Finished sending audio file")
        else:
            print("Failed to send audio file")
        client.disconnect()
    else:
        print("Failed to connect to WebSocket server")

# Configuration
MEET_LINK = "https://meet.google.com/ydv-osya-xgf"
WS_SERVER_URL = "ws://localhost:8765/"
STREAM_LIVE = False  

if __name__ == "__main__":
    join_and_record_meet(MEET_LINK, WS_SERVER_URL, STREAM_LIVE)