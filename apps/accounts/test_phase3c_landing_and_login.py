from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import LoginForm
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.inventory.models import Asset, AssetCategory
from apps.organizations.models import Department
from apps.student_reservations.models import StudentReservation


class Phase3CPublicLandingAndLoginTests(TestCase):
    """Targeted verification tests for the separate Student Portal (/student/)
    and Staff & Officials Portal (/staff/), routing/redirect rules, authentication,
    and public/private security boundaries.
    """

    @classmethod
    def setUpTestData(cls):
        cls.password = 'Phase3CTestPass!2026'
        cls.admin_user = User.objects.create_user(
            username='phase3c_admin',
            email='phase3c_admin@cba.edu',
            password=cls.password,
            first_name='System',
            last_name='Custodian',
            role=User.Role.ADMIN,
        )
        cls.faculty_user = User.objects.create_user(
            username='phase3c_faculty',
            email='phase3c_faculty@cba.edu',
            password=cls.password,
            first_name='Elena',
            last_name='Reyes',
            role=User.Role.FACULTY,
        )

        # Seed private operational records to verify they are never leaked
        cls.dept = Department.objects.create(name='Accountancy', code='ACCT3C')
        cls.category = AssetCategory.objects.create(name='IT Equipment 3C', code='IT3C')
        cls.private_asset = Asset.objects.create(
            asset_code='CBA-SECRET-9901',
            item_name='Confidential Server Rack Alpha',
            serial_number='SN-PRIVATE-88219',
            category=cls.category,
            department=cls.dept,
            status=Asset.Status.AVAILABLE,
        )
        cls.private_reservation = StudentReservation.objects.create(
            student_name='Juan Dela Cruz PrivatePII',
            student_id='2026-998877',
            email='juandelacruz.secret@student.cba.edu',
            contact_number='09179998877',
            course_year_section='BSBA-4A',
            category=cls.category,
            equipment_type='Projector',
            purpose='Confidential Thesis Defense',
            room_venue='CBA-402',
            requested_pickup=timezone.now() + timedelta(days=1),
            requested_return=timezone.now() + timedelta(days=1, hours=2),
        )
        cls.private_audit = AuditLog.objects.create(
            user=cls.admin_user,
            action='CREATE',
            model_name='Asset',
            object_id=str(cls.private_asset.id),
            object_repr='CBA-SECRET-9901 Confidential Audit Entry',
            changes={'note': 'Internal custodian audit trail entry'},
        )

    # ------------------------------------------------------------------
    # 1. Student Portal (/student/ and /)
    # ------------------------------------------------------------------

    def test_anonymous_root_redirects_to_student_landing_page(self):
        """Anonymous GET / redirects (HTTP 302) to /student/."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('student_landing'))

    def test_student_landing_page_returns_http_200_with_student_branding(self):
        """GET /student/ returns HTTP 200 with dedicated student branding and elements."""
        response = self.client.get(reverse('student_landing'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/landing.html')

        # Student-facing branding
        self.assertContains(response, 'CBA Equipment Reservations')
        self.assertContains(response, 'College of Business Administration')

        # Permitted student features
        self.assertContains(response, 'Browse equipment')
        self.assertContains(response, 'Reserve equipment for your next class')
        self.assertContains(response, 'Track my request')
        self.assertContains(response, 'How reservations work')
        self.assertContains(response, '01')
        self.assertContains(response, 'Choose equipment')
        self.assertContains(response, '02')
        self.assertContains(response, 'Submit request')
        self.assertContains(response, '03')
        self.assertContains(response, 'Collect after approval')

    def test_student_portal_does_not_contain_staff_links_or_internal_terms(self):
        """Student landing page must not show CBA IMS, Staff Sign In, dashboard links, or internal ops."""
        response = self.client.get(reverse('student_landing'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # Forbidden terminology & branding
        self.assertNotIn('CBA IMS', html)
        self.assertNotIn('Inventory Management System', html)
        self.assertNotIn('Staff Sign In', html)
        self.assertNotIn('Go to Dashboard', html)
        self.assertNotIn('Custodian Queue', html)
        self.assertNotIn('Property Custodian', html)
        self.assertNotIn('/staff/', html)
        self.assertNotIn('/accounts/login/', html)
        self.assertNotIn('reverse("dashboard")', html)

    def test_public_student_pages_do_not_leak_custodian_navigation_or_staff_links(self):
        """Student reservation base and catalog layouts must not contain custodian links or staff links."""
        routes = [
            reverse('student_reservations:catalog'),
            reverse('student_reservations:public_request'),
            reverse('student_reservations:public_lookup_search'),
        ]
        for url in routes:
            with self.subTest(url=url):
                # Test anonymous visitor
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode('utf-8')
                self.assertNotIn('Custodian Queue', html)
                self.assertNotIn('/staff/', html)
                self.assertNotIn('Staff Sign In', html)
                self.assertNotIn('CBA IMS', html)

                # Test authenticated admin visitor on public student pages
                self.client.force_login(self.admin_user)
                admin_response = self.client.get(url)
                self.assertEqual(admin_response.status_code, 200)
                admin_html = admin_response.content.decode('utf-8')
                self.assertNotIn('Custodian Queue', admin_html)
                self.assertNotIn('Property Custodian Queue', admin_html)
                self.assertNotIn('/staff/', admin_html)
                self.client.logout()

    def test_public_landing_page_does_not_expose_private_records_or_pii(self):
        """Student landing page must never expose private inventory items, student PII, or audit logs."""
        response = self.client.get(reverse('student_landing'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        self.assertNotIn('CBA-SECRET-9901', html)
        self.assertNotIn('Confidential Server Rack Alpha', html)
        self.assertNotIn('SN-PRIVATE-88219', html)
        self.assertNotIn('Juan Dela Cruz PrivatePII', html)
        self.assertNotIn('2026-998877', html)
        self.assertNotIn('juandelacruz.secret@student.cba.edu', html)
        self.assertNotIn(self.private_reservation.lookup_token, html)
        self.assertNotIn('Confidential Audit Entry', html)
        self.assertNotIn('Internal custodian audit trail entry', html)

    # ------------------------------------------------------------------
    # 2. Staff and Officials Portal (/staff/ and /accounts/login/)
    # ------------------------------------------------------------------

    def test_staff_portal_renders_workspace_layout_and_login_form(self):
        """GET /staff/ renders Staff Workspace branding, LoginForm, and CSRF token."""
        response = self.client.get(reverse('staff_login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')
        self.assertIsInstance(response.context['form'], LoginForm)
        self.assertContains(response, 'CBA IMS &mdash; Staff Workspace')
        self.assertContains(response, 'Staff sign in')
        self.assertContains(response, 'Equipment library')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'Sign in')

        # Must not contain student reservation actions or forms
        self.assertNotContains(response, 'Browse equipment')
        self.assertNotContains(response, 'How reservations work')

    def test_accounts_login_backward_compatibility(self):
        """GET /accounts/login/ maintains full compatibility and serves the staff login view."""
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')
        self.assertContains(response, 'CBA IMS &mdash; Staff Workspace')

    def test_successful_staff_login_redirects_to_dashboard(self):
        """Valid staff login POST at /staff/ without next parameter redirects to /dashboard/."""
        response = self.client.post(
            reverse('staff_login'),
            {'username': self.admin_user.username, 'password': self.password},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('dashboard'))

    def test_failed_staff_login_displays_error_alert_and_stays_on_login(self):
        """Invalid credentials return HTTP 200 with clear error message and unauthenticated session."""
        response = self.client.post(
            reverse('staff_login'),
            {'username': self.admin_user.username, 'password': 'WrongPassword!999'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')
        self.assertContains(response, 'Authentication failed')
        self.assertNotIn('_auth_user_id', self.client.session)

    # ------------------------------------------------------------------
    # 3. Safe Handling of `next` Redirects
    # ------------------------------------------------------------------

    def test_login_honors_valid_safe_internal_next_url(self):
        """Valid internal next URL is preserved in the login form and honored upon login."""
        safe_next = '/inventory/assets/'
        get_res = self.client.get(reverse('staff_login'), {'next': safe_next})
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, f'name="next" value="{safe_next}"')

        post_res = self.client.post(
            reverse('staff_login'),
            {
                'username': self.admin_user.username,
                'password': self.password,
                'next': safe_next,
            },
        )
        self.assertEqual(post_res.status_code, 302)
        self.assertEqual(post_res['Location'], safe_next)

    def test_login_rejects_external_or_unsafe_next_urls(self):
        """External or protocol-relative next URLs are rejected and fall back to /dashboard/."""
        unsafe_targets = [
            'https://evil.example.com/phish',
            'http://attacker.invalid/login',
            '//evil.example.com/protocol-relative',
            'javascript:alert(1)',
        ]
        for unsafe_next in unsafe_targets:
            with self.subTest(unsafe_next=unsafe_next):
                self.client.logout()
                response = self.client.post(
                    f"{reverse('staff_login')}?next={unsafe_next}",
                    {
                        'username': self.faculty_user.username,
                        'password': self.password,
                        'next': unsafe_next,
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'], reverse('dashboard'))

    def test_authenticated_user_visiting_staff_login_redirects_to_dashboard(self):
        """Authenticated staff visiting GET /staff/ are redirected to /dashboard/."""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('staff_login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('dashboard'))

    # ------------------------------------------------------------------
    # 4. Security & Role-Based Access Control (RBAC)
    # ------------------------------------------------------------------

    def test_anonymous_user_cannot_access_internal_management_views(self):
        """Anonymous access to internal views must redirect to login."""
        internal_urls = [
            reverse('dashboard'),
            reverse('inventory:asset_list'),
            reverse('student_reservations:custodian_list'),
            reverse('maintenance:case_list'),
            reverse('supplies:supply_list'),
            reverse('transfers:pending_list'),
            reverse('disposals:pending_list'),
            reverse('reports:reports_dashboard'),
            reverse('audit:audit_log_list'),
        ]
        for url in internal_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/accounts/login/', response['Location'])

    def test_non_admin_cannot_access_admin_queues_and_logs(self):
        """Faculty cannot access custodian reservation queue or audit logs (HTTP 403)."""
        self.client.force_login(self.faculty_user)
        restricted_urls = [
            reverse('student_reservations:custodian_list'),
            reverse('audit:audit_log_list'),
        ]
        for url in restricted_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_authenticated_user_can_access_dashboard(self):
        """Authenticated staff users can access GET /dashboard/ (HTTP 200)."""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/dashboard.html')
