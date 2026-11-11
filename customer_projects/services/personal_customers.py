"""Private customer containers without granting organization membership."""
from uuid import UUID, uuid5

from extensions import db
from shared.models import Organization
from .projects import DomainError, _create_customer_record


# Persistent identity: never change this namespace or derive it from credentials.
_NAMESPACE = UUID("415584f3-d30d-4f5c-bafb-a415b59c75d4")


def personal_customer_organization_id(user_id: int) -> str:
    return str(uuid5(_NAMESPACE, str(int(user_id))))


def create_personal_customer(data: dict, user_id: int):
    """Caller authorizes and locks the user; commit belongs to the API transaction."""
    organization_id = personal_customer_organization_id(user_id)
    organization = db.session.get(Organization, organization_id)
    if organization is None:
        organization = Organization(id=organization_id, name="个人客户空间", status="personal")
        db.session.add(organization)
        db.session.flush()
    elif organization.status != "personal":
        raise DomainError("CUSTOMER_SPACE_UNAVAILABLE", "客户空间暂不可用，请联系管理员。")
    return _create_customer_record(data, organization_id, user_id, user_id)
