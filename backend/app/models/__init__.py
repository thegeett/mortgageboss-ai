"""Models package.

Exports the declarative Base and common mixins. As concrete models are
added in subsequent tickets, they will also be imported here so that
Alembic autogenerate can discover them.
"""

from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDMixin,
    utcnow,
)
from app.models.borrower import Borrower, MaritalStatus
from app.models.calculator_override import CalculatorOverride
from app.models.communication import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.company import Company
from app.models.document import (
    Document,
    DocumentCategory,
    DocumentStatus,
    Tier,
    UploadSource,
)
from app.models.document_finding import (
    DocumentFinding,
    DocumentFindingStatus,
    DocumentFindingType,
)
from app.models.dti_override import DtiOverride
from app.models.encrypted_types import EncryptedString
from app.models.enums import RecordStatus, str_enum
from app.models.extraction import Extraction, ExtractionStatus
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.helpers import only_active, scope_to_company
from app.models.lender import Lender, LoanProgram
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose, RefinanceType
from app.models.ltv_override import LtvOverride
from app.models.mismo_import import MismoImport, MismoImportStatus
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)
from app.models.property import OccupancyType, Property, PropertyType
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.models.types import (
    LongStr,
    MediumStr,
    Money,
    ShortStr,
)
from app.models.user import User, UserRole
from app.models.validation_verdict import ValidationVerdict, VerdictKind
from app.models.verification import (
    Verification,
    VerificationStatus,
    VerificationTrigger,
)

__all__ = [
    "ActivityLog",
    "ActivityType",
    "Base",
    "Borrower",
    "CalculatorOverride",
    "Communication",
    "CommunicationChannel",
    "CommunicationDirection",
    "CommunicationStatus",
    "Company",
    "Document",
    "DocumentCategory",
    "DocumentFinding",
    "DocumentFindingStatus",
    "DocumentFindingType",
    "DocumentStatus",
    "DtiOverride",
    "EncryptedString",
    "Extraction",
    "ExtractionStatus",
    "Finding",
    "FindingCategory",
    "FindingOrigin",
    "FindingResolutionStatus",
    "FindingStatus",
    "Lender",
    "LoanFile",
    "LoanFileStatus",
    "LoanProgram",
    "LoanPurpose",
    "LongStr",
    "LtvOverride",
    "MaritalStatus",
    "MediumStr",
    "MismoImport",
    "MismoImportStatus",
    "Money",
    "NeedsItem",
    "NeedsItemDisposition",
    "NeedsItemOrigin",
    "NeedsItemPriority",
    "NeedsItemStatus",
    "OccupancyType",
    "Property",
    "PropertyType",
    "RecordStatus",
    "RefinanceType",
    "ShortStr",
    "SoftDeleteMixin",
    "StatedAsset",
    "StatedEmployer",
    "StatedIncomeItem",
    "StatedLiability",
    "Tier",
    "TimestampMixin",
    "UUIDMixin",
    "UploadSource",
    "User",
    "UserRole",
    "ValidationVerdict",
    "VerdictKind",
    "Verification",
    "VerificationStatus",
    "VerificationTrigger",
    "only_active",
    "scope_to_company",
    "str_enum",
    "utcnow",
]

# Concrete models are imported here so Alembic autogenerate (which imports
# app.models) sees every table on Base.metadata.
