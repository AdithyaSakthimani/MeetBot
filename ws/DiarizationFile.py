import os 
from pyannote.audio import Pipeline 
import ffmpeg
import torch
import requests
class DiarizationHelper:
    def __init__(self):
        try:
            print("Loading speaker diarization model...")
            hf_token = os.getenv("HF_TOKEN")
            print(f"Token found: {'Yes' if hf_token else 'No'}")

            self.diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token
            )
            # Set this to run on GPU if available
            if torch.cuda.is_available():
                self.diarization_pipeline = self.diarization_pipeline.to(torch.device("cuda"))
        except Exception as e:
            print(f"Error loading diarization model: {e}")
            self.diarization_pipeline = None
    def _combine_transcript_with_diarization(self, transcript, diarization_segments):
        if not diarization_segments:
            return transcript  
        # Sort segments by start time
        diarization_segments.sort(key=lambda x: x["start"])
        
        # For simplicity, just take the most dominant speaker in this chunk
        if len(diarization_segments) > 0:
            # Count speaker occurrences
            speaker_times = {}
            for segment in diarization_segments:
                speaker = segment["speaker"]
                duration = segment["end"] - segment["start"]
                speaker_times[speaker] = speaker_times.get(speaker, 0) + duration
            
            # Find the speaker with the most time
            dominant_speaker = max(speaker_times.items(), key=lambda x: x[1])[0]
            return f"[{dominant_speaker}]: {transcript}"
        
        return transcript
    def _perform_diarization(self, audio_file):
        """
        Perform speaker diarization on the audio file.
        Returns a list of (speaker, start, end) tuples.
        """
        try:
            # Run diarization on the audio file
            diarization = self.diarization_pipeline(audio_file)
            
            # Extract speaker segments
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "speaker": f"Speaker {speaker.split('_')[-1]}",
                    "start": turn.start,
                    "end": turn.end
                })
            
            return segments
        except Exception as e:
            print(f"❌ Error in diarization: {e}")
            return []
    def _transcribe_and_diarize_chunk(self, chunk_data, chunk_index):
        try:
            temp_file = f"chunk_{chunk_index}.wav"

            # Save audio chunk temporarily
            with open(temp_file, "wb") as f:
                f.write(chunk_data)

            # Convert to WAV (if needed)
            wav_file = temp_file.replace(".wav", "_converted.wav")
            ffmpeg.input(temp_file).output(wav_file, ar=16000, ac=1).run(overwrite_output=True)

            # Send to cloud API
            files = {"file": open(wav_file, "rb")}
            response = requests.post(f"{os.getenv('AWS_EC2_URL')}/transcribe", files=files)

            if response.status_code == 200:
                result = response.json()
                transcription = result.get("transcription", "")
                # Get diarization and actions from the response if available
                diarization = result.get("diarization", [])
                actions = result.get("actions", {})
                
                # Send the transcript to your WebSocket
                self._send_transcript(transcription, chunk_index)
                
                # Print actions if available
                if actions:
                    print("Action items detected:")
                    print(actions)
            else:
                print(f"Transcription failed: {response.text}")

            # Clean up temporary files
            os.remove(temp_file)
            os.remove(wav_file)

        except Exception as e:
            print(f"Error in remote transcription: {e}")