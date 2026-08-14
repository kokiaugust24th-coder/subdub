param(
    [Parameter(Mandatory = $true)][string]$Manifest,
    [string]$Voice = "",
    [int]$SampleRate = 22050
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$json  = [System.IO.File]::ReadAllText($Manifest, [System.Text.Encoding]::UTF8)
$items = $json | ConvertFrom-Json

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($Voice -ne "") {
    try {
        $synth.SelectVoice($Voice)
    } catch {
        Write-Error "voice not found: $Voice"
        exit 2
    }
}

$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    $SampleRate,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)

$n = 0
foreach ($it in $items) {
    $synth.Rate = [int]$it.rate
    $synth.SetOutputToWaveFile([string]$it.out, $fmt)
    $synth.Speak([string]$it.text)
    $n++
}

# Release the last wave file handle before exiting.
$synth.SetOutputToNull()
$synth.Dispose()

Write-Output "rendered=$n"
