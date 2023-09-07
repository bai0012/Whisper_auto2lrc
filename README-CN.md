# Whisper_auto2lrc

使用whisper通过python程序实现文件夹下（及子文件夹）所有音频文件转换为.lrc字幕文件，若已存在lrc字幕文件，则自动跳过

### 现在整合了 [Faster Whisper](https://github.com/guillaumekln/faster-whisper) 以实现更快速的推理和更低的显存使用量！（约4倍推理速度和少一半的显存需求）

### 推荐使用 [Faster Whisper](https://github.com/guillaumekln/faster-whisper) 

## 这个程序能干什么？

它可以使用openai发布的whisper语音转文字模型，由用户制定需要处理的音频文件夹，程序将自动递归搜索所有文件夹音频文件，并且将其转录为lrc格式的字幕文件。

适合有大量音频文件需要转录为字幕的用户。

后续将加入自动翻译。

## 程序截图
![](https://raw.githubusercontent.com/bai0012/Whisper_auto2lrc/main/demo2.0.png)

使用Faster Whisper的情况
![](https://raw.githubusercontent.com/bai0012/Whisper_auto2lrc/main/demo2.0_1.png)

## 如何安装

首先安装python，已经在python3.10.11上测试

然后根据whisper的要求安装python依赖库[openai/whisper](https://github.com/openai/whisper#setup):

```python
pip install git+https://github.com/openai/whisper.git 
```

若要使用Faster Whisper，需同时安装Faster Whisper命令行版本[Softcatala/whisper-ctranslate2](https://github.com/Softcatala/whisper-ctranslate2#installation)的依赖项
```python
pip install -U whisper-ctranslate2
```


## 如何使用

### 使用源代码程序

拉取该repo，并且安装Python依赖项：

```git
git clone https://github.com/bai0012/Whisper_auto2lrc
```


```Powershell
cd Whisper_auto2lrc
```

```python
pip install -r requirements.txt 
```

使终端处于项目文件夹的基础上，运行

```Powershell
python main.py
```

若要使用Faster Whisper，运行

```Powershell
python main_faster-whisper.py
```
（Faster Whisper默认打开了[Silero VAD 滤波器](https://github.com/snakers4/silero-vad)来跳过超过两秒的空白音频段，以及使用颜色来表示各字符的置信度，红色为置信度低，绿色为置信度高）


在窗口中选择文件夹路径，选择要使用的模型大小，输入要处理的音频文件语言，点击开始即可


## 疑难解答

### Faster Whisper和原版Whisper的区别在哪？

faster-whisper 是使用 CTranslate2 重新实现的 OpenAI 的 Whisper 模型，CTranslate2 是一个用于 Transformer 模型的快速推理引擎。

这个实现比openai/whisper快4倍，同时使用更少的内存和显存，而且准确度相同。

根据[guillaumekln/faster-whisper](https://github.com/guillaumekln/faster-whisper#benchmark)的统计，使用large-v2模型在NVIDIA Tesla V100S上的性能提升如下表所示：

| 实现方式 | 精度 | 波束大小 | 所需时间 | 最大所需GPU显存 | 最大所需内存 |
| --- | --- | --- | --- | --- | --- |
| openai/whisper | fp16 | 5 | 4m30s | 11325MB | 9439MB |
| faster-whisper | fp16 | 5 | 54s | 4755MB | 3244MB |
| faster-whisper | int8 | 5 | 59s | 3091MB | 3117MB |

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

### 我应该选择什么模型，各个模型有什么区别？

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

Faster Whisper使用相同的模型，所需的显存量更小，请自行尝试。

(Faster Whisper在1050ti 4G上甚至能跑large模型，只不过有时会爆显存，估计6G显存就足以跑动large模型)

### 在语言输入框中，我应该输入什么？

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

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bai0012/Whisper_auto2lrc&type=Date)](https://star-history.com/#bai0012/Whisper_auto2lrc&Date)


(本程序在GPT 4指导下完成)
