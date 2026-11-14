"""Import every ORM model so Base.metadata is complete and foreign keys resolve.

Anything that touches the database (the app factory, CLI commands, Alembic) imports this
module. Add each new models module here.
"""

from app.core.audit import AuditLog
from app.modules.agreements.models import Agreement
from app.modules.alerts.models import Alert
from app.modules.auth.models import AuthSession, LoginAttempt, RecoveryCode
from app.modules.documents.models import Document, DocumentAccessLog
from app.modules.drivers.models import Consent, Driver, DriverManagerHistory, DriverRestriction
from app.modules.kyc.models import IdentityDetails, KycCheck, KycEvent, LicenceDetails
from app.modules.payments.models import AdvanceTransaction, Payment, PaymentAllocation
from app.modules.rent.models import ChargeAdjustment, RentCharge
from app.modules.settings.models import SettingsVersion
from app.modules.users.models import User, UserPermission
from app.modules.vehicles.models import MaintenanceRecord, Vehicle, VehicleCompliance

__all__ = [
    "AdvanceTransaction",
    "Agreement",
    "Alert",
    "AuditLog",
    "AuthSession",
    "ChargeAdjustment",
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
    "MaintenanceRecord",
    "Payment",
    "PaymentAllocation",
    "RecoveryCode",
    "RentCharge",
    "SettingsVersion",
    "User",
    "UserPermission",
    "Vehicle",
    "VehicleCompliance",
]
