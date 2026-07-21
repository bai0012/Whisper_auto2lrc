# Whisper_auto2lrc

[![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/)
<img alt="GitHub Top Language" src="https://img.shields.io/github/languages/top/bai0012/Whisper_auto2lrc" />
<img alt="GitHub Last Commit" src="https://img.shields.io/github/last-commit/bai0012/Whisper_auto2lrc" />
<img alt="GitHub Commit Activity (Year)" src="https://img.shields.io/github/commit-activity/y/bai0012/Whisper_auto2lrc" />

<p align="center">
    <br> English | <a href="README-CN.md">中文</a>


Whisper_auto2lrc uses either OpenAI Whisper or Faster Whisper to convert all media files in a folder (and its subfolders) into one or more subtitle/transcript formats: LRC, SRT, VTT, TXT, TSV, and JSON. Existing output files are never overwritten.

The application provides a PyQt6 desktop interface and supports two interchangeable transcription backends:

- **OpenAI Whisper** uses PyTorch and the system FFmpeg executable.
- **Faster Whisper** uses CTranslate2 and PyAV for faster, memory-efficient inference.


## What can this program do?

It uses the Whisper speech-to-text model released by OpenAI. Users specify a media folder, and the program recursively finds supported files and exports every selected format from a single transcription pass.

It is suitable for users who need to transcribe a large number of audio files into subtitles.


## Screenshots
![](https://raw.githubusercontent.com/bai0012/Whisper_auto2lrc/main/demo.png)


## How to install

First, install Python, which has been tested on Python 3.11

Both supported transcription backends are installed by `requirements.txt`.

## How to use

### Using the source code program

Pull this repo and install the Python dependencies:

```git
git clone https://github.com/bai0012/Whisper_auto2lrc
```

```Powershell
cd Whisper_auto2lrc
```

```python
pip install -r requirements.txt 
```

If you use the OpenAI Whisper backend, download FFmpeg and add the folder containing ffmpeg.exe to the system variables. For example, [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases). Faster Whisper decodes media through PyAV and does not require a system FFmpeg installation.

With the terminal at the base of the project folder, run

```Powershell
python main.py
```

In the window, select the backend, model, folder path, transcription language, and one or more output formats, then click start. OpenAI Whisper with the `base` model is the default. Switching the backend refreshes the model list: both backends expose the standard Whisper models, while Faster Whisper additionally supports optimized, English-only Distil-Whisper models. LRC is selected by default. The transcription language defaults to `auto`, which lets Whisper detect it automatically; leaving the field blank has the same effect.

To avoid downloading a model at processing time, enable **Use Local Model**. For OpenAI Whisper, select a downloaded checkpoint file (normally a `.pt` file). For Faster Whisper, select a complete local **CTranslate2 model directory**, not a PyTorch checkpoint or a Hugging Face cache parent directory. Faster Whisper opens a selected local directory with downloads disabled. The enabled state and path are remembered separately for each backend, and local model paths participate in the in-memory model cache key.

The available output formats are LRC, SRT, VTT, TXT, TSV, and JSON. A media file is transcribed only once for all selected formats. Existing selected outputs are preserved, while any missing selected outputs are created. If multiple media files have the same path and stem (for example, `song.mp3` and `song.wav`), the whole ambiguous group is skipped and reported.

The display language can be switched between English and Simplified Chinese at the top of the window. The application remembers UI settings between launches. It also caches the most recently loaded backend/model/runtime combination, so running the same selection again does not reload it; changing one of those settings replaces the cached model.

Faster Whisper offers `Auto`, `CPU`, and `CUDA` device choices. `Auto` uses CUDA + FP16 when CTranslate2 detects a usable CUDA device and otherwise uses CPU + INT8. If automatic CUDA initialization fails, processing retries on CPU + INT8 and reports the fallback in the log. Choose `CPU` to force the portable path or `CUDA` to require GPU execution.

### REST batch API

Install the API dependencies and start the local service:

```bash
pip install -r requirements-api.txt
python api.py
```

The default address is `http://127.0.0.1:8000`; use `--host` and `--port` to change it. Submit a recursive folder job, then poll its status:

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"folder_path":"/data/audio","backend":"faster-whisper","model":"base","language":"auto","formats":["lrc","srt"],"faster_device":"auto","faster_compute_type":"auto"}'

curl http://127.0.0.1:8000/v1/jobs/JOB_ID
curl -X POST http://127.0.0.1:8000/v1/jobs/JOB_ID/cancel
```

For a local model, add `"local_model_path":"/models/model.pt"` for OpenAI Whisper or a CTranslate2 model directory for Faster Whisper. `GET /v1/capabilities` lists valid backends, models, formats, languages, devices, and precision choices. Other endpoints are `GET /health`, `GET /v1/jobs`, and `GET /v1/jobs/{id}`. Interactive OpenAPI documentation is available at `/docs`.

Jobs use a single in-memory queue (maximum 100 waiting jobs) and run one at a time to avoid concurrent VRAM use. The latest 1,000 job records are retained in memory; `GET /v1/jobs` supports `limit` (maximum 200) and `offset`. Jobs and history are lost when the process restarts. Cancellation is cooperative, so a running job can remain `cancelling` until its current model load or media transcription returns. During shutdown, queued jobs are cancelled and the server waits for the active worker to finish safely.

**Security warning:** the API has no authentication and accepts local filesystem paths. Keep the default loopback address. Do not expose it to a LAN or the public Internet without an authenticated, access-controlled reverse proxy and suitable filesystem isolation.

### Running the unit tests

The tests use fake Whisper models and do not require real audio files or model downloads:

```Powershell
pip install -r requirements-dev.txt
python -m ruff check main.py api.py tests
python -m pytest -s tests
```

### Windows release package

GitHub releases provide `Whisper_auto2lrc-windows-x64.zip`. It is a PyInstaller **onedir** build: extract the entire archive, keep all bundled files together, and launch `Whisper_auto2lrc.exe` from the extracted folder. The directory layout is intentional and avoids the startup and temporary-extraction overhead of a one-file executable.

## Troubleshooting

### Why is the selected backend only using the CPU?

OpenAI Whisper uses PyTorch. If it does not detect CUDA, install the CUDA build that matches your graphics driver by following the [PyTorch installation guide](https://pytorch.org/get-started/locally/).

```python 
pip uninstall torch
```

```python 
pip cache purge
```
Then install the appropriate PyTorch build, for example:

For example:
```python
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

Faster Whisper uses CTranslate2. Its current NVIDIA backend requires CUDA 12 cuBLAS and cuDNN 9; see the [Faster Whisper GPU instructions](https://github.com/SYSTRAN/faster-whisper#gpu). The application falls back to CPU + INT8 when CUDA detection fails.

### Why is FFmpeg giving an error when I use it?

Only the OpenAI Whisper backend requires the system FFmpeg executable. Run `ffmpeg -version` in a new terminal to verify that it is installed and visible on `PATH`; if the command is not found, install an FFmpeg build and add its `bin` directory to `PATH`, then restart the application. The Python package named `ffmpeg-python` is not an FFmpeg executable and is neither required nor a substitute for this installation.

### Which model should I choose and what are the differences between each model?

Refer to [openai/whisper](https://github.com/openai/whisper#available-models-and-languages)
|  Size  | Parameters | English-only model | Multilingual model | Required VRAM | Relative speed |
|:------:|:----------:|:------------------:|:------------------:|:-------------:|:--------------:|
|  tiny  |    39 M    |     `tiny.en`      |       `tiny`       |     ~1 GB     |      ~10x      |
|  base  |    74 M    |     `base.en`      |       `base`       |     ~1 GB     |      ~7x       |
| small  |   244 M    |     `small.en`     |      `small`       |     ~2 GB     |      ~4x       |
| medium |   769 M    |    `medium.en`     |      `medium`      |     ~5 GB     |      ~2x       |
| large  |   1550 M   |        N/A         |      `large`       |    ~10 GB     |       1x       |
| turbo  |   809 M    |        N/A         |      `turbo`       |     ~6 GB     |      ~8x       |

Choose a model based on available VRAM, desired accuracy, and processing speed. Larger models are generally more accurate but slower and more memory intensive; `turbo` is a strong default when balancing speed and accuracy. Faster Whisper also offers Distil-Whisper models and INT8 execution for lower memory use.

### What should I enter in the language input box?

Whisper supports speech-to-text in multiple languages, commonly used ones include:
|  Language  | Code |
|:-----:|:---:|
|  Chinese  | zh |
|  English  | en |
|  Russian  | ru |
|  Japanese  | ja |
|  Korean  | ko |
|  German  | de |
|  Italian  | it |

For more languages, refer to: [whisper/tokenizer.py](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bai0012/Whisper_auto2lrc&type=Date)](https://star-history.com/#bai0012/Whisper_auto2lrc&Date)

This program was completed under the guidance of GPT-4, with special thanks to [chshkhr](https://github.com/chshkhr) for their contributions.
