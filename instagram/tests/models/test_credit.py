from django.test import TestCase

from instagram.models.credit import StoryCredit
from instagram.models.credit import StoryCreditPayment
from instagram.tests.factories import InstagramUserFactory
from payments.tests.factories import PaymentFactory


class TestStoryCreditModel(TestCase):
    """Tests for the StoryCredit model."""

    def test_str_representation(self):
        """Test the string representation of StoryCredit."""
        user = InstagramUserFactory(username="credituser")
        story_credit = StoryCredit.objects.create(user=user, credit=0)
        assert str(story_credit) == "Story Credit for credituser"

    def test_default_credit_is_zero(self):
        """Test that the default credit value is zero."""
        user = InstagramUserFactory()
        story_credit = StoryCredit.objects.create(user=user)
        assert story_credit.credit == 0


class TestStoryCreditPaymentModel(TestCase):
    """Tests for the StoryCreditPayment model."""

    def setUp(self):
        """Set up shared test data."""
        self.instagram_user = InstagramUserFactory(username="paymentuser")
        self.story_credit = StoryCredit.objects.create(
            user=self.instagram_user,
            credit=0,
        )
        self.payment = PaymentFactory()

    def test_str_representation(self):
        """Test the string representation of StoryCreditPayment."""
        scp = StoryCreditPayment.objects.create(
            story_credit=self.story_credit,
            payment=self.payment,
            credit=10,
        )
        assert str(scp) == "Story Credit Payment for paymentuser"

    def test_save_updates_story_credit(self):
        """Test that saving a StoryCreditPayment increments the StoryCredit balance."""
        assert self.story_credit.credit == 0
        StoryCreditPayment.objects.create(
            story_credit=self.story_credit,
            payment=self.payment,
            credit=5,
        )
        self.story_credit.refresh_from_db()
        assert self.story_credit.credit == 5  # noqa: PLR2004

    def test_multiple_payments_accumulate_credits(self):
        """Test that multiple payments correctly accumulate story credits."""
        payment2 = PaymentFactory()
        StoryCreditPayment.objects.create(
            story_credit=self.story_credit,
            payment=self.payment,
            credit=3,
        )
        StoryCreditPayment.objects.create(
            story_credit=self.story_credit,
            payment=payment2,
            credit=7,
        )
        self.story_credit.refresh_from_db()
        assert self.story_credit.credit == 10  # noqa: PLR2004

    def test_create_record_creates_story_credit_if_missing(self):
        """Test that create_record creates a StoryCredit if one doesn't exist yet."""
        new_user = InstagramUserFactory(username="newcredituser")
        # Ensure no StoryCredit exists for the new user
        assert not StoryCredit.objects.filter(user=new_user).exists()

        scp = StoryCreditPayment.create_record(
            payment_id=self.payment.id,
            instagram_user_id=new_user.uuid,
            credit=15,
        )
        assert StoryCredit.objects.filter(user=new_user).exists()
        story_credit = StoryCredit.objects.get(user=new_user)
        assert story_credit.credit == 15  # noqa: PLR2004
        assert scp.credit == 15  # noqa: PLR2004
