# 请求用户输入要转换的文件夹路径
$folderPath = Read-Host "Please enter the folder path to convert audio files"

# 请求用户选择 --model 参数的值
Write-Host "Please enter the model you want to use"
Write-Host "1. tiny"
Write-Host "2. base"
Write-Host "3. small"
Write-Host "4. medium"
Write-Host "5. large"
$modelChoice = Read-Host "default is small"

# 根据用户选择设置 --model 参数的值
switch ($modelChoice) {
    "1" { $model = "tiny" }
    "2" { $model = "base" }
    "3" { $model = "small" }
    "4" { $model = "medium" }
    "5" { $model = "large" }
    default { $model = "small" }
}

# 请求用户输入 --language 参数的值
$language = Read-Host "Please enter the audio's language"

# 获取要转换的所有音频文件
$audioFiles = Get-ChildItem $folderPath -Recurse -Include "*.mp3", "*.wav"

# 设置进度条初始值
$i = 0

# 遍历每个音频文件并进行转换
foreach ($file in $audioFiles) {
    # 更新进度条
    Write-Progress -Activity "Converting audio files..." -Status "Processing file $($file.Name) ($($i+1) of $($audioFiles.Count))" -PercentComplete (($i+1)/$audioFiles.Count*100)
    
    # 获取同名的 .lrc 文件，如果存在则直接跳过转换
    $lrcFile = $file.DirectoryName + "\" + $file.BaseName + ".lrc"
    if (Test-Path $lrcFile) {
        $i++
        continue
    }
    
    # 执行 Whisper 命令将音频转换为文本
    whisper --model $model --language $language $file.FullName
    
    # 获取同名的 .srt 文件并调用 Python 程序将其转换为 .lrc 文件
    $srtFile = $file.DirectoryName + "\" + $file.BaseName + ".srt"
    if (Test-Path $srtFile) {
        python srt_to_lrc.py "$srtFile"
    }
    
    # 删除由 Whisper 生成的文件
    $whisperFiles = Get-ChildItem $file.DirectoryName -Include "*.json", "*.tsv", "*.txt", "*.vtt" -Recurse | Where-Object { $_.Name -match $file.BaseName }
    foreach ($whisperFile in $whisperFiles) {
        Remove-Item $whisperFile.FullName -Force
    }
    
    # 增加进度条计数
    $i++
}

# 更新进度条，指示转换已完成
Write-Progress -Activity "Converting audio files..." -Status "Conversion completed." -Completed

# 显示 "Finish" 并黄色高亮显示
Write-Host "Finish" -ForegroundColor Yellow
