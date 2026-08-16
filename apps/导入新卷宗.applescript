-- 拖动一个或多个卷宗文件(PDF/docx)到这个 App 图标上即可。
-- 会询问一次案件名称,然后自动完成:转文字/OCR -> 脱敏检测 -> 替换。
-- 如果全部内容都没有需要人工核实的地方,会直接导出可用文件;
-- 否则会提示你先查看审核报告,再运行「批准并导出」。

on open theFiles
	try
		set caseName to text returned of (display dialog "这些文件属于哪个案件?(填案号或简称,同一案件请每次填一样的)" default answer "" with title "导入新卷宗")
	on error number -128
		return
	end try

	if caseName is "" then
		display dialog "案件名称不能为空,已取消。" buttons {"好的"} default button "好的"
		return
	end if

	set filePaths to ""
	repeat with f in theFiles
		set filePaths to filePaths & " " & quoted form of POSIX path of f
	end repeat

	set toolDir to "$HOME/法律脱敏工具"
	set pyBin to toolDir & "/venv/bin/python3"
	set pyScript to toolDir & "/process_case.py"
	set shellCmd to pyBin & " " & pyScript & " " & quoted form of caseName & filePaths

	try
		set resultText to do shell script shellCmd
	on error errText
		set resultText to "处理时出错:" & errText
	end try

	display dialog resultText with title "处理完成 - " & caseName buttons {"好的"} default button "好的"
end open
