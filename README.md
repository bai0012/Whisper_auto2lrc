# Whisper_auto2lrc
使用whisper通过powershell和python程序实现文件夹下（及子文件夹）所有音频文件转换为.lrc字幕文件

## 本程序大部分由ChatGPT生成

首先安装python，我使用的是python3.10.10

然后根据whisper的要求安装python依赖库[openai/whisper](https://github.com/openai/whisper)

下载srt_to_lrc.py和whisper.ps1


## 自定义，修改whisper.ps1的下列内容：

### 修改要处理的mp3文件的路径，（包括文件夹和子文件夹）

第2行
```powershell
$folderPath = "R:"
```

### 设定whisper的参数，默认为small模型，语言为日语

第16行
 ```powershell
 whisper --model small --language ja $file.FullName
 ```
 
 ### 设定srt_to_lrc.py文件的路径
 
 第22行
 ```powershell
 & python "R:/srt_to_lrc.py" $srtFile.FullName $lrcFile
 ```
