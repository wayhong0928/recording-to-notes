# Synthesize each line with Windows OneCore voices (WinRT SpeechSynthesizer), fully offline.
# Usage: powershell -File synth_tts.ps1 -JobFile jobs.json -OutDir dir
# jobs.json: [{"id": "001", "voice": "Yating", "text": "..."}]
param([Parameter(Mandatory)][string]$JobFile, [Parameter(Mandatory)][string]$OutDir)
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]

$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1

function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$voices = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
$jobs = [IO.File]::ReadAllText($JobFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
New-Item -ItemType Directory -Force $OutDir | Out-Null

foreach ($j in $jobs) {
    $voice = $voices | Where-Object { $_.DisplayName -match $j.voice } | Select-Object -First 1
    if (-not $voice) { throw "voice not found: $($j.voice)" }
    $synth.Voice = $voice
    $stream = Await ($synth.SynthesizeTextToStreamAsync($j.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $size = [uint32]$stream.Size
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $null = Await ($reader.LoadAsync($size)) ([uint32])
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes((Join-Path $OutDir "$($j.id).wav"), $bytes)
    $reader.Dispose(); $stream.Dispose()
}
Write-Output "synthesized $(@($jobs).Count) lines"
