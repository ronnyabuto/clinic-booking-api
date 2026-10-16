"""Clinic models, schedule checks and active-slot indexes."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for name in ("doctors", "patients"):
        op.create_table(
            name,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("full_name", sa.String(200), nullable=False),
        )
    op.create_table(
        "doctor_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("doctor_id", sa.Uuid(), sa.ForeignKey("doctors.id"), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_schedule_weekday"),
        sa.CheckConstraint("start_time < end_time", name="ck_schedule_order"),
        sa.CheckConstraint(
            "EXTRACT(MINUTE FROM start_time) IN (0, 30) AND "
            "EXTRACT(SECOND FROM start_time) = 0 AND "
            "EXTRACT(MINUTE FROM end_time) IN (0, 30) AND "
            "EXTRACT(SECOND FROM end_time) = 0",
            name="ck_schedule_grid",
        ),
    )
    op.create_index("ix_schedule_doctor_weekday", "doctor_schedules", ["doctor_id", "day_of_week"])
    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("doctor_id", sa.Uuid(), sa.ForeignKey("doctors.id"), nullable=False),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="BOOKED"),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('BOOKED', 'CANCELLED')", name="ck_appointment_status"),
        sa.CheckConstraint(
            "(status = 'BOOKED' AND cancel_reason IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'CANCELLED' AND cancel_reason IS NOT NULL AND "
            "btrim(cancel_reason, U&'\\0009\\000A\\000B\\000C\\000D\\0020\\0085\\00A0\\1680"
            "\\2000\\2001\\2002\\2003\\2004\\2005\\2006\\2007\\2008\\2009\\200A\\2028\\2029"
            "\\202F\\205F\\3000') <> '' AND cancelled_at IS NOT NULL)",
            name="ck_appointment_cancellation_state",
        ),
    )
    op.create_index(
        "uq_doctor_active_slot",
        "appointments",
        ["doctor_id", "slot_start"],
        unique=True,
        postgresql_where=sa.text("status = 'BOOKED'"),
    )
    op.create_index(
        "ix_patient_active_slot",
        "appointments",
        ["patient_id", "slot_start"],
        postgresql_where=sa.text("status = 'BOOKED'"),
    )


def downgrade():
    op.drop_table("appointments")
    op.drop_table("doctor_schedules")
    op.drop_table("patients")
    op.drop_table("doctors")
