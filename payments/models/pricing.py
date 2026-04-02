from django.db import models
from simple_history.models import HistoricalRecords


class PricingPlan(models.Model):
    BILLING_MONTHLY = "monthly"
    BILLING_ANNUAL = "annual"
    BILLING_PERIOD_CHOICES = [
        (BILLING_MONTHLY, "Monthly"),
        (BILLING_ANNUAL, "Annual"),
    ]

    CURRENCY_USD = "USD"
    CURRENCY_IDR = "IDR"
    CURRENCY_EUR = "EUR"
    CURRENCY_SGD = "SGD"
    CURRENCY_GBP = "GBP"
    CURRENCY_AUD = "AUD"
    CURRENCY_CHOICES = [
        (CURRENCY_USD, "USD"),
        (CURRENCY_IDR, "IDR"),
        (CURRENCY_EUR, "EUR"),
        (CURRENCY_SGD, "SGD"),
        (CURRENCY_GBP, "GBP"),
        (CURRENCY_AUD, "AUD"),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    billing_period = models.CharField(max_length=20, choices=BILLING_PERIOD_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(
        max_length=10,
        choices=CURRENCY_CHOICES,
        default=CURRENCY_USD,
    )
    features = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "Pricing Plan"
        verbose_name_plural = "Pricing Plans"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.billing_period})"
