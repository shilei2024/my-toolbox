"""Audit records owned by the reimbursement domain."""
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from extensions import db
from models import utcnow


class ReimbursementAudit(db.Model):
    __tablename__ = "reimbursement_audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(8), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    period_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
