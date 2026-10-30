param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speechSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $speechSynth.SelectVoice('Microsoft Huihui Desktop')
    $speechSynth.Rate = -1
    $audioFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $speechSynth.SetOutputToWaveFile($OutputPath, $audioFormat)
    $speechSynth.Speak('请介绍一下模型预测控制的基本原理。为什么要进行闭环控制？')
} finally {
    $speechSynth.Dispose()
}
