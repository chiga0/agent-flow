# Vendored Qwen Code WebShell

The client uses the upstream Qwen Code WebShell as its primary UI surface.
The two package archives in this directory were built from the local upstream
checkout at commit `837358f63`:

- `@qwen-code/web-shell` 0.20.0
- `@qwen-code/webui` 0.20.0

Upstream: <https://github.com/QwenLM/qwen-code> (Apache-2.0).

They are committed because `@qwen-code/web-shell` is not published as a stable
npm package. Keeping the exact archives in the repository makes local, NAS,
Docker, and CI installs reproducible. When upgrading, build the upstream
workspace, run `npm pack` in each package, replace both archives, update this
commit reference, then run `npm install`, `npm test`, and `npm run build` here.
