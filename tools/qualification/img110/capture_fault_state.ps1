param(
    [Parameter(Mandatory)]
    [string]$OutputPath,
    [Parameter(Mandatory)]
    [datetime]$StartTime,
    [Parameter(Mandatory)]
    [datetime]$EndTime,
    [Parameter(Mandatory)]
    [string]$QualificationPython
)

$ErrorActionPreference = "Stop"

function Invoke-TextCommand {
    param([string]$FilePath, [string[]]$Arguments)
    try {
        return (& $FilePath @Arguments 2>&1 | Out-String).Trim()
    }
    catch {
        return "ERROR: $($_.Exception.Message)"
    }
}

$eventProviders = "nvlddmkm", "Display", "Kernel-PnP", "WHEA-Logger"
$systemEvents = Get-WinEvent -FilterHashtable @{
    LogName = "System"
    StartTime = $StartTime
    EndTime = $EndTime
} -ErrorAction SilentlyContinue |
    Where-Object { $_.ProviderName -in $eventProviders } |
    ForEach-Object {
        [pscustomobject]@{
            time_created = $_.TimeCreated.ToString("o")
            provider = $_.ProviderName
            event_id = $_.Id
            level = $_.LevelDisplayName
            record_id = $_.RecordId
            message = $_.Message
            xml = $_.ToXml()
        }
    }

$werEvents = Get-WinEvent -FilterHashtable @{
    LogName = "Application"
    StartTime = $StartTime
    EndTime = $EndTime
} -ErrorAction SilentlyContinue |
    Where-Object { $_.ProviderName -match "Windows Error Reporting|WER" } |
    ForEach-Object {
        [pscustomobject]@{
            time_created = $_.TimeCreated.ToString("o")
            provider = $_.ProviderName
            event_id = $_.Id
            level = $_.LevelDisplayName
            record_id = $_.RecordId
            message = $_.Message
            xml = $_.ToXml()
        }
    }

$reliability = Get-CimInstance -ClassName Win32_ReliabilityRecords -ErrorAction SilentlyContinue |
    Where-Object {
        $_.TimeGenerated -ge $StartTime -and $_.TimeGenerated -le $EndTime
    } |
    Select-Object TimeGenerated, SourceName, ProductName, Message, EventIdentifier

$os = Get-CimInstance -ClassName Win32_OperatingSystem
$gpuQuery = Invoke-TextCommand "nvidia-smi" @(
    "--query-gpu=name,driver_version,memory.total,memory.free,memory.used,temperature.gpu,power.draw,clocks.current.graphics,clocks.current.memory,pstate,utilization.gpu",
    "--format=csv,noheader"
)
$runtime = Invoke-TextCommand "nvidia-smi" @()
$packages = Invoke-TextCommand $QualificationPython @(
    "-c",
    "import torch, diffusers, transformers, accelerate, bitsandbytes; print({'python': __import__('sys').version, 'torch': torch.__version__, 'torch_cuda': torch.version.cuda, 'diffusers': diffusers.__version__, 'transformers': transformers.__version__, 'accelerate': accelerate.__version__, 'bitsandbytes': bitsandbytes.__version__})"
)

$record = [pscustomobject]@{
    captured_at = (Get-Date).ToString("o")
    window_start = $StartTime.ToString("o")
    window_end = $EndTime.ToString("o")
    windows = [pscustomobject]@{
        caption = $os.Caption
        version = $os.Version
        build = $os.BuildNumber
    }
    nvidia_smi_query = $gpuQuery
    nvidia_smi_full = $runtime
    qualification_packages = $packages
    system_events = @($systemEvents)
    windows_error_reporting_events = @($werEvents)
    reliability_records = @($reliability)
}

$parent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Output $OutputPath
