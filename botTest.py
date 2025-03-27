import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time
import random
import subprocess
import threading

# === Configuration ===
MEET_LINK = "https://meet.google.com/wix-djuy-nze"  # Replace with actual link
RECORD_DURATION = 600  # Duration in seconds

# === Randomized Human Behavior ===
def human_delay(min_time=2, max_time=5):
    time.sleep(random.uniform(min_time, max_time))

# === Audio Recording Function (Records System Audio) ===
def record_audio(output_filename="meet_recording.wav", duration=600):
    print("🎤 Starting Audio Recording...")
    
    cmd = [
        'ffmpeg',
        '-y',
        '-f', 'dshow',
        '-i', 'audio=Stereo Mix',  # Change to "Virtual Audio Cable" if needed
        '-t', str(duration),
        output_filename
    ]

    subprocess.run(cmd)
    print("🎤 Recording finished. File saved.")

# === Google Meet Bot ===
def join_google_meet(meet_link):
    # Configure Chrome options to keep mic & camera ON
    options = uc.ChromeOptions()
    options.add_argument("--use-fake-ui-for-media-stream")  # Automatically allows mic & camera
    options.add_argument("--start-maximized")  # Open in full screen

    # Enable mic/cam permissions
    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.media_stream_mic": 1,
        "profile.default_content_setting_values.media_stream_camera": 1,
        "profile.default_content_setting_values.notifications": 1
    })

    # Start undetected ChromeDriver
    driver = uc.Chrome(use_subprocess=True, options=options)

    # Open Google Meet
    driver.get(meet_link)
    human_delay(5, 8)

    # Enter random guest name
    try:
        name_input = driver.find_element(By.XPATH, '//input[@aria-label="Your name"]')
        guest_name = "Guest" + str(random.randint(100, 999))
        name_input.send_keys(guest_name)
        human_delay(2, 4)
    except:
        print("⚠ Name input not found, continuing...")

    # Click "Ask to join"
    try:
        join_btn = driver.find_element(By.XPATH, '//span[contains(text(),"Ask to join")]')
        join_btn.click()
        human_delay(4, 7)
        print(f"✅ Joined as {guest_name} with mic & camera ON")
    except:
        print("⚠ Unable to find Join button, exiting.")
        driver.quit()
        return

    # Keep browser open while recording
    time.sleep(RECORD_DURATION + 10)
    driver.quit()

# === Main Execution ===
if __name__ == "__main__":
    # Start audio recording in a separate thread
    recorder = threading.Thread(target=record_audio, args=("meet_recording.wav", RECORD_DURATION))
    recorder.start()

    # Start selenium bot
    join_google_meet(MEET_LINK)
