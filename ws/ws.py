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
import queue
import base64

ssl._create_default_https_context = ssl._create_unverified_context

class AudioStreamer:
    def __init__(self, websocket_url):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.recording = False
        self.websocket_url = websocket_url
        self.ws = None
        self.audio_queue = queue.Queue()
        self.connected = False
        self.ws_lock = threading.Lock()
        self.audio_sequence = 0
        self.init_sent = False  # Track if init message was sent

    def connect_websocket(self):
        try:
            # Disable trace for production (less noisy logs)
            websocket.enableTrace(False)
            
            self.ws = websocket.WebSocketApp(
                self.websocket_url,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            # Start WebSocket connection in a separate thread
            threading.Thread(target=self.ws.run_forever, kwargs={'ping_interval': 30}, daemon=True).start()
            print(f"Connecting to WebSocket server at {self.websocket_url}...")
            
            # Wait for the connection to be established
            timeout = 15
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
            
            if not self.connected:
                print("Failed to connect to WebSocket server within timeout")
                return False
                
            return True
        except Exception as e:
            print(f"WebSocket connection error: {e}")
            return False

    def on_open(self, ws):
        print("WebSocket connection established")
        self.connected = True
        
        # Send initial handshake message
        init_message = {
            "event": "init",
            "client_type": "audio_streamer",
            "format": "audio/pcm",
            "sample_rate": 16000,
            "channels": 1
        }
        with self.ws_lock:
            # Important: Send as text, not binary
            ws.send(json.dumps(init_message))
            self.init_sent = True
            print("Sent initialization message")
            
        # Wait a moment before sending audio data
        time.sleep(0.5)
            
        # Start sender thread to handle the queue
        threading.Thread(target=self.send_audio_data, daemon=True).start()

    def on_message(self, ws, message):
        try:
            # Parse message as JSON if possible
            msg_data = json.loads(message)
            print(f"Received from server: {msg_data}")
            
            # Check for acknowledgment of init message
            if msg_data.get('status') == 'connected':
                print(f"Connection confirmed with session ID: {msg_data.get('sessionId')}")
        except:
            # Not JSON, print as is (truncated)
            print(f"Received from server: {message[:100]}...")

    def on_error(self, ws, error):
        print(f"WebSocket error: {error}")
        self.connected = False

    def on_close(self, ws, close_status_code, close_msg):
        print(f"WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False

    def start_streaming(self):
        if not self.connect_websocket():
            print("Cannot start streaming - WebSocket connection failed")
            return
            
        self.recording = True
        
        # Configure audio stream
        try:
            # List available input devices first
            print("\nAvailable audio input devices:")
            for i in range(self.p.get_device_count()):
                dev_info = self.p.get_device_info_by_index(i)
                if dev_info['maxInputChannels'] > 0:  # if it has input channels
                    print(f"Device {i}: {dev_info['name']}")
                    
            # Configure audio stream
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,  # Using 16kHz which is common for speech recognition
                input=True,
                frames_per_buffer=1024
            )
            
            # Start recording thread
            threading.Thread(target=self._record, daemon=True).start()
            print("Audio streaming started")
            
        except Exception as e:
            print(f"Error setting up audio stream: {e}")
            self.recording = False

    def _record(self):
        """Capture audio data and add to queue"""
        data_captured = 0
        zero_chunks = 0
        total_chunks = 0
        buffer_size = 4096  # Increased buffer size
        
        while self.recording:
            try:
                # Read larger chunks for efficiency
                data = self.stream.read(buffer_size, exception_on_overflow=False)
                total_chunks += 1
                
                # Check if this is silent/zero audio
                is_silent = all(b == 0 for b in data[:100])  # Check first 100 bytes
                if is_silent:
                    zero_chunks += 1
                
                if not data or len(data) == 0:
                    print("Warning: Empty audio chunk received")
                    continue
                    
                data_captured += len(data)
                
                # Log audio statistics
                if data_captured % 32000 == 0:  # Every 2 seconds
                    print(f"Audio captured: {data_captured / 1024:.1f}KB (Silence: {zero_chunks}/{total_chunks} chunks)")
                    
                self.audio_queue.put(data)
            except Exception as e:
                print(f"Error reading audio: {e}")
                time.sleep(0.1)

    def send_audio_data(self):
        """Send audio data from queue to WebSocket server"""
        data_sent = 0
        last_log_time = time.time()
        
        # Wait until init message is confirmed sent
        while not self.init_sent and self.recording:
            time.sleep(0.1)
        
        # Small delay to ensure server processes init message
        time.sleep(0.5)
        
        while self.recording or not self.audio_queue.empty():
            if not self.connected:
                print("WebSocket disconnected, cannot send audio")
                time.sleep(1)
                continue
                
            try:
                if not self.audio_queue.empty():
                    audio_chunk = self.audio_queue.get()
                    data_sent += len(audio_chunk)
                    
                    # Log progress every second rather than every packet
                    current_time = time.time()
                    if current_time - last_log_time >= 1.0:
                        print(f"Sending audio data: {data_sent / 1024:.1f}KB sent so far")
                        last_log_time = current_time
                    
                    with self.ws_lock:
                        if self.connected and self.ws and self.ws.sock:
                            # Important: Create audio data packet with an event
                            # This makes it explicit that we're sending binary audio data
                            audio_packet = {
                                "event": "audio_data",
                                "sequence": self.audio_sequence,
                                "format": "audio/pcm",
                                "data": base64.b64encode(audio_chunk).decode('utf-8')
                            }
                            self.audio_sequence += 1
                            
                            # Send as text, not binary
                            self.ws.send(json.dumps(audio_packet))
                        else:
                            print("WebSocket not available for sending")
                            
                else:
                    time.sleep(0.01)  # Small delay when queue is empty
            except websocket.WebSocketConnectionClosedException:
                print("WebSocket connection closed while sending data")
                break
            except Exception as e:
                print(f"Error sending audio data: {e}")
                time.sleep(0.1)  # Wait before retry

    def stop_streaming(self):
        print("Stopping audio streaming...")
        self.recording = False
        
        # Make sure audio queue is empty before closing
        while not self.audio_queue.empty():
            time.sleep(0.1)
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            print("Audio stream closed")
            
        # Close WebSocket connection gracefully
        with self.ws_lock:
            if self.ws and self.connected:
                try:
                    # Send a closing message
                    close_msg = {"event": "stop", "message": "Streaming stopped"}
                    self.ws.send(json.dumps(close_msg))
                    print("Sent stop message to server")
                    time.sleep(1.0)  # Give server more time to process
                    self.ws.close()
                    print("WebSocket closed")
                except Exception as e:
                    print(f"Error closing WebSocket: {e}")
        
        # Clean up PyAudio
        if self.p:
            self.p.terminate()
            print("PyAudio terminated")

def human_delay(min_time=2, max_time=5):
    time.sleep(random.uniform(min_time, max_time))

def join_and_stream_meet(meet_link, websocket_url):
    # Create audio streamer
    audio_streamer = AudioStreamer(websocket_url)

    # Use undetected_chromedriver's native ChromeOptions
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
                
                # Start audio streaming
                audio_streamer.start_streaming()
                
                try:
                    # Keep the connection alive
                    print("\nStreaming audio from Google Meet...\nPress Enter to stop streaming and exit...")
                    input()
                except KeyboardInterrupt:
                    print("\nKeyboard interrupt detected, stopping...")
                
            else:
                print("⚠ Could not find a join button")
        
        except Exception as join_error:
            print(f"Join button error: {join_error}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    
    finally:
        # Make sure to stop streaming before closing
        if audio_streamer:
            audio_streamer.stop_streaming()
            
        if driver:
            driver.quit()

if __name__ == "__main__":
    MEET_LINK = "https://meet.google.com/aqu-zbuo-qyn"
    WEBSOCKET_URL = "ws://localhost:8080/audio"  # Replace with your teammate's WebSocket server URL
    
    join_and_stream_meet(MEET_LINK, WEBSOCKET_URL)