import json
import tkinter as tk
from tkinter import filedialog
from prettytable import PrettyTable

# 模型列表
models = [
    {"name": "tiny", "memory": "1GB"},
    {"name": "base", "memory": "1GB"},
    {"name": "small", "memory": "2GB"},
    {"name": "medium", "memory": "5GB"},
    {"name": "large", "memory": "10GB"}
]

# 生成模型表格
model_table = PrettyTable()
model_table.field_names = ["选择", "名字", "需求显存"]
for i, model in enumerate(models):
    model_table.add_row([str(i+1), model["name"], model["memory"]])

# 请求用户输入路径
print("请选择要处理的音频文件的路径：")
folderPath = filedialog.askdirectory()

# 请求用户选择模型
print("请选择模型：")
print(model_table)
modelChoiceIndex = int(input("请输入模型编号：")) - 1
modelChoice = models[modelChoiceIndex]["name"]

# 请求用户输入语言
language = input("请输入语言：")

# 将输入的变量保存为json文件
input_dict = {
    "folderPath": folderPath,
    "modelChoice": modelChoice,
    "language": language
}
with open("config.json", "w") as f:
    json.dump(input_dict, f)
