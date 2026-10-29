from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from extensions import db
from models import utcnow


class UploadReceipt(db.Model):
    __tablename__ = "reimbursement_upload_receipts"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_rb_upload_receipt_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("reimbursement_invoices.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
