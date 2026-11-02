from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.inventory.models import AssetCategory, EquipmentType, Brand, Asset
from apps.organizations.models import Department, Location
from apps.student_reservations.models import StudentReservation


class StudentPortalPhase4D1ModernizationTests(TestCase):
    """
    Focused tests for Phase 4D1 Student Portal modernization:
    1. Landing page presentation and verified institutional information.
    2. Catalog projector-first presentation and schedule checker tool actions.
    3. Catalog-to-request prefill and parameter transfer integrity.
    4. Direct request access without false prefill claims (honest empty state).
    5. Tracking lookup token validation and error states.
    """

    def setUp(self):
        self.client = Client()

        self.dept = Department.objects.create(code='CBA', name='College of Business Administration')
        self.loc = Location.objects.create(name='Property Office', department=self.dept)

        self.cat_proj = AssetCategory.objects.create(
            name='Projectors',
            code='PRJ',
            is_reservable=True,
            description='Instructional classroom projectors.'
        )
        self.brand = Brand.objects.create(name='Epson')
        self.eq_type = EquipmentType.objects.create(
            category=self.cat_proj,
            name='Classroom LCD Projector',
            is_active=True
        )

        self.asset1 = Asset.objects.create(
            asset_code='PRJ-001',
            item_name='Epson EB-X06',
            category=self.cat_proj,
            equipment_type=self.eq_type,
            brand=self.brand,
            department=self.dept,
            current_location=self.loc,
            status=Asset.Status.AVAILABLE,
            condition=Asset.Condition.GOOD,
            is_reservable=True
        )

        now = timezone.localtime()
        self.pickup_dt = now + timedelta(days=1, hours=2)
        self.return_dt = self.pickup_dt + timedelta(hours=3)
        self.pickup_str = self.pickup_dt.strftime('%Y-%m-%dT%H:%M')
        self.return_str = self.return_dt.strftime('%Y-%m-%dT%H:%M')

    def test_student_landing_page_renders_complete_guidelines_and_steps(self):
        """Landing page contains verified office information, CTAs, and 3-step cards."""
        url = reverse('student_landing')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode()
        # Heading & Primary CTAs
        self.assertIn("Reserve equipment for your next class.", content)
        self.assertIn("Browse equipment", content)
        self.assertIn("Track my request", content)

        # Verified Institutional Information
        self.assertIn("CBA Property Office", content)
        self.assertIn("Original School ID Required", content)
        self.assertIn("15-Minute Pickup Grace Period", content)
        self.assertIn("8:00 AM &ndash; 5:00 PM", content)

        # 3 Step Cards
        self.assertIn("STEP 01", content)
        self.assertIn("Choose equipment", content)
        self.assertIn("STEP 02", content)
        self.assertIn("Submit request", content)
        self.assertIn("STEP 03", content)
        self.assertIn("Collect after approval", content)

    def test_catalog_renders_projector_first_and_secondary_check_action(self):
        """Catalog page features projectors prominently with secondary check button."""
        url = reverse('student_reservations:catalog')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode()
        self.assertIn("Find equipment", content)
        self.assertIn("Projectors", content)
        self.assertIn("Primary Instructional Equipment", content)
        self.assertIn("Classroom LCD Projector", content)
        self.assertIn("Reserve Projector", content)
        # Check schedule button exists
        self.assertIn("Check", content)
        # Session picker exists; Asia/Manila timezone handling lives in loan_desk.js alignment
        self.assertIn('aria-label="Session"', content)
        self.assertIn("js/loan_desk.js", content)
        # Factual accessories notice
        self.assertIn("Included accessories may vary. Confirm the issued equipment and accessories with the CBA Property Office at pickup.", content)

    def test_catalog_to_request_prefill_handoff_integrity(self):
        """Navigating from catalog to request form transfers category, type, and dates cleanly."""
        url = reverse('student_reservations:public_request')
        params = {
            'category': self.cat_proj.pk,
            'type': self.eq_type.pk,
            'pickup': self.pickup_str,
            'return': self.return_str
        }
        resp = self.client.get(url, params)
        self.assertEqual(resp.status_code, 200)

        self.assertTrue(resp.context['selection_prefilled'])
        self.assertEqual(resp.context['form'].initial.get('category'), self.cat_proj.pk)
        self.assertEqual(resp.context['form'].initial.get('equipment_type_ref'), self.eq_type.pk)
        self.assertEqual(resp.context['form'].initial.get('requested_pickup'), self.pickup_str)
        self.assertEqual(resp.context['form'].initial.get('requested_return'), self.return_str)

        content = resp.content.decode()
        self.assertIn("Classroom LCD Projector", content)
        self.assertIn("Change equipment or schedule", content)
        self.assertIn(f'value="{self.pickup_str}"', content)
        self.assertIn(f'value="{self.return_str}"', content)

    def test_direct_request_access_renders_honest_unselected_state(self):
        """Direct access to request form does NOT falsely claim items are selected."""
        url = reverse('student_reservations:public_request')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        self.assertFalse(resp.context['selection_prefilled'])

        content = resp.content.decode()
        # Must NOT contain misleading placeholder phrases
        self.assertNotIn("Equipment selected in catalog", content)
        self.assertNotIn("Instructional Equipment", content)
        self.assertNotIn("Selected in schedule", content)

        # Must offer clean instruction and browse catalog link
        self.assertIn("No equipment selected", content)
        self.assertIn("Browse Catalog", content)
        self.assertIn("Choose equipment and schedule", content)

    def test_lookup_tracking_displays_clean_states(self):
        """Lookup form renders search card, handles not found, and shows instructions."""
        url = reverse('student_reservations:public_lookup_search')

        # 1. Empty search view
        resp_empty = self.client.get(url)
        self.assertEqual(resp_empty.status_code, 200)
        content_empty = resp_empty.content.decode()
        self.assertIn("Track your reservation", content_empty)
        self.assertIn("43-Character Tracking Code", content_empty)
        self.assertIn("Status information will appear here", content_empty)

        # 2. Invalid code lookup
        resp_invalid = self.client.get(url, {'token': 'invalid-token-123456789012345678901234567890'})
        self.assertEqual(resp_invalid.status_code, 200)
        content_invalid = resp_invalid.content.decode()
        self.assertIn("Reservation Not Found", content_invalid)
