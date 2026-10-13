"""Common backend interface."""

from __future__ import annotations

import shlex
import shutil
import subprocess

from ..model import Output


class BackendError(RuntimeError):
    pass


def run(cmd: list[str], check: bool = True) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise BackendError(f"Comando não encontrado: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise BackendError(f"Tempo esgotado executando: {shlex.join(cmd)}") from e
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        raise BackendError(f"{shlex.join(cmd)}\n{msg}")
    return proc.stdout


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


class Backend:
    #: Short id used on the command line (--backend)
    id = "base"
    #: Name shown in the GUI
    name = "Base"
    #: Features from model.FEAT_* this backend can change
    features: frozenset[str] = frozenset()
    #: True when the compositor itself asks the user to confirm/revert
    self_confirming = False

    @classmethod
    def available(cls) -> bool:
        raise NotImplementedError

    def list_outputs(self) -> list[Output]:
        raise NotImplementedError

    def commands(self, outputs: list[Output]) -> list[list[str]]:
        """Shell commands that produce the given configuration."""
        raise NotImplementedError

    def apply(self, outputs: list[Output]) -> None:
        for cmd in self.commands(outputs):
            run(cmd)

    def preview(self, outputs: list[Output]) -> str:
        """What `apply` will do, shown to the user before applying."""
        return "\n".join(shlex.join(c) for c in self.commands(outputs))

    def script(self, outputs: list[Output]) -> str:
        """Text the user can keep to restore this configuration on login."""
        lines = ["#!/bin/sh", "# Gerado pelo Monitor Handler"]
        lines += [shlex.join(c) for c in self.commands(outputs)]
        return "\n".join(lines) + "\n"

    def persist_hint(self) -> str:
        return "Execute o script salvo ao iniciar a sessão."

    def supports(self, feature: str) -> bool:
        return feature in self.features
