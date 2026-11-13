"""Import every ORM model so Base.metadata is complete and foreign keys resolve.

Anything that touches the database (the app factory, CLI commands, Alembic) imports this
module. Add each new models module here.
"""

from app.core.audit import AuditLog
from app.modules.auth.models import AuthSession, LoginAttempt, RecoveryCode
from app.modules.settings.models import SettingsVersion
from app.modules.users.models import User, UserPermission

__all__ = [
    "AuditLog",
    "AuthSession",
    "LoginAttempt",
    "RecoveryCode",
    "SettingsVersion",
    "User",
    "UserPermission",
]
