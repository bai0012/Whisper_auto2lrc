import os
import sys
import shutil
import traceback
from pathlib import Path
import math  # For ceiling function in time formatting
import time # For basic timing if needed

# --- Check Core Dependencies ---
try:
    import whisper
except ImportError:
    # Display error immediately if whisper module is missing
    # Need a temporary minimal QApplication to show the message box
    from PyQt5.QtWidgets import QApplication, QMessageBox
    _app = QApplication([])
    QMessageBox.critical(None, "Startup Error", "Could not import the 'whisper' library.\nPlease install it using: pip install -U openai-whisper")
    sys.exit(1)

try:
    # Assuming srt_to_lrc.py is in the same directory or importable
    import srt_to_lrc
except ImportError:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    _app = QApplication([])
    QMessageBox.critical(None, "Startup Error", "Could not import srt_to_lrc.py. Make sure it's included with the application.")
    sys.exit(1)

# --- Check for FFMPEG ---
if shutil.which("ffmpeg") is None:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    _app = QApplication([])
    QMessageBox.critical(None, "Startup Error", "FFmpeg not found.\n\nThe Whisper library requires FFmpeg to process audio.\nPlease install FFmpeg and ensure it's in your system's PATH.\n\nSee: https://ffmpeg.org/download.html")
    # sys.exit(1) # Allow app to start but warn user? Or exit? Exiting is safer.
    sys.exit(1)


from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QProgressBar, QPushButton, QFileDialog,
                             QComboBox, QLineEdit, QFormLayout, QMessageBox,
                             QTextEdit)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont, QIcon

# --- Constants and Path Definitions ---

# Use CWD as the base for the temp dir, as requested previously
try:
    BASE_PATH = Path(os.getcwdb().decode("utf-8")).resolve()
except Exception as e:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    _app = QApplication([])
    QMessageBox.critical(None, "Startup Error", f"Could not determine base path using CWD: {e}")
    sys.exit(1)

TEMP_DIR_NAME = "temp_lrc_processing"
TEMP_DIR_PATH = BASE_PATH / TEMP_DIR_NAME
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.mkv', '.mp4'} # Whisper supports more

# Determine Application Base Directory (for assets like icons)
if getattr(sys, 'frozen', False):
    APP_BASE_DIR = Path(sys.executable).parent
else:
    APP_BASE_DIR = Path(__file__).resolve().parent

# Global variable to hold the loaded Whisper model (optional optimization)
# Set to None initially. Will be loaded by the worker.
# This prevents reloading the model for every run if the app stays open,
# but means the model stays in memory. Load inside Worker for per-run loading.
# WHISPER_MODEL_CACHE = {} # Or load inside worker run()

# --- Helper Function for SRT Time Formatting ---
def format_srt_time(seconds: float) -> str:
    """Converts seconds to SRT time format HH:MM:SS,ms"""
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)

    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000

    minutes = milliseconds // 60_000
    milliseconds %= 60_000

    seconds = milliseconds // 1_000
    milliseconds %= 1_000

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

# --- Helper Function to Generate SRT Content ---
def generate_srt_content(transcription_result: dict) -> str:
    """Generates SRT file content string from Whisper transcription result."""
    srt_content = ""
    for i, segment in enumerate(transcription_result["segments"], start=1):
        start_time_str = format_srt_time(segment['start'])
        end_time_str = format_srt_time(segment['end'])
        text = segment['text'].strip()
        # Handle potential multi-line text within a segment if needed,
        # though typically whisper provides reasonably short segments.
        srt_content += f"{i}\n"
        srt_content += f"{start_time_str} --> {end_time_str}\n"
        srt_content += f"{text}\n\n"
    return srt_content


# --- Worker Thread ---
class Worker(QThread):
    progress = pyqtSignal(str, int)
    error_occurred = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, folder_path: Path, model_name: str, language: str):
        super().__init__()
        self.folder_path = folder_path
        self.model_name = model_name
        self.language = language if language and language.lower() != 'auto' else None # Whisper uses None for auto-detect
        self.temp_dir_path = TEMP_DIR_PATH
        self._is_running = True
        self.whisper_model = None # Model will be loaded in run()

    def stop(self):
        self._is_running = False
        # Note: Stopping doesn't immediately interrupt a running model.transcribe() call

    def run(self):
        try:
            # --- Load Whisper Model ---
            # Consider moving model loading outside if you want to cache it
            # across multiple runs within the same app session.
            # Loading here ensures it uses the selected model for this run.
            self.progress.emit(f"Loading Whisper model: {self.model_name}...", 0)
            QApplication.processEvents() # Allow GUI to update
            try:
                # Check cache first (example of simple caching)
                # if self.model_name in WHISPER_MODEL_CACHE:
                #     self.whisper_model = WHISPER_MODEL_CACHE[self.model_name]
                # else:
                #     self.whisper_model = whisper.load_model(self.model_name)
                #     WHISPER_MODEL_CACHE[self.model_name] = self.whisper_model
                # Simpler: Load every time worker runs
                self.whisper_model = whisper.load_model(self.model_name)

            except Exception as model_load_error:
                self.error_occurred.emit(f"Failed to load Whisper model '{self.model_name}': {model_load_error}")
                # Try to unload partially loaded model? Might not be possible/easy.
                self.whisper_model = None
                return # Cannot continue without a model
            self.progress.emit(f"Model '{self.model_name}' loaded.", 0)


            # --- Create Temp Directory ---
            self.temp_dir_path.mkdir(parents=True, exist_ok=True)

            # --- Find Audio Files ---
            audio_files = [
                f for f in self.folder_path.rglob('*')
                if f.suffix.lower() in AUDIO_EXTENSIONS and not f.with_suffix('.lrc').exists()
            ]

            total_files = len(audio_files)
            if total_files == 0:
                self.progress.emit("No new audio files found to process.", 0)
                try: # Clean up empty temp dir
                    if not any(self.temp_dir_path.iterdir()): self.temp_dir_path.rmdir()
                except OSError: pass
                return

            self.progress.emit(f"Found {total_files} files to process...", 0)

            # --- Process Files ---
            for idx, audio_file in enumerate(audio_files):
                if not self._is_running:
                    self.progress.emit("Processing cancelled.", int((idx / total_files) * 100))
                    break

                progress_text = f'Processing: {audio_file.name} ({idx + 1}/{total_files})'
                self.progress.emit(progress_text, int((idx / total_files) * 100))
                QApplication.processEvents() # Ensure label updates before potentially long transcribe

                expected_srt_file_path = self.temp_dir_path / (audio_file.stem + '.srt')
                generated_lrc_path = None # Reset for each file

                try:
                    # --- Transcribe using Whisper library ---
                    transcribe_options = {"language": self.language} # Add other options like fp16=False if needed
                    result = self.whisper_model.transcribe(str(audio_file), **transcribe_options, verbose=False) # verbose=False suppresses console output

                    # --- Generate SRT Content from Result ---
                    srt_data = generate_srt_content(result)
                    if not srt_data:
                         self.error_occurred.emit(f"Whisper produced no output for {audio_file.name}")
                         continue # Skip to next file

                    # --- Write SRT to Temp File ---
                    try:
                        with open(expected_srt_file_path, 'w', encoding='utf-8') as srt_f:
                            srt_f.write(srt_data)
                    except IOError as io_err:
                        self.error_occurred.emit(f"Failed to write temporary SRT file {expected_srt_file_path.name}: {io_err}")
                        continue # Skip to next file

                    # --- Convert SRT to LRC (using existing function) ---
                    if expected_srt_file_path.exists():
                        generated_lrc_path = srt_to_lrc.srt_to_lrc(expected_srt_file_path) # This deletes the SRT file

                        if generated_lrc_path and generated_lrc_path.exists():
                            target_lrc_path = audio_file.with_suffix('.lrc')
                            try:
                                shutil.move(str(generated_lrc_path), str(target_lrc_path))
                            except Exception as move_err:
                                self.error_occurred.emit(f"Failed to move {generated_lrc_path.name} to target: {move_err}")
                        elif expected_srt_file_path.exists(): # Should have been deleted by srt_to_lrc
                            self.error_occurred.emit(f"LRC conversion failed but SRT still exists for {audio_file.name}")
                        else:
                            self.error_occurred.emit(f"LRC file not generated for {audio_file.name} after SRT processing.")

                    else:
                        # This case should ideally not happen if SRT writing succeeded
                        self.error_occurred.emit(f"Temporary SRT file disappeared before conversion for {audio_file.name}")

                except Exception as e:
                    self.error_occurred.emit(f"Error processing {audio_file.name}: {e}\n{traceback.format_exc()}")
                    # Clean up potentially leftover temp files for this failed audio
                    if expected_srt_file_path.exists():
                        try: expected_srt_file_path.unlink()
                        except OSError: pass
                    if generated_lrc_path and generated_lrc_path.exists():
                         try: generated_lrc_path.unlink()
                         except OSError: pass
                    continue # Skip to next file

                # Update progress after successful processing or handled error
                self.progress.emit(progress_text, int(((idx + 1) / total_files) * 100))

        except Exception as e:
            # Catch errors during setup (e.g., model load, file scan)
            self.error_occurred.emit(f"An unexpected error occurred in worker setup: {e}\n{traceback.format_exc()}")
        finally:
            # --- Cleanup ---
            if self.temp_dir_path.exists():
                try:
                    shutil.rmtree(self.temp_dir_path)
                except Exception as clean_err:
                     self.error_occurred.emit(f"Warning: Failed to delete temp directory {self.temp_dir_path}: {clean_err}")
            # --- Unload model (optional, frees memory) ---
            # If you want to free VRAM/RAM after processing:
            # del self.whisper_model
            # self.whisper_model = None
            # import gc; gc.collect() # Try to force garbage collection
            # Note: CUDA memory might need more specific handling if using GPU

            if self._is_running:
                self.finished_signal.emit()


# --- Main Application Window ---
class App(QWidget):
    # (Constructor __init__ remains the same)
    def __init__(self):
        super().__init__()
        self.worker = None
        self.initUI()

    # (initUI remains mostly the same, just remove whisper.exe mentions)
    def initUI(self):
        self.setWindowTitle("Audio to LRC Extractor (using Whisper Library)")
        icon_path = APP_BASE_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
             print(f"Debug: Icon not found at {icon_path}")

        initial_width = 750
        initial_height = 550
        self.resize(initial_width, initial_height)
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # --- Form Layout ---
        form_layout = QFormLayout()
        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setPlaceholderText("Select folder containing audio files")
        self.folder_path_edit.setText("C:/")
        self.select_folder_button = QPushButton("Select Folder...")
        self.select_folder_button.setFont(QFont("Arial", 10))
        self.select_folder_button.clicked.connect(self.select_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_path_edit)
        folder_layout.addWidget(self.select_folder_button)
        form_layout.addRow("Audio Folder:", folder_layout)

        self.model_select = QComboBox()
        # Add models supported by the library. .en models are English-only.
        self.model_select.addItems(["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v1", "large-v2", "large-v3", "turbo"])
        self.model_select.setCurrentText("base")
        form_layout.addRow("Whisper Model:", self.model_select)

        self.language_input = QLineEdit()
        self.language_input.setPlaceholderText("e.g., 'en', 'ja', 'auto' (leave blank for auto-detect)")
        self.language_input.setText("en")
        form_layout.addRow("Language:", self.language_input)
        layout.addLayout(form_layout)

        # --- Progress Area ---
        self.progress_label = QLabel("State: Idle. Requires FFmpeg installed.") # Note FFmpeg req.
        self.progress_label.setFont(QFont("Arial", 10))
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # --- Log Area ---
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 9))
        self.log_output.setMaximumHeight(150)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log_output)

        # --- Buttons ---
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Processing")
        self.start_button.setFont(QFont("Arial", 12, QFont.Bold))
        self.start_button.clicked.connect(self.start_processing)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setFont(QFont("Arial", 12))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_processing)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    # (select_folder remains the same)
    def select_folder(self):
        start_dir = self.folder_path_edit.text()
        if not Path(start_dir).is_dir():
            start_dir = str(BASE_PATH)
        folder = QFileDialog.getExistingDirectory(self, "Select Audio Folder", start_dir)
        if folder:
            self.folder_path_edit.setText(folder)

    # (log_message remains the same)
    def log_message(self, message: str):
        self.log_output.append(message)
        QApplication.processEvents()

    def start_processing(self):
        folder_str = self.folder_path_edit.text().strip()
        model = self.model_select.currentText()
        language = self.language_input.text().strip() or "auto" # Default to auto if empty

        if not folder_str:
            QMessageBox.warning(self, "Input Error", "Please select an audio folder.")
            return
        folder_path = Path(folder_str)
        if not folder_path.is_dir():
            QMessageBox.warning(self, "Input Error", f"Selected path is not a valid folder:\n{folder_str}")
            return

        # Double-check ffmpeg before starting (user might have uninstalled it)
        if shutil.which("ffmpeg") is None:
             QMessageBox.critical(self, "Error", "FFmpeg not found in system PATH.\nCannot proceed without FFmpeg.")
             return

        self.log_output.clear()
        self.log_message(f"Using Base Path: {BASE_PATH}")
        self.log_message("Starting processing...")
        self.log_message(f"Folder: {folder_path}")
        self.log_message(f"Model: {model}")
        self.log_message(f"Language: {language if language else 'auto-detect'}")

        self.set_controls_enabled(False)
        self.progress_label.setText("State: Initializing...") # Update state

        self.worker = Worker(folder_path, model, language)
        self.worker.progress.connect(self.update_progress)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.finished_signal.connect(self.worker_finished)
        self.worker.start()

    # (stop_processing remains the same)
    def stop_processing(self):
         if self.worker and self.worker.isRunning():
            self.log_message("Attempting to stop processing (will finish current file)...")
            self.worker.stop() # Signal the worker loop to stop
            self.stop_button.setEnabled(False)
            # Note: The actual transcription might continue until finished

    # (update_progress remains the same)
    def update_progress(self, text, value):
        self.progress_label.setText(text)
        self.progress_bar.setValue(value)
        self.log_message(text)

    # (handle_error remains the same)
    def handle_error(self, error_message):
        self.log_message(f"[ERROR] {error_message}")
        self.progress_label.setText("State: Error occurred (see log)")
        self.progress_label.setStyleSheet("color: red;")


    # (worker_finished remains the same)
    def worker_finished(self):
        if self.worker and not self.worker._is_running:
             status_message = "State: Stopped by user."
             log_suffix = "Processing stopped."
        else:
            status_message = "State: Finished!"
            log_suffix = "Processing finished."
            self.progress_bar.setValue(100)

        self.progress_label.setText(status_message)
        self.progress_label.setStyleSheet("") # Reset color
        self.log_message(log_suffix)
        self.set_controls_enabled(True)
        self.worker = None

    # (set_controls_enabled remains the same)
    def set_controls_enabled(self, enabled: bool):
        self.start_button.setEnabled(enabled)
        self.select_folder_button.setEnabled(enabled)
        self.folder_path_edit.setEnabled(enabled)
        self.model_select.setEnabled(enabled)
        self.language_input.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)

    # (closeEvent remains the same)
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, 'Confirm Exit',
                                         "Processing is ongoing. Stop and exit?\n(Current file might finish processing)",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                 self.stop_processing()
                 # We can't forcefully kill the transcribe call easily
                 # We just wait briefly for the GUI to acknowledge stop
                 self.worker.wait(500)
                 event.accept()
            else:
                 event.ignore()
        else:
            event.accept()


# --- Entry Point ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Initial checks already happened before QApplication was fully initialized
    # We rely on sys.exit() having been called if checks failed

    window = App()
    window.show()
    sys.exit(app.exec_())

