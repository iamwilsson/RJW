$ErrorActionPreference = 'Stop'
$secureKey = Read-Host -Prompt 'Clave del desarrollador (mínimo 16 caracteres)' -AsSecureString
if ($secureKey.Length -lt 16) {
  throw 'La clave debe tener al menos 16 caracteres.'
}

$pointer = [IntPtr]::Zero
try {
  $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
  $env:RJW_DEVELOPER_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  python (Join-Path $PSScriptRoot 'server.py')
}
finally {
  if ($pointer -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
  }
  Remove-Item Env:RJW_DEVELOPER_KEY -ErrorAction SilentlyContinue
}
