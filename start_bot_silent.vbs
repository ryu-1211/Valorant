Set ws = CreateObject("WScript.Shell")
ws.Run "cmd /c cd /d ""C:\Users\ozeki\Desktop\claude\valorant"" && python bot.py >> logs\bot.log 2>&1", 0, False
