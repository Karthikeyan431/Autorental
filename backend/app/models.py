"""Import every ORM model so Base.metadata is complete and foreign keys resolve.

Anything that touches the database (the app factory, CLI commands, Alembic) imports this
module. Add each new models module here.
"""

from app.core.audit import AuditLog
from app.modules.alerts.models import Alert
from app.modules.auth.models import AuthSession, LoginAttempt, RecoveryCode
from app.modules.documents.models import Document, DocumentAccessLog
from app.modules.drivers.models import Consent, Driver, DriverManagerHistory, DriverRestriction
from app.modules.kyc.models import IdentityDetails, KycCheck, KycEvent, LicenceDetails
from app.modules.settings.models import SettingsVersion
from app.modules.users.models import User, UserPermission

__all__ = [
    "Alert",
    "AuditLog",
    "AuthSession",
    "Consent",
    "Document",
    "DocumentAccessLog",
    "Driver",
    "DriverManagerHistory",
    "DriverRestriction",
    "IdentityDetails",
    "KycCheck",
    "KycEvent",
    "LicenceDetails",
    "LoginAttempt",
    "RecoveryCode",
    "SettingsVersion",
    "User",
    "UserPermission",
]
