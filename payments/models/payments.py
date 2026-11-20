import logging

from django.db import models
from django.db import transaction
from simple_history.models import HistoricalRecords

from core.users.models import User

logger = logging.getLogger(__name__)


class Payment(models.Model):
    # Stripe Checkout Session payment_status values (official)
    STATUS_PAID = "paid"
    STATUS_UNPAID = "unpaid"
    STATUS_NO_PAYMENT_REQUIRED = "no_payment_required"

    # Custom statuses for additional states
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_PROCESSING = "processing"

    STATUS_CHOICES = [
        (STATUS_PAID, "Paid"),
        (STATUS_UNPAID, "Unpaid"),
        (STATUS_NO_PAYMENT_REQUIRED, "No Payment Required"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
    ]

    REFERENCE_STRIPE = "STRIPE"
    REFERENCE_PADDLE = "PADDLE"
    REFERENCE_CHOICES = [
        (REFERENCE_STRIPE, "Stripe"),
        (REFERENCE_PADDLE, "Paddle"),
    ]

    TYPE_INSTAGRAM_USER_STORY_CREDIT = "INSTAGRAM_USER_STORY_CREDIT"
    TYPE_INSTAGRAM_USER_PROFILE_CREDIT = "INSTAGRAM_USER_PROFILE_CREDIT"
    TYPE_CHOICES = [
        (TYPE_INSTAGRAM_USER_STORY_CREDIT, "Instagram User Story Credit"),
        (TYPE_INSTAGRAM_USER_PROFILE_CREDIT, "Instagram User Profile Credit"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reference_type = models.CharField(max_length=20, choices=REFERENCE_CHOICES)
    reference = models.CharField(max_length=100, unique=True)
    url = models.URLField(max_length=1000)
    status = models.CharField(
        max_length=100,
        choices=STATUS_CHOICES,
        default=STATUS_UNPAID,
    )
    type = models.CharField(max_length=255, choices=TYPE_CHOICES, null=True)  # noqa: DJ001
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    raw_data = models.JSONField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Payment {self.reference} - {self.status}"

    @transaction.atomic
    def update_status(self):
        """
        Update payment status from gateway with row-level locking.

        Returns early without error if payment is already paid (idempotent).
        """
        from instagram.models import StoryCreditPayment  # noqa: PLC0415
        from payments.gateways.factory import PaymentGatewayFactory  # noqa: PLC0415

        # Acquire a row-level lock on this payment instance
        payment = Payment.objects.select_for_update().get(pk=self.pk)

        # Return early if payment is already paid (idempotent behavior)
        if payment.status == Payment.STATUS_PAID:
            logger.info(
                "Payment %s is already paid, skipping status update.",
                payment.reference,
            )
            return

        # Get the appropriate gateway
        gateway = PaymentGatewayFactory.get_gateway(payment.reference_type)

        # Retrieve payment status
        status_data = gateway.retrieve_payment_status(payment.reference)

        # Update payment
        payment.status = status_data["status"]
        payment.raw_data = status_data["raw_data"]
        payment.save()

        logger.info(
            "Updated payment %s status to %s",
            payment.reference,
            payment.status,
        )

        # Process payment if paid
        if payment.status == Payment.STATUS_PAID:
            metadata = status_data.get("metadata", {})

            if payment.type == Payment.TYPE_INSTAGRAM_USER_STORY_CREDIT:
                StoryCreditPayment.create_record(
                    instagram_user_id=metadata.get("target")
                    or metadata.get("instagram_user_id"),
                    credit=int(
                        metadata.get("quantity")
                        or metadata.get("story_credit_quantity"),
                    ),
                    payment_id=payment.id,
                )
