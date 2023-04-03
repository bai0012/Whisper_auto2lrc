# 设置要转换的文件夹路径
$folderPath = "C:\Path\To\Audio\Folder"

# 获取要转换的所有音频文件
$audioFiles = Get-ChildItem $folderPath -Recurse -Include "*.mp3", "*.wav", "*.flac", "*.m4a", "*.aac", "*.wma", "*.ogg"

# 设置进度条初始值
$i = 0

# 遍历每个音频文件并进行转换
foreach ($file in $audioFiles) {
    # 更新进度条
    Write-Progress -Activity "Converting audio files..." -Status "Processing file $($file.Name) ($($i+1) of $($audioFiles.Count))" -PercentComplete (($i+1)/$audioFiles.Count*100)
    
    # 检查相应的.lrc文件是否已存在
    $lrcFile = Get-ChildItem $file.DirectoryName -Include "*.lrc" -Recurse | Where-Object { $_.Name -match $file.BaseName }
    if ($lrcFile) {
        Write-Host "Skipping file $($file.Name) as .lrc file already exists."
    }
    else {
        # 执行Whisper命令将音频转换为文本
        whisper --model small --language ja $file.FullName
        
        # 获取相应的.srt文件并调用Python程序将其转换为.lrc文件
        $srtFile = Get-ChildItem $file.DirectoryName -Include "*.srt" -Recurse | Where-Object { $_.Name -match $file.BaseName }
        if ($srtFile) {
            $lrcFile = $srtFile.FullName.Replace(".srt", ".lrc")
            & python srt_to_lrc.py $srtFile.FullName $lrcFile
        }
        
        # 删除由Whisper生成的文件
        $whisperFiles = Get-ChildItem $file.DirectoryName -Include "*.json", "*.tsv", "*.txt", "*.vtt" -Recurse | Where-Object { $_.Name -match $file.BaseName }
        foreach ($whisperFile in $whisperFiles) {
            Remove-Item $whisperFile.FullName -Force
        }
    }
    
    # 增加进度条计数
    $i++
}

# 更新进度条，指示转换已完成
Write-Progress -Activity "Converting audio files..." -Status "Conversion completed." -Completed
