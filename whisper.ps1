# �����û�����Ҫת�����ļ���·��
$folderPath = Read-Host "Please enter the folder path to convert audio files"

# �����û�ѡ�� --model ������ֵ
Write-Host "Please enter the model you want to use"
Write-Host "1. tiny"
Write-Host "2. base"
Write-Host "3. small"
Write-Host "4. medium"
Write-Host "5. large"
$modelChoice = Read-Host "default is small"

# �����û�ѡ������ --model ������ֵ
switch ($modelChoice) {
    "1" { $model = "tiny" }
    "2" { $model = "base" }
    "3" { $model = "small" }
    "4" { $model = "medium" }
    "5" { $model = "large" }
    default { $model = "small" }
}

# �����û����� --language ������ֵ
$language = Read-Host "Please enter the audio's language"

# ��ȡҪת����������Ƶ�ļ�
$audioFiles = Get-ChildItem $folderPath -Recurse -Include "*.mp3", "*.wav"

# ���ý�������ʼֵ
$i = 0

# ����ÿ����Ƶ�ļ�������ת��
foreach ($file in $audioFiles) {
    # ���½�����
    Write-Progress -Activity "Converting audio files..." -Status "Processing file $($file.Name) ($($i+1) of $($audioFiles.Count))" -PercentComplete (($i+1)/$audioFiles.Count*100)
    
    # ��ȡͬ���� .lrc �ļ������������ֱ������ת��
    $lrcFile = $file.DirectoryName + "\" + $file.BaseName + ".lrc"
    if (Test-Path $lrcFile) {
        $i++
        continue
    }
    
    # ִ�� Whisper �����Ƶת��Ϊ�ı�
    whisper --model $model --language $language $file.FullName
    
    # ��ȡͬ���� .srt �ļ������� Python ������ת��Ϊ .lrc �ļ�
    $srtFile = $file.DirectoryName + "\" + $file.BaseName + ".srt"
    if (Test-Path $srtFile) {
        python srt_to_lrc.py "$srtFile"
    }
    
    # ɾ���� Whisper ���ɵ��ļ�
    $whisperFiles = Get-ChildItem $file.DirectoryName -Include "*.json", "*.tsv", "*.txt", "*.vtt" -Recurse | Where-Object { $_.Name -match $file.BaseName }
    foreach ($whisperFile in $whisperFiles) {
        Remove-Item $whisperFile.FullName -Force
    }
    
    # ���ӽ���������
    $i++
}

# ���½�������ָʾת�������
Write-Progress -Activity "Converting audio files..." -Status "Conversion completed." -Completed

# ��ʾ "Finish" ����ɫ������ʾ
Write-Host "Finish" -ForegroundColor Yellow
