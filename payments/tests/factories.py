import factory
from factory import Faker
from factory import SubFactory
from factory.django import DjangoModelFactory

from core.users.tests.factories import UserFactory
from payments.models import GatewayOption
from payments.models import Payment
from payments.models import PricingFeature
from payments.models import PricingPlan


class PaymentFactory(DjangoModelFactory):
    user = SubFactory(UserFactory)
    reference_type = Payment.REFERENCE_STRIPE
    reference = Faker("uuid4")
    url = Faker("url")
    status = Payment.STATUS_UNPAID
    amount = Faker("pydecimal", left_digits=5, right_digits=2, positive=True)
    raw_data = factory.LazyFunction(
        lambda: {
            "id": factory.Faker("uuid4").evaluate(None, None, extra={"locale": None}),
            "object": "checkout.session",
            "payment_status": "unpaid",
            "amount_total": 1000,
            "currency": "usd",
            "status": "open",
            "mode": "payment",
        },
    )

    class Meta:
        model = Payment
        django_get_or_create = ["reference"]

    class Params:
        # Trait for paid status
        paid = factory.Trait(
            status=Payment.STATUS_PAID,
            raw_data=factory.LazyFunction(
                lambda: {
                    "id": factory.Faker("uuid4").evaluate(
                        None,
                        None,
                        extra={"locale": None},
                    ),
                    "object": "checkout.session",
                    "payment_status": "paid",
                    "amount_total": 1000,
                    "currency": "usd",
                    "status": "complete",
                    "mode": "payment",
                },
            ),
        )

        # Trait for no_payment_required status
        no_payment_required = factory.Trait(
            status=Payment.STATUS_NO_PAYMENT_REQUIRED,
            raw_data=factory.LazyFunction(
                lambda: {
                    "id": factory.Faker("uuid4").evaluate(
                        None,
                        None,
                        extra={"locale": None},
                    ),
                    "object": "checkout.session",
                    "payment_status": "no_payment_required",
                    "amount_total": 0,
                    "currency": "usd",
                    "status": "complete",
                    "mode": "payment",
                },
            ),
        )

        # Trait for processing status
        processing = factory.Trait(
            status=Payment.STATUS_PROCESSING,
            raw_data=factory.LazyFunction(
                lambda: {
                    "id": factory.Faker("uuid4").evaluate(
                        None,
                        None,
                        extra={"locale": None},
                    ),
                    "object": "checkout.session",
                    "payment_status": "unpaid",
                    "amount_total": 1000,
                    "currency": "usd",
                    "status": "open",
                    "mode": "payment",
                },
            ),
        )

        # Trait for failed status
        failed = factory.Trait(
            status=Payment.STATUS_FAILED,
            raw_data=factory.LazyFunction(
                lambda: {
                    "id": factory.Faker("uuid4").evaluate(
                        None,
                        None,
                        extra={"locale": None},
                    ),
                    "object": "checkout.session",
                    "payment_status": "unpaid",
                    "amount_total": 1000,
                    "currency": "usd",
                    "status": "expired",
                    "mode": "payment",
                },
            ),
        )

        # Trait for canceled status
        canceled = factory.Trait(
            status=Payment.STATUS_CANCELED,
            raw_data=factory.LazyFunction(
                lambda: {
                    "id": factory.Faker("uuid4").evaluate(
                        None,
                        None,
                        extra={"locale": None},
                    ),
                    "object": "checkout.session",
                    "payment_status": "unpaid",
                    "amount_total": 1000,
                    "currency": "usd",
                    "status": "expired",
                    "mode": "payment",
                },
            ),
        )


class PricingPlanFactory(DjangoModelFactory):
    name = Faker("word")
    description = Faker("sentence")
    billing_period = PricingPlan.BILLING_MONTHLY
    price = Faker("pydecimal", left_digits=4, right_digits=2, positive=True)
    currency = PricingPlan.CURRENCY_USD
    is_active = True
    sort_order = 0

    class Meta:
        model = PricingPlan

    class Params:
        annual = factory.Trait(
            billing_period=PricingPlan.BILLING_ANNUAL,
        )
        inactive = factory.Trait(
            is_active=False,
        )


class PricingFeatureFactory(DjangoModelFactory):
    plan = SubFactory(PricingPlanFactory)
    label = Faker("sentence", nb_words=4)
    is_available = True
    sort_order = 0

    class Meta:
        model = PricingFeature

    class Params:
        unavailable = factory.Trait(
            is_available=False,
        )


class GatewayOptionFactory(DjangoModelFactory):
    name = Payment.REFERENCE_STRIPE
    is_active = True

    class Meta:
        model = GatewayOption

    class Params:
        # Trait for inactive gateway option
        inactive = factory.Trait(
            is_active=False,
        )
