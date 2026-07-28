import argparse
import getpass
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin"); create.add_argument("--username", required=True)
    args = parser.parse_args()
    return create_admin(args.username) if args.command == "create-admin" else 2


if __name__ == "__main__": raise SystemExit(main())
