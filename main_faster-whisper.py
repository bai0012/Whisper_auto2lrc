import os
import sys
import shutil
import subprocess
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton, QFileDialog, QComboBox, QLineEdit, QFormLayout, QMessageBox
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

class Worker(QThread):
    progress = pyqtSignal(str, int)

    def __init__(self, folder, model, language):
        super().__init__()
        self.folder = folder
        self.model = model
        self.language = language

    def run(self):
        audio_extensions = {'.mp3', '.wav'}
        temp_dir = Path('temp')
        temp_dir.mkdir(exist_ok=True)

        audio_files = [f for f in Path(self.folder).rglob('*') if f.suffix in audio_extensions and not (f.with_suffix('.lrc')).exists()]

        total_files = len(audio_files)
        for idx, audio_file in enumerate(audio_files):
            progress_text = f'处理中: {audio_file.name} ({idx + 1}/{total_files})'
            self.progress.emit(progress_text, int((idx + 1) / total_files * 100))

            srt_file = temp_dir / (audio_file.stem + '.srt')
            subprocess.run(f'whisper-ctranslate2 "{audio_file}" --model {self.model} --language {self.language} --vad_filter True --print_colors True', shell=True, cwd=temp_dir)

            if srt_file.exists():
                subprocess.run(f'python srt_to_lrc.py "{srt_file}"', shell=True)
                lrc_file = temp_dir / (audio_file.stem + '.lrc')
                if lrc_file.exists():
                    shutil.move(lrc_file, audio_file.with_suffix('.lrc'))

        shutil.rmtree(temp_dir)

class App(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("LRC生成器")
        self.setWindowIcon(QIcon("icon.png"))

        layout = QVBoxLayout()

        form_layout = QFormLayout()
        self.folder_path = QLineEdit()
        form_layout.addRow("文件夹路径", self.folder_path)

        self.model_select = QComboBox()
        self.model_select.addItems(["tiny", "base", "small", "medium", "large-v2"])
        form_layout.addRow("模型大小", self.model_select)

        self.language_input = QLineEdit()
        form_layout.addRow("语言", self.language_input)
        layout.addLayout(form_layout)

        self.progress_label = QLabel("准备开始...")
        self.progress_label.setFont(QFont("Arial", 12))
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.start_button = QPushButton("开始")
        self.start_button.setFont(QFont("Arial", 12))
        self.start_button.clicked.connect(self.start_processing)
        layout.addWidget(self.start_button)

        self.select_folder_button = QPushButton("选择文件夹")
        self.select_folder_button.setFont(QFont("Arial", 12))
        self.select_folder_button.clicked.connect(self.select_folder)
        layout.addWidget(self.select_folder_button)

        self.setLayout(layout)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory()
        if folder:
            self.folder_path.setText(folder)

    def start_processing(self):
        folder = self.folder_path.text()
        model = self.model_select.currentText()
        language = self.language_input.text()
        if not folder or not language:
            QMessageBox.warning(self, "警告", "请确保已输入文件夹路径和语言。")
            return

        self.start_button.setEnabled(False)
        self.select_folder_button.setEnabled(False)

        self.worker = Worker(folder, model, language)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def update_progress(self, text, value):
        self.progress_label.setText(text)
        self.progress_bar.setValue(value)

    def worker_finished(self):
        self.progress_label.setText("完成！")
        self.start_button.setEnabled(True)
        self.select_folder_button.setEnabled(True)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec_())