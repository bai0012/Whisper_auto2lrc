# Whisper_auto2lrc

使用whisper通过python程序实现文件夹下（及子文件夹）所有音频文件转换为.lrc字幕文件，若已存在lrc字幕文件，则自动跳过

### 目前程序还没有达到预期的效果，正在修复

## 这个程序能干什么？

它可以使用openai发布的whisper语音转文字模型，由用户制定需要处理的音频文件夹，程序将自动递归搜索所有文件夹音频文件，并且将其转录为lrc格式的字幕文件。

适合有大量音频文件需要转录为字幕的用户。

后续将加入自动翻译。

## 如何安装：

首先安装python，推荐使用python3.10.10

然后根据whisper的要求安装python依赖库[openai/whisper](https://github.com/openai/whisper#setup)

然后在powershell中运行下列指令：


```git
git clone https://github.com/bai0012/Whisper_auto2lrc
```

```Powershell
cd Whisper_auto2lrc
```

```python
pip install -r requirements.txt 
```


## 如何使用：

在Powershell路径处于项目文件夹的基础上，运行

```Powershell
python main.py
```

根据提示输入要处理的音频文件夹，选择模型，并选择目标语言，等待处理完成即可。

![](https://raw.githubusercontent.com/bai0012/Whisper_auto2lrc/main/demo.png)

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

(例如，你拥有RTX3060 12G，那你就可以选择large模型，而你拥有的是GTX 1050ti 4G，那你就只能使用small模型了)

### 在提示“请求用户输入语言”时，我应该输入什么？

whsiper支持多种语言的语音转文字，常用的有：
|  语言  | 代码 |
|:-----:|:---:|
|  汉语  | zh |
|  英语  | en |
|  俄语  | ru |
|  日语  | ja |
|  韩语  | ko |
|  德语  | de |
|  意大利语  | it |

更多语言，请参考：[whisper/tokenizer.py](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py)
(本程序在ChatGPT指导下生成)
