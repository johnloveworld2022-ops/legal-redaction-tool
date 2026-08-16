-- 双击打开:启动本地脱敏工具网页界面(在浏览器里操作)。
-- 如果已经开着了,直接打开一个新标签页,不会重复启动。

on run
	set toolDir to "$HOME/法律脱敏工具"
	set pyBin to toolDir & "/venv/bin/python3"
	set appScript to toolDir & "/gui/app.py"
	set logFile to "/tmp/法律脱敏工具_gui.log"
	set shellCmd to "cd " & toolDir & " && nohup " & pyBin & " " & appScript & " > " & logFile & " 2>&1 & disown"

	try
		do shell script shellCmd
	on error errText
		display dialog "启动时出错:" & errText with title "法律脱敏工具" buttons {"好的"} default button "好的"
	end try
end run
