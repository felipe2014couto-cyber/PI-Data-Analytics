"""Local user lifecycle and authorization invariants."""
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import UserCreate, UserUpdate


def normalized_username(username: str) -> str:
    return username.strip().casefold()


class UserService:
    def __init__(self, db: Session): self.db = db

    def _commit(self) -> None:
        try: self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("Nome de usuario ja existe.") from exc

    def get(self, user_id: str) -> User:
        user = self.db.get(User, user_id)
        if not user: raise NotFoundError("Usuario nao encontrado.")
        return user

    def list(self) -> list[User]:
        return list(self.db.scalars(select(User).order_by(User.normalized_username, User.id)))

    def create(self, payload: UserCreate) -> User:
        user = User(username=payload.username.strip(), normalized_username=normalized_username(payload.username), password_hash=hash_password(payload.password), role=UserRole(payload.role), is_active=payload.is_active, auth_version=1, must_change_password=True)
        self.db.add(user); self._commit(); self.db.refresh(user); return user

    def create_first_admin(self, username: str, password: str) -> User:
        if self.db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)):
            raise ConflictError("Um administrador ja foi cadastrado.")
        return self.create(UserCreate(username=username, password=password, role="admin", is_active=True))

    def authenticate(self, username: str, password: str) -> User:
        user = self.db.scalar(select(User).where(User.normalized_username == normalized_username(username)))
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            raise AuthenticationError("Credenciais invalidas.")
        user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None); self._commit(); self.db.refresh(user); return user

    def _active_admin_count(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))) or 0)

    def update(self, user_id: str, payload: UserUpdate) -> User:
        user = self.get(user_id)
        removing_last = user.role == UserRole.ADMIN and user.is_active and ((payload.role is not None and payload.role != "admin") or payload.is_active is False)
        if removing_last and self._active_admin_count() <= 1: raise ConflictError("O ultimo administrador ativo nao pode ser alterado.")
        security_changed = False
        if payload.username is not None:
            user.username = payload.username.strip(); user.normalized_username = normalized_username(payload.username)
        if payload.role is not None and user.role != UserRole(payload.role): user.role = UserRole(payload.role); security_changed = True
        if payload.is_active is not None and user.is_active != payload.is_active: user.is_active = payload.is_active; security_changed = True
        if security_changed: user.auth_version += 1
        self._commit(); self.db.refresh(user); return user

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.password_hash): raise AuthenticationError("Senha atual invalida.")
        user.password_hash = hash_password(new_password); user.must_change_password = False; user.auth_version += 1; self._commit(); self.db.refresh(user)

    def reset_password(self, user_id: str, new_password: str) -> User:
        user = self.get(user_id); user.password_hash = hash_password(new_password); user.must_change_password = True; user.auth_version += 1; self._commit(); self.db.refresh(user); return user
