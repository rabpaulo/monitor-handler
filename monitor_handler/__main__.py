"""Command line entry point: `monitor-handler` or `python -m monitor_handler`."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .backends import BACKENDS, BackendError, detect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="monitor-handler",
        description="Configura resolução, posição, orientação, Hz, VRR e HDR dos monitores (X11 e Wayland).")
    parser.add_argument("--backend", choices=[b.id for b in BACKENDS],
                        help="força um backend em vez de detectar automaticamente")
    parser.add_argument("--dry-run", action="store_true",
                        help="abre a GUI mas só mostra os comandos, sem aplicar nada")
    parser.add_argument("--list", action="store_true", help="lista os monitores detectados e sai")
    parser.add_argument("--print-commands", action="store_true",
                        help="mostra o comando que reproduz a configuração atual e sai")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    try:
        backend = detect(args.backend)
        if args.list or args.print_commands:
            outputs = backend.list_outputs()
            if args.list:
                print(f"Backend: {backend.name}")
                for o in outputs:
                    flags = [f for f, on in (("principal", o.primary), ("desligado", not o.enabled),
                                             ("VRR", o.vrr), ("HDR", o.hdr)) if on]
                    print(f"{o.name:10} {o.width}x{o.height}@{o.refresh:.2f}Hz +{o.x}+{o.y} "
                          f"rot={o.rotation} escala={o.scale:g} {o.description}"
                          + (f" [{', '.join(flags)}]" if flags else ""))
            if args.print_commands:
                print(backend.preview(outputs))
            return 0
    except BackendError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1

    from .gui.app import run_gui
    return run_gui(backend, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
