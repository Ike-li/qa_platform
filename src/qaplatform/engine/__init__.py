from __future__ import annotations

__all__ = ["DockerBackend", "LogStream", "RunExecutor"]


def __getattr__(name: str):
    if name == "DockerBackend":
        from qaplatform.engine.docker_backend import DockerBackend

        return DockerBackend
    if name == "LogStream":
        from qaplatform.infra.log_stream import LogStream

        return LogStream
    if name == "RunExecutor":
        from qaplatform.engine.executor import RunExecutor

        return RunExecutor
    raise AttributeError(name)
