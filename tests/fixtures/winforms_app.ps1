# Aplicación WinForms de pruebas para UI Automation. Registra cada acción en el archivo $env:BANCO_LOG.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$log = $env:BANCO_LOG
function Log($t) { [IO.File]::AppendAllText($log, $t + "`n", [Text.Encoding]::UTF8) }

$f = New-Object System.Windows.Forms.Form
$f.Text = "Banco de Pruebas UIA"; $f.Width = 440; $f.Height = 340
$f.StartPosition = "Manual"; $f.Location = New-Object System.Drawing.Point(40, 40); $f.TopMost = $true

$lbl = New-Object System.Windows.Forms.Label
$lbl.Name = "estado"; $lbl.Text = "Estado: inicial"; $lbl.Left = 10; $lbl.Top = 10; $lbl.Width = 380

$tb = New-Object System.Windows.Forms.TextBox
$tb.Name = "nombre"; $tb.AccessibleName = "Nombre"; $tb.Left = 10; $tb.Top = 40; $tb.Width = 250

$pw = New-Object System.Windows.Forms.TextBox
$pw.Name = "clave"; $pw.AccessibleName = "Clave"; $pw.UseSystemPasswordChar = $true; $pw.Left = 10; $pw.Top = 75; $pw.Width = 250; $pw.Text = "no-leer-esto"

$btn = New-Object System.Windows.Forms.Button
$btn.Name = "btnSaludar"; $btn.Text = "Saludar"; $btn.Left = 10; $btn.Top = 110; $btn.Width = 100
$btn.Add_Click({ $lbl.Text = "Estado: Hola, " + $tb.Text; Log ("saludar:" + $tb.Text) })

$chk = New-Object System.Windows.Forms.CheckBox
$chk.Name = "chkAceptar"; $chk.Text = "Aceptar"; $chk.Left = 10; $chk.Top = 150
$chk.Add_CheckedChanged({ Log ("aceptar:" + $chk.Checked) })

$off = New-Object System.Windows.Forms.Button
$off.Name = "btnOff"; $off.Text = "Bloqueado"; $off.Left = 130; $off.Top = 110; $off.Width = 100; $off.Enabled = $false

$f.Controls.AddRange(@($lbl, $tb, $pw, $btn, $chk, $off))
$f.Add_Shown({ Log "listo" })
[void]$f.ShowDialog()
