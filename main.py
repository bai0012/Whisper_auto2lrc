import os
import sys
import shutil
import subprocess
import traceback
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QProgressBar, QPushButton, QFileDialog,
                             QComboBox, QLineEdit, QFormLayout, QMessageBox,
                             QTextEdit)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont, QIcon

# --- Check for srt_to_lrc ---
try:
    # Assuming srt_to_lrc.py is in the same directory or importable
    # (auto-py-to-exe should handle bundling this if added correctly)
    import srt_to_lrc
except ImportError:
    # Display error immediately if module is missing
    app = QApplication([]) # Need an app instance for QMessageBox
    QMessageBox.critical(None, "Startup Error", "Could not import srt_to_lrc.py. Make sure it's included with the application.")
    sys.exit(1)

# --- Constants and Path Definitions ---

# Use CWD as the base for finding whisper.exe and creating temp dir, as requested
# This works well with auto-py-to-exe if whisper.exe is placed alongside the final .exe
try:
    # Use Path object for consistency
    BASE_PATH = Path(os.getcwdb().decode("utf-8")).resolve()
except Exception as e:
    app = QApplication([])
    QMessageBox.critical(None, "Startup Error", f"Could not determine base path using CWD: {e}")
    sys.exit(1)

WHISPER_EXE_PATH = BASE_PATH / "whisper.exe" # Assumes whisper.exe is in CWD
TEMP_DIR_NAME = "temp_lrc_processing"
# Temp directory will also be created relative to CWD
TEMP_DIR_PATH = BASE_PATH / TEMP_DIR_NAME

AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.ogg'}

# Determine Application Base Directory (more robust for finding bundled assets like icons)
if getattr(sys, 'frozen', False):
    # Running as bundled executable (e.g., PyInstaller/auto-py-to-exe)
    # sys.executable is the path to the .exe file
    APP_BASE_DIR = Path(sys.executable).parent
else:
    # Running as a script
    # __file__ is the path to the script file
    APP_BASE_DIR = Path(__file__).resolve().parent


# --- Worker Thread ---
class Worker(QThread):
    progress = pyqtSignal(str, int)
    error_occurred = pyqtSignal(str)
    finished_signal = pyqtSignal() # Renamed from finished to avoid clash

    def __init__(self, folder_path: Path, model: str, language: str):
        super().__init__()
        self.folder_path = folder_path
        self.model = model
        self.language = language
        # Use the globally defined TEMP_DIR_PATH (relative to CWD)
        self.temp_dir_path = TEMP_DIR_PATH
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        # Check for whisper.exe using the path relative to CWD
        if not WHISPER_EXE_PATH.exists():
            self.error_occurred.emit(f"Error: whisper.exe not found at {WHISPER_EXE_PATH} (expected in the application's running directory).")
            return

        try:
            # Create temp dir safely (relative to CWD)
            self.temp_dir_path.mkdir(parents=True, exist_ok=True)

            # Find audio files needing LRC files
            audio_files = [
                f for f in self.folder_path.rglob('*')
                if f.suffix.lower() in AUDIO_EXTENSIONS and not f.with_suffix('.lrc').exists()
            ]

            total_files = len(audio_files)
            if total_files == 0:
                self.progress.emit("No new audio files found to process.", 0)
                # Clean up empty temp dir if created
                try:
                    if not any(self.temp_dir_path.iterdir()): # Check if empty
                         self.temp_dir_path.rmdir()
                except OSError:
                    pass # Ignore cleanup error
                return # Nothing to do

            self.progress.emit(f"Found {total_files} files to process...", 0)

            for idx, audio_file in enumerate(audio_files):
                if not self._is_running:
                    self.progress.emit("Processing cancelled.", int((idx / total_files) * 100))
                    break

                progress_text = f'Processing: {audio_file.name} ({idx + 1}/{total_files})'
                self.progress.emit(progress_text, int((idx / total_files) * 100))

                # Define expected SRT path in temp directory (which is relative to CWD)
                expected_srt_file_path = self.temp_dir_path / (audio_file.stem + '.srt')

                try:
                    # --- Run Whisper ---
                    cmd = [
                        str(WHISPER_EXE_PATH), # Path relative to CWD
                        str(audio_file),
                        "--model", self.model,
                        "--language", self.language,
                        "--output_format", "srt",
                        # Output dir is TEMP_DIR_PATH (relative to CWD)
                        "--output_dir", str(self.temp_dir_path)
                    ]

                    startupinfo = None
                    creationflags = 0
                    if sys.platform == "win32":
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = subprocess.SW_HIDE
                        creationflags = subprocess.CREATE_NO_WINDOW

                    # Run from the base path (CWD) - might not be strictly necessary
                    # but ensures relative paths are interpreted from there if needed.
                    result = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                            encoding='utf-8', startupinfo=startupinfo,
                                            creationflags=creationflags, cwd=str(BASE_PATH))

                    if result.returncode != 0:
                        error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
                        self.error_occurred.emit(f"Whisper failed for {audio_file.name}:\n{error_msg}")
                        if expected_srt_file_path.exists():
                            try: expected_srt_file_path.unlink()
                            except OSError: pass
                        continue

                    # --- Convert SRT to LRC ---
                    if expected_srt_file_path.exists():
                        generated_lrc_path = srt_to_lrc.srt_to_lrc(expected_srt_file_path)

                        if generated_lrc_path and generated_lrc_path.exists():
                            target_lrc_path = audio_file.with_suffix('.lrc')
                            try:
                                shutil.move(str(generated_lrc_path), str(target_lrc_path))
                            except Exception as move_err:
                                self.error_occurred.emit(f"Failed to move {generated_lrc_path.name} to target location: {move_err}")
                        else:
                             self.error_occurred.emit(f"LRC file not generated for {audio_file.name} (SRT exists).")
                    else:
                        self.error_occurred.emit(f"Whisper ran but SRT file not found for {audio_file.name} at {expected_srt_file_path}")

                except Exception as e:
                    self.error_occurred.emit(f"Error processing {audio_file.name}: {e}\n{traceback.format_exc()}")
                    continue

                # Update progress after successful processing or skipping
                # Use floor division for slightly more accurate progress steps
                self.progress.emit(progress_text, int(((idx + 1) / total_files) * 100))

        except Exception as e:
            self.error_occurred.emit(f"An unexpected error occurred during setup/file scan: {e}\n{traceback.format_exc()}")
        finally:
            # --- Cleanup ---
            if self.temp_dir_path.exists():
                try:
                    shutil.rmtree(self.temp_dir_path)
                except Exception as clean_err:
                     self.error_occurred.emit(f"Warning: Failed to delete temp directory {self.temp_dir_path}: {clean_err}")
            if self._is_running:
                self.finished_signal.emit()


# --- Main Application Window ---
class App(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Audio to LRC Extractor (using Whisper)")

        # Use APP_BASE_DIR for icon (relative to .exe or .py file)
        icon_path = APP_BASE_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
             print(f"Debug: Icon not found at {icon_path}") # Add print for debugging

        # --- Set Initial Size ---
        initial_width = 800
        initial_height = 550
        self.resize(initial_width, initial_height)
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # --- Form Layout ---
        form_layout = QFormLayout()

        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setPlaceholderText("Select folder containing audio files")
        self.folder_path_edit.setText("F:/ai-gen/riffusion/vladua-bufer")
        self.select_folder_button = QPushButton("Select Folder...")
        self.select_folder_button.setFont(QFont("Arial", 10))
        self.select_folder_button.clicked.connect(self.select_folder)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_path_edit)
        folder_layout.addWidget(self.select_folder_button)
        form_layout.addRow("Audio Folder:", folder_layout)

        self.model_select = QComboBox()
        self.model_select.addItems(["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"])
        self.model_select.setCurrentText("base")
        form_layout.addRow("Whisper Model:", self.model_select)

        self.language_input = QLineEdit()
        self.language_input.setPlaceholderText("e.g., 'en', 'ja', 'auto' (leave blank for auto)")
        self.language_input.setText("en")
        form_layout.addRow("Language:", self.language_input)

        layout.addLayout(form_layout)

        # --- Progress Area ---
        self.progress_label = QLabel("State: Idle")
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

    def select_folder(self):
        # Use current text as starting directory if valid, otherwise use CWD
        start_dir = self.folder_path_edit.text()
        if not Path(start_dir).is_dir():
            start_dir = str(BASE_PATH) # Fallback to CWD

        folder = QFileDialog.getExistingDirectory(self, "Select Audio Folder", start_dir)
        if folder:
            self.folder_path_edit.setText(folder)

    def log_message(self, message: str):
        self.log_output.append(message)
        QApplication.processEvents() # Ensure GUI updates for logs

    def start_processing(self):
        folder_str = self.folder_path_edit.text().strip()
        model = self.model_select.currentText()
        language = self.language_input.text().strip() or "auto"

        if not folder_str:
            QMessageBox.warning(self, "Input Error", "Please select an audio folder.")
            return

        folder_path = Path(folder_str)
        if not folder_path.is_dir():
            QMessageBox.warning(self, "Input Error", f"Selected path is not a valid folder:\n{folder_str}")
            return

        # Check for whisper.exe again before starting, using the path relative to CWD
        if not WHISPER_EXE_PATH.exists():
             QMessageBox.critical(self, "Error", f"whisper.exe not found at expected location:\n{WHISPER_EXE_PATH}\nPlease ensure it's in the same directory as the application executable.")
             return

        self.log_output.clear()
        self.log_message(f"Using Base Path (CWD): {BASE_PATH}")
        self.log_message(f"Expecting whisper.exe at: {WHISPER_EXE_PATH}")
        self.log_message("Starting processing...")
        self.log_message(f"Folder: {folder_path}")
        self.log_message(f"Model: {model}")
        self.log_message(f"Language: {language}")

        self.set_controls_enabled(False)

        self.worker = Worker(folder_path, model, language)
        self.worker.progress.connect(self.update_progress)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.finished_signal.connect(self.worker_finished)
        self.worker.start()

    def stop_processing(self):
         if self.worker and self.worker.isRunning():
            self.log_message("Attempting to stop processing...")
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def update_progress(self, text, value):
        self.progress_label.setText(text)
        self.progress_bar.setValue(value)
        # Log every text update received from the worker
        self.log_message(text)


    def handle_error(self, error_message):
        self.log_message(f"[ERROR] {error_message}")
        # Optionally make errors more prominent
        # self.progress_label.setText("Error occurred! See log.")
        # self.progress_label.setStyleSheet("color: red;")


    def worker_finished(self):
        if self.worker and not self.worker._is_running:
             status_message = "State: Stopped by user."
             log_suffix = "Processing stopped."
        else:
            status_message = "State: Finished!"
            log_suffix = "Processing finished."
            self.progress_bar.setValue(100)

        self.progress_label.setText(status_message)
        self.progress_label.setStyleSheet("") # Reset color if changed by error
        self.log_message(log_suffix)
        self.set_controls_enabled(True)
        self.worker = None

    def set_controls_enabled(self, enabled: bool):
        self.start_button.setEnabled(enabled)
        self.select_folder_button.setEnabled(enabled)
        self.folder_path_edit.setEnabled(enabled)
        self.model_select.setEnabled(enabled)
        self.language_input.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, 'Confirm Exit',
                                         "Processing is ongoing. Stop and exit?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                 self.stop_processing()
                 self.worker.wait(1000) # Give thread time to potentially finish current file/stop
                 event.accept()
            else:
                 event.ignore()
        else:
            event.accept()


# --- Entry Point ---
if __name__ == '__main__':
    # Important: Use this pattern for multiprocessing support with PyInstaller/auto-py-to-exe if needed
    # Though not strictly required here as we use QThread and subprocess
    # from multiprocessing import freeze_support
    # freeze_support()

    app = QApplication(sys.argv)
    # Ensure required resources are accessible before showing window
    if not WHISPER_EXE_PATH.exists():
         QMessageBox.critical(None, "Startup Error", f"whisper.exe not found at:\n{WHISPER_EXE_PATH}\n\nPlease ensure it is placed in the same directory as this application.")
         sys.exit(1)

    window = App()
    window.show()
    sys.exit(app.exec_())

