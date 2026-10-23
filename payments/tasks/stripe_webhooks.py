import logging

import stripe
from celery import shared_task

from payments.models import Payment
from settings.models import StripeSetting

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_checkout_session_completed(self, checkout_session_id, event_data):
    """
    Process a checkout.session.completed event asynchronously.

    Maps Stripe payment statuses to Payment model statuses:
    - 'paid' -> STATUS_PAID
    - 'unpaid' -> STATUS_UNPAID
    - 'no_payment_required' -> STATUS_PAID

    Note: Payments that are already PAID will not be updated to prevent downgrades.

    Args:
        checkout_session_id (str): The Stripe checkout session ID
        event_data (dict): The raw webhook event data

    Returns:
        dict: Operation result with success status and details
    """
    logger.info(
        "Processing checkout.session.completed for session %s",
        checkout_session_id,
    )

    data = event_data.get("data", {}).get("object", {})
    payment_status = data.get("payment_status")

    # Validate payment status
    if payment_status not in [choice[0] for choice in Payment.STATUS_CHOICES]:
        logger.warning(
            "Unknown payment status '%s' for payment %s. Skipping status update.",
            payment_status,
            checkout_session_id,
        )
        return {
            "success": False,
            "error": f"Unknown payment status: {payment_status}",
            "checkout_session_id": checkout_session_id,
        }

    try:
        # Update payment status in database
        _update_checkout_session_payment_status(checkout_session_id, payment_status)

        logger.info(
            "Successfully processed checkout.session.completed for %s",
            checkout_session_id,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Payment status updated successfully",
            "checkout_session_id": checkout_session_id,
            "payment_status": payment_status,
        }
    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "database",
            "deadlock",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error processing checkout session %s (attempt %s/%s): %s",
                checkout_session_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to process checkout session %s after %s attempts",
            checkout_session_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "checkout_session_id": checkout_session_id,
            "attempts": self.request.retries + 1,
        }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_payment_intent_succeeded(self, payment_intent_id, event_data):
    """
    Process a payment_intent.succeeded event asynchronously.

    This task retrieves the checkout session from Stripe API and updates
    the Payment model status to PAID.

    Args:
        payment_intent_id (str): The Stripe payment intent ID
        event_data (dict): The raw webhook event data

    Returns:
        dict: Operation result with success status and details
    """
    logger.info(
        "Processing payment_intent.succeeded for payment_intent %s",
        payment_intent_id,
    )

    data = event_data.get("data", {}).get("object", {})
    payment_status = data.get("status")

    # Validate payment status
    if payment_status != "succeeded":
        logger.warning(
            "Unexpected status '%s' for payment_intent.succeeded event. "
            "Expected 'succeeded'. Skipping update.",
            payment_status,
        )
        return {
            "success": False,
            "error": f"Unexpected status: {payment_status}",
            "payment_intent_id": payment_intent_id,
        }

    try:
        # Retrieve checkout session from Stripe API
        checkout_session_id = _get_checkout_session_from_payment_intent(
            payment_intent_id,
        )

        if not checkout_session_id:
            logger.warning(
                "No checkout session found for payment_intent %s. "
                "Cannot update payment status.",
                payment_intent_id,
            )
            return {
                "success": False,
                "error": "No checkout session found",
                "payment_intent_id": payment_intent_id,
            }

        # Update payment status in database
        _update_payment_status(checkout_session_id, payment_intent_id)

        logger.info(
            "Successfully processed payment_intent.succeeded for %s",
            payment_intent_id,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Payment status updated successfully",
            "payment_intent_id": payment_intent_id,
            "checkout_session_id": checkout_session_id,
        }

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error processing payment_intent %s (attempt %s/%s): %s",
                payment_intent_id,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to process payment_intent %s after %s attempts",
            payment_intent_id,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "payment_intent_id": payment_intent_id,
            "attempts": self.request.retries + 1,
        }


def _get_checkout_session_from_payment_intent(payment_intent_id):
    """
    Retrieve the checkout session ID from a payment intent ID.

    Args:
        payment_intent_id (str): The Stripe payment intent ID

    Returns:
        str | None: The checkout session ID, or None if not found

    Raises:
        Exception: If there's an error retrieving the checkout session
    """
    try:
        stripe_settings = StripeSetting.get_solo()
        stripe.api_key = stripe_settings.api_key

        # Get the checkout session ID from the payment intent
        checkout_sessions = stripe.checkout.Session.list(
            payment_intent=payment_intent_id,
            limit=1,
        )

        if not checkout_sessions.data:
            return None

        checkout_session_id = checkout_sessions.data[0].id

        logger.info(
            "Found checkout session %s for payment_intent %s",
            checkout_session_id,
            payment_intent_id,
        )

        return checkout_session_id  # noqa: TRY300

    except Exception:
        logger.exception(
            "Error retrieving checkout session for payment_intent %s",
            payment_intent_id,
        )
        raise


def _update_checkout_session_payment_status(checkout_session_id, payment_status):
    """
    Update the payment status and raw data using the checkout session ID.

    Args:
        checkout_session_id (str): The Stripe checkout session ID
        payment_status (str): The payment status from Stripe (for logging)

    Raises:
        Payment.DoesNotExist: If payment is not found
    """
    try:
        payment = Payment.objects.only("id").get(
            reference_type=Payment.REFERENCE_STRIPE,
            reference=checkout_session_id,
        )

        # Use the model's update_status method to update both status and raw_data
        # This method is idempotent and handles already-paid payments gracefully
        payment.update_status()

        logger.info(
            "Processed checkout.session.completed for payment %s",
            checkout_session_id,
        )
    except Payment.DoesNotExist:
        logger.warning(
            "Payment with reference %s not found. Skipping status update.",
            checkout_session_id,
        )
        raise


def _update_payment_status(checkout_session_id, payment_intent_id):
    """
    Update the payment status and raw data using the checkout session ID.

    This function uses the Payment model's update_status method to retrieve
    the full checkout session data from Stripe API.

    Args:
        checkout_session_id (str): The Stripe checkout session ID
        payment_intent_id (str): The Stripe payment intent ID (for logging)

    Raises:
        Payment.DoesNotExist: If payment is not found
    """
    try:
        payment = Payment.objects.only("id").get(
            reference_type=Payment.REFERENCE_STRIPE,
            reference=checkout_session_id,
        )

        # Use the model's update_status method to update both status and raw_data
        # This method is idempotent and handles already-paid payments gracefully
        payment.update_status()

        logger.info(
            "Processed payment_intent.succeeded for payment %s (payment_intent: %s)",
            checkout_session_id,
            payment_intent_id,
        )
    except Payment.DoesNotExist:
        logger.warning(
            "Payment with checkout session reference %s not found. "
            "Skipping status update. (payment_intent: %s)",
            checkout_session_id,
            payment_intent_id,
        )
        raise
