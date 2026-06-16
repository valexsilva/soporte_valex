# Prueba de autenticacion contra ServiceNow (Table API).
# Uso (Basic):  ./scripts/test_servicenow.ps1
#      (OAuth):  ./scripts/test_servicenow.ps1 -Auth oauth
# Solo LEE (no crea nada). Las credenciales se piden en cuadros seguros y
# NO se imprimen ni se guardan.

param(
    [string]$Instance = "https://santander.service-now.com",
    [ValidateSet("basic", "oauth")]
    [string]$Auth = "basic"
)

$uri = "$Instance/api/now/table/sys_user?sysparm_limit=1&sysparm_fields=user_name,name"

function Show-Failure($err) {
    Write-Host "FALLO:" $err.Exception.Message -ForegroundColor Red
    if ($err.Exception.Response) {
        $code = [int]$err.Exception.Response.StatusCode
        Write-Host ("HTTP " + $code) -ForegroundColor Yellow
        if ($code -eq 401 -or $code -eq 403) {
            Write-Host "=> Autenticacion rechazada (SSO/MFA, sin acceso REST, o credenciales OAuth invalidas)." -ForegroundColor Yellow
        }
    }
}

try {
    if ($Auth -eq "oauth") {
        # 1) Pedir client_id/secret de la app OAuth y el usuario.
        $app  = Get-Credential -Message "OAuth APP: client_id (usuario) y client_secret (contrasena)"
        $user = Get-Credential -Message "Usuario ServiceNow (tu cuenta)"
        $tokenUrl = "$Instance/oauth_token.do"
        $body = @{
            grant_type    = "password"
            client_id     = $app.UserName
            client_secret = $app.GetNetworkCredential().Password
            username      = $user.UserName
            password      = $user.GetNetworkCredential().Password
        }
        $tok = Invoke-RestMethod -Method Post -Uri $tokenUrl -Body $body -ErrorAction Stop
        if (-not $tok.access_token) { throw "Respuesta sin access_token." }
        Write-Host "OK - token OAuth obtenido." -ForegroundColor Green
        $headers = @{ Authorization = "Bearer " + $tok.access_token }
        $r = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -ErrorAction Stop
    }
    else {
        $cred = Get-Credential -Message "ServiceNow ($Instance)"
        $r = Invoke-RestMethod -Method Get -Uri $uri -Credential $cred -ErrorAction Stop
    }
    Write-Host "OK - autenticacion valida. Ejemplo de registro:" -ForegroundColor Green
    $r.result | Format-List
}
catch {
    Show-Failure $_
}
