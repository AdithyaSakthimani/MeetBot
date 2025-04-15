import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
from TranscriptionFile import AudioTranscriber

def human_delay(min_time=2, max_time=5):
    time.sleep(random.uniform(min_time, max_time))

def join_and_stream_meet(meet_link):
    audio_transcriber = AudioTranscriber()
    audio_transcriber.start_streaming()
    
    # Rest of the function remains the same
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
                print("\nStreaming audio from Google Meet with speaker diarization...\nPress Enter to stop streaming and exit...")
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
    MEET_LINK = "https://meet.google.com/zbk-gaoy-mmq"
    join_and_stream_meet(MEET_LINK)
