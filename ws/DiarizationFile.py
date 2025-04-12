import os 
from pyannote.audio import Pipeline 
import ffmpeg
import torch
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
    def _transcribe_and_diarize_chunk(self, chunk_data, index):
        """
        Save a PCM chunk to file, convert it to WAV, transcribe and diarize it,
        and send the results over the WebSocket connection.
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
            # Get the transcript from Whisper
            result = self.whisper_model.transcribe(chunk_wav_path)
            transcript = result['text'].strip()
            # Only perform diarization if there's actual transcript content
            if transcript and self.diarization_pipeline:
                diarization_results = self._perform_diarization(chunk_wav_path)
                diarized_transcript = self._combine_transcript_with_diarization(transcript, diarization_results)
                print(f"🗣 [Live] Chunk {index} Diarized Transcript:\n{diarized_transcript}\n")
                self.transcript_text += diarized_transcript + " "
                self._send_transcript(diarized_transcript, index)
            else:
                print(f"🗣 [Live] Chunk {index} Transcript (no diarization):\n{transcript}\n")
                self.transcript_text += transcript + " "
                self._send_transcript(transcript, index)
            if os.path.exists(chunk_wav_path):
                    os.remove(chunk_wav_path)
            if os.path.exists(chunk_pcm_path):
                    os.remove(chunk_pcm_path)
        except Exception as e:
            print(f"❌ Error in transcription/diarization for chunk {index}: {e}")
        


