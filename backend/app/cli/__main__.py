import argparse
import getpass
import sys
import asyncio
from app.database.session import SessionLocal
from app.services.user_service import UserService


def create_admin(username: str) -> int:
    password = getpass.getpass("Senha: ")
    confirmation = getpass.getpass("Confirme a senha: ")
    if password != confirmation:
        print("As senhas nao coincidem.", file=sys.stderr); return 2
    with SessionLocal() as db:
        try: user = UserService(db).create_first_admin(username, password)
        except Exception as exc:
            print(f"Nao foi possivel criar o administrador: {getattr(exc, 'message', 'erro controlado')}.", file=sys.stderr); return 1
    print(f"Administrador criado: {user.username}"); return 0


def reload_norm_limits() -> int:
    from app.integrations.pi.manager import shutdown_pi_provider, startup_pi_provider
    from app.services.norm_limit_reload_service import reload_norm_limits as run_reload
    import logging

    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    async def run():
        await startup_pi_provider()
        try:
            return await run_reload()
        finally:
            await shutdown_pi_provider()

    try:
        results = asyncio.run(run())
    except Exception as exc:
        print(f"Recarga nao iniciada: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    total_samples = sum(item.samples for item in results)
    failures = [item for item in results if item.status != "COMPLETE"]
    for item in results:
        print(f"{item.server}/{item.tag_name}: {item.status}; amostras={item.samples}; seed={item.seeded}; erro={item.error or '-'}")
    print(f"Total: tags={len(results)} falhas={len(failures)} amostras={total_samples}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin"); create.add_argument("--username", required=True)
    commands.add_parser("reload-norm-limits", help="Materializa uma vez os ultimos 7 dias de limites visuais RECORDED")
    args = parser.parse_args()
    if args.command == "create-admin":
        return create_admin(args.username)
    if args.command == "reload-norm-limits":
        return reload_norm_limits()
    return 2


if __name__ == "__main__": raise SystemExit(main())
