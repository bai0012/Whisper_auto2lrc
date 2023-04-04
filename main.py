import os
import subprocess
import json
import tkinter as tk
from tkinter import filedialog
from prettytable import PrettyTable
from tqdm import tqdm

# 由用户设定路径、模型和语言
os.system('python load_config.py') 
# 读取 config.json 文件
with open("config.json", "r") as f:
    config = json.load(f)

# 获取要转换的所有音频文件
audio_files = []
for root, dirs, files in os.walk(config["folderPath"]):
    for file in files:
        if file.endswith((".mp3", ".wav")):
            audio_files.append(os.path.join(root, file))

# 设置进度条初始值
i = 0

# 遍历每个音频文件并进行转换
for file in tqdm(audio_files, desc="Converting audio files..."):
    # 更新进度条
    i += 1
    
    # 获取同名的 .lrc 文件，如果存在则直接跳过转换
    lrc_file = os.path.join(os.path.dirname(file), os.path.splitext(os.path.basename(file))[0] + ".lrc")
    if os.path.exists(lrc_file):
        continue
    
    # 执行 Whisper 命令将音频转换为文本
    subprocess.run(['whisper', '--model', config['modelChoice'], '--language', config['language'], file], check=True)
    
    # 获取同名的 .srt 文件并调用 Python 程序将其转换为 .lrc 文件
    srt_file = os.path.join(os.path.dirname(file), os.path.splitext(os.path.basename(file))[0] + ".srt")
    if os.path.exists(srt_file):
        subprocess.run(['python', 'srt_to_lrc.py', srt_file], check=True)
    
    # 删除由 Whisper 生成的文件
    file_basename = os.path.splitext(os.path.basename(file))[0]
    for whisper_file in os.listdir(os.path.dirname(file)):
        if file_basename in whisper_file and whisper_file.endswith((".json", ".tsv", ".txt", ".vtt")):
            os.remove(os.path.join(os.path.dirname(file), whisper_file))
    
# 更新进度条，指示转换已完成
tqdm.write("Conversion completed.")

# 显示 "Finish" 并黄色高亮显示
print("\033[33mFinish\033[0m")
