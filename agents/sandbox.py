"""
agents/sandbox.py
-----------------
Ruby – Docker Agent Sandbox

Runs an agent in an isolated Docker container.  The host sends a task JSON
over stdin; the container runs the agent and writes the AgentResult JSON to stdout.

Security model
--------------
  - Each sandboxed run spins up a fresh, ephemeral container (--rm)
  - Network access is disabled by default (--network none)
  - CPU + memory limits are enforced
  - The container image includes only the agent's dependencies
  - No access to host filesystem (bind mounts are optional + explicit)

Requirements
------------
  - Docker CLI on host PATH
  - A Ruby agent Docker image (see agents/Dockerfile)

Usage
-----
    sandbox = AgentSandbox(image="ruby-agent:latest")
    result  = await sandbox.run_task(task="Summarise the article at ...", agent_name="researcher")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict
from typing import Optional

from .base import AgentResult

logger = logging.getLogger("ruby.agents.sandbox")

# ---------------------------------------------------------------------------
# Docker availability check
# ---------------------------------------------------------------------------

async def _docker_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# AgentSandbox
# ---------------------------------------------------------------------------

class AgentSandbox:
    """
    Runs Ruby sub-agents inside Docker containers for isolation.

    Parameters
    ----------
    image       : str   — Docker image to use (default: "ruby-agent:latest")
    network     : str   — Docker network mode (default: "none" = no internet)
    cpu_limit   : str   — Docker --cpus value   (default: "0.5")
    mem_limit   : str   — Docker --memory value (default: "512m")
    timeout     : float — Max seconds per run   (default: 120)
    volumes     : dict  — Optional host:container bind mounts
    env         : dict  — Extra environment variables passed to container
    """

    DEFAULT_IMAGE = "ruby-agent:latest"

    def __init__(
        self,
        image:     str   = DEFAULT_IMAGE,
        network:   str   = "none",
        cpu_limit: str   = "0.5",
        mem_limit: str   = "512m",
        timeout:   float = 120.0,
        volumes:   dict[str, str] | None = None,
        env:       dict[str, str] | None = None,
    ):
        self.image     = image
        self.network   = network
        self.cpu_limit = cpu_limit
        self.mem_limit = mem_limit
        self.timeout   = timeout
        self.volumes   = volumes or {}
        self.env       = env or {}
        self._docker_ok: Optional[bool] = None

    async def _check_docker(self) -> bool:
        if self._docker_ok is None:
            self._docker_ok = await _docker_available()
        return self._docker_ok

    async def run_task(
        self,
        task:       str,
        agent_name: str  = "general",
        context:    dict | None = None,
    ) -> AgentResult:
        """
        Run a task in a Docker container and return the AgentResult.
        Falls back to a descriptive error if Docker is unavailable.
        """
        if not await self._check_docker():
            return AgentResult(
                agent_name=agent_name, task=task, output="",
                error="Docker is not available on this host.",
            )

        input_payload = json.dumps({
            "task":       task,
            "agent_name": agent_name,
            "context":    context or {},
        })

        cmd = self._build_docker_cmd(agent_name)

        logger.info("[Sandbox] Running agent %r in Docker: %s", agent_name, self.image)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_payload.encode()),
                timeout=self.timeout,
            )

            if stderr:
                logger.debug("[Sandbox] stderr: %s", stderr.decode(errors="replace"))

            if proc.returncode != 0:
                return AgentResult(
                    agent_name=agent_name, task=task, output="",
                    error=f"Container exited {proc.returncode}: {stderr.decode(errors='replace')[:500]}",
                )

            data = json.loads(stdout.decode())
            return AgentResult(**data)

        except asyncio.TimeoutError:
            proc.kill()
            return AgentResult(
                agent_name=agent_name, task=task, output="",
                error=f"Agent sandbox timed out after {self.timeout}s.",
            )
        except Exception as exc:
            return AgentResult(
                agent_name=agent_name, task=task, output="",
                error=str(exc),
            )

    def _build_docker_cmd(self, agent_name: str) -> list[str]:
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", self.network,
            "--cpus",    self.cpu_limit,
            "--memory",  self.mem_limit,
            "--pids-limit", "64",
            "--security-opt", "no-new-privileges",
        ]
        for host_path, container_path in self.volumes.items():
            cmd += ["-v", f"{host_path}:{container_path}:ro"]
        for key, val in self.env.items():
            cmd += ["-e", f"{key}={val}"]
        cmd += [self.image, agent_name]
        return cmd

    async def is_available(self) -> bool:
        return await self._check_docker()

    async def pull_image(self) -> bool:
        """Pull/update the Ruby agent Docker image."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "pull", self.image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                logger.error("[Sandbox] docker pull failed: %s", err.decode())
                return False
            logger.info("[Sandbox] Image pulled: %s", self.image)
            return True
        except Exception as exc:
            logger.error("[Sandbox] pull error: %s", exc)
            return False
