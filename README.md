# Whisper_auto2lrc
使用whisper通过powershell和python程序实现文件夹下（及子文件夹）所有音频文件转换为.lrc字幕文件

## 本程序大部分由ChatGPT生成

首先安装python，我使用的是python3.10.10

然后根据whisper的要求安装python依赖库[openai/whisper](https://github.com/openai/whisper#setup)

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

## 如何使用：

在修改好whisper.ps1之后，打开Windows PowerShell

```powershell
cd 放置whisper.ps1的文件夹
```

```powershell
./whisper.ps1
```

## 疑难解答

### 为什么我的Whisper只调用了CPU？

Whisper可以调用支持CUDA的GPU，如果你确认GPU已经正确安装并且支持CUDA，请尝试以下步骤：

```python 
pip uninstall torch
```

```python 
pip cache purge
```
然后在[PyTorch官网](https://pytorch.org/get-started/locally/)使用命令安装最新的PyTorch

如：
```python
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

应该就可以正常调用显卡了

### 为什么使用时ffmpeg报错？

可以尝试以下步骤重新安装ffmpeg：

```python
pip uninstall ffmpeg
```

```python 
pip uninstall ffmpeg-python
```

```python
pip install ffmpeg-python
```

### 我应该使用什么模型，各个模型有什么区别？

参见[openai/whisper](https://github.com/openai/whisper#available-models-and-languages)
|  Size  | Parameters | English-only model | Multilingual model | Required VRAM | Relative speed |
|:------:|:----------:|:------------------:|:------------------:|:-------------:|:--------------:|
|  tiny  |    39 M    |     `tiny.en`      |       `tiny`       |     ~1 GB     |      ~32x      |
|  base  |    74 M    |     `base.en`      |       `base`       |     ~1 GB     |      ~16x      |
| small  |   244 M    |     `small.en`     |      `small`       |     ~2 GB     |      ~6x       |
| medium |   769 M    |    `medium.en`     |      `medium`      |     ~5 GB     |      ~2x       |
| large  |   1550 M   |        N/A         |      `large`       |    ~10 GB     |       1x       |

请根据你所拥有GPU的显存大小选择模型，一般来说，越大的模型速度越快，错误率越低。
