-- 双击运行。看完审核报告、确认没问题之后,用这个把候选脱敏文件正式导出到
-- 「03_已批准可上传」文件夹——只有这个文件夹里的文件才可以复制给 AI。

on run
	try
		set caseName to text returned of (display dialog "要批准导出哪个案件?(填案号或简称)" default answer "" with title "批准并导出")
	on error number -128
		return
	end try

	if caseName is "" then
		display dialog "案件名称不能为空,已取消。" buttons {"好的"} default button "好的"
		return
	end if

	set toolDir to "$HOME/法律脱敏工具"
	set pyBin to toolDir & "/venv/bin/python3"
	set pyScript to toolDir & "/approve_export.py"
	set shellCmd to pyBin & " " & pyScript & " " & quoted form of caseName

	try
		set resultText to do shell script shellCmd
	on error errText
		set resultText to "导出时出错:" & errText
	end try

	display dialog resultText with title "批准并导出 - " & caseName buttons {"好的"} default button "好的"
end run
