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

def human_delay(min_time=2, max_time=5):
    time.sleep(random.uniform(min_time, max_time))

def join_and_record_meet(meet_link):
   
    output_dir = "meet_recordings"
    os.makedirs(output_dir, exist_ok=True)
    
    
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_filename = os.path.join(output_dir, f"meet_recording_{timestamp}.wav")

    
    audio_recorder = AudioRecorder(output_filename)

    # Use undetected_chromedriver's native ChromeOptions
    chrome_options = uc.ChromeOptions()
    
    
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--use-fake-ui-for-media-stream")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    
    
    chrome_options.add_argument("--disable-notifications")

    driver = None  
    
    try:
       
        driver = uc.Chrome(options=chrome_options)
        
       
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
                name_input.clear()  # Clear any existing text
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
                
                time.sleep(600)  # Keeps the meet open for 10 minutes
                
               
                audio_recorder.stop_recording()
            else:
                print("⚠ Could not find a join button")
        
        except Exception as join_error:
            print(f"Join button error: {join_error}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    
    finally:
        
        if driver:
            driver.quit()

MEET_LINK = "https://meet.google.com/gzw-ktbj-anc"

if __name__ == "__main__":
    join_and_record_meet(MEET_LINK)