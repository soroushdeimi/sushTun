# Thin wrapper around the cross-platform fetcher (keeps the old entrypoint).
param([switch]$Force)
$root = Split-Path -Parent $PSScriptRoot
$args = @((Join-Path $PSScriptRoot "fetch_deps.py"))
if ($Force) { $args += "--force" }
& python @args
