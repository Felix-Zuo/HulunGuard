# OpenClaw Integration

HulunGuard includes an OpenClaw hook that injects a short monitoring reminder during agent bootstrap.

Install:

```powershell
.\scripts\Install-OpenClawHook.ps1
```

Verify:

```powershell
openclaw hooks list --json
```

Expected fields for `hulunguard`:

- `eligible: true`
- `loadable: true`
- `disabled: false`
- events include `agent:bootstrap`

The hook does not restart the gateway and does not run dangerous commands. It only injects a virtual reminder file telling agents to use HulunGuard for long-running work.
