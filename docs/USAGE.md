# HulunGuard Usage

## Open A Desktop HulunGauge

```powershell
python .\hulun.py open --conversation "Codex long task" --group "My Project" --widget
```

- Single-click and drag the bar to move it.
- Double-click the bar to close it.
- Green: continue.
- Yellow: checkpoint or calibrate.
- Red: do not claim completion.

## Update A Conversation

```powershell
python .\hulun.py update --id M1 --score 70 --summary "Tool failed and no evidence yet" --reason "Unresolved failure"
python .\hulun.py update --id M1 --delta -25 --summary "Tests passed and evidence was recorded"
python .\hulun.py update --id M1 --group "New Project Group"
```

## Open The Project Board

```powershell
python .\hulun.py board --serve --open
```

This opens:

```text
http://127.0.0.1:8766/board.html
```

The board shows all active monitors and group-level risk averages.

## Universal Agent Prompt

Generate a pasteable startup code for any agent:

```powershell
python .\hulun.py prompt --conversation "Claude task" --group "Research"
```

Paste the output into the target agent. It starts with:

```text
#HULUN_ON
```

Any agent that can run shell commands can then open its own widget and update the same board.
