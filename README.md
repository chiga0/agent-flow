# AgentFlow

AgentFlow is a self-hostable Agent runtime for long-running cloud execution,
human approval, worker scheduling, audit trails, and recovery.

Online site: https://chiga0.github.io/agent-research/

## Reading path

Start with the learner-facing docs before jumping into the design notes:

- [认识 AgentFlow](docs/getting-started.md)
- [核心概念](docs/concepts.md)
- [使用管理台](docs/user-guide.md)
- [自我部署](docs/self-deploy.md)
- [排障手册](docs/troubleshooting.md)
- [产品可用性审计](docs/implementation/product-usability-audit.md)

## Local preview

```bash
python3 -m pip install -r requirements.txt
mkdocs serve
```

## AgentFlow Runtime

The runtime lives in [runtime](runtime/). It provides a stdlib Run Manager with
`/runs`, `/missions`, `/workers`, `/executors`, `/auth`, `/access`, and
artifact/audit APIs over a pluggable SAEU adapter boundary.

```bash
python3 -m runtime.cloud_agents_runtime --host 127.0.0.1 --port 8765
python3 -m unittest discover -s runtime/tests
```
