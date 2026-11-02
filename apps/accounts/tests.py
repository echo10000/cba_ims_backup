from django.test import TestCase, Client
from django.urls import reverse
from apps.organizations.models import Department, Location, Employee
from .models import User


class UserModelTests(TestCase):
    def test_user_roles_and_properties(self):
        admin = User.objects.create_user(
            username='admin_user',
            password='Password123!',
            role=User.Role.ADMIN
        )
        dean = User.objects.create_user(
            username='dean_user',
            password='Password123!',
            role=User.Role.DEAN
        )
        chair = User.objects.create_user(
            username='chair_user',
            password='Password123!',
            role=User.Role.DEPT_CHAIR
        )
        faculty = User.objects.create_user(
            username='faculty_user',
            password='Password123!',
            role=User.Role.FACULTY
        )

        self.assertTrue(admin.is_admin)
        self.assertFalse(admin.is_dean)

        self.assertTrue(dean.is_dean)
        self.assertFalse(dean.is_admin)

        self.assertTrue(chair.is_dept_chair)
        self.assertFalse(chair.is_faculty)

        self.assertTrue(faculty.is_faculty)
        self.assertFalse(faculty.is_admin)


class AccountViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='sysadmin',
            email='admin@cba.edu',
            password='Password123!',
            role=User.Role.ADMIN
        )
        self.faculty = User.objects.create_user(
            username='prof_santos',
            email='santos@cba.edu',
            password='Password123!',
            role=User.Role.FACULTY
        )

    def test_login_view(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CBA IMS')

    def test_unauthenticated_redirect_to_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_authenticated_dashboard(self):
        self.client.login(username='sysadmin', password='Password123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Equipment operations')

    def test_user_list_admin_only(self):
        # Non-admin access should fail (403 or redirect)
        self.client.login(username='prof_santos', password='Password123!')
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 403)

        # Admin access should succeed
        self.client.login(username='sysadmin', password='Password123!')
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Users Management')
        self.assertContains(response, 'sysadmin')
        self.assertContains(response, 'prof_santos')

    def test_user_create_and_toggle_active(self):
        self.client.login(username='sysadmin', password='Password123!')
        
        # Create user
        create_url = reverse('accounts:user_create')
        post_data = {
            'username': 'new_user',
            'email': 'new@cba.edu',
            'first_name': 'New',
            'last_name': 'Faculty',
            'role': User.Role.FACULTY,
            'password1': 'Secret12345!',
            'password2': 'Secret12345!',
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        new_user = User.objects.get(username='new_user')
        self.assertTrue(new_user.is_active)

        # Toggle active
        toggle_url = reverse('accounts:user_toggle_active', kwargs={'pk': new_user.pk})
        response = self.client.post(toggle_url)
        self.assertEqual(response.status_code, 302)
        new_user.refresh_from_db()
        self.assertFalse(new_user.is_active)

    def test_combined_user_and_employee_creation(self):
        self.client.login(username='sysadmin', password='Password123!')

        dept = Department.objects.create(name='Dept of Accountancy', code='ACC')
        loc = Location.objects.create(name='Faculty Room 101', building='CBA Main')

        create_url = reverse('accounts:user_create')
        post_data = {
            'username': 'prof_delacruz',
            'email': 'delacruz@cba.edu',
            'first_name': 'Juan',
            'last_name': 'Dela Cruz',
            'role': User.Role.FACULTY,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'create_employee_profile': 'on',
            'employee_id': 'EMP-FAC-099',
            'position': 'Assistant Professor',
            'department': dept.pk,
            'location': loc.pk,
            'contact_number': '+63 912 345 6789',
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)

        # Verify User created
        user = User.objects.get(username='prof_delacruz')
        self.assertEqual(user.first_name, 'Juan')
        self.assertEqual(user.email, 'delacruz@cba.edu')

        # Verify Employee profile linked
        self.assertTrue(hasattr(user, 'employee_profile'))
        profile = user.employee_profile
        self.assertEqual(profile.employee_id, 'EMP-FAC-099')
        self.assertEqual(profile.first_name, 'Juan')
        self.assertEqual(profile.last_name, 'Dela Cruz')
        self.assertEqual(profile.position, 'Assistant Professor')
        self.assertEqual(profile.department, dept)
        self.assertEqual(profile.location, loc)
        self.assertEqual(profile.contact_number, '+63 912 345 6789')


class PWAResponsiveTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin_pwa',
            password='Password123!',
            role=User.Role.ADMIN
        )

    def test_pwa_static_assets_exist_and_accessible(self):
        import os, json
        from django.contrib.staticfiles import finders

        # Staff Manifest
        manifest_path = finders.find('manifest.json')
        self.assertIsNotNone(manifest_path, "manifest.json must be discoverable by static finders")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)
        self.assertEqual(manifest_data.get('short_name'), 'CBA IMS')
        self.assertEqual(manifest_data.get('name'), 'CBA Asset & Inventory Management System')
        self.assertEqual(manifest_data.get('id'), 'cba-ims-staff')
        self.assertEqual(manifest_data.get('start_url'), '/staff/')
        self.assertEqual(manifest_data.get('display'), 'standalone')

        # Student Manifest
        student_manifest_path = finders.find('manifest_student.json')
        self.assertIsNotNone(student_manifest_path, "manifest_student.json must be discoverable by static finders")
        self.assertTrue(os.path.exists(student_manifest_path))
        with open(student_manifest_path, 'r', encoding='utf-8') as f:
            student_manifest = json.load(f)
        self.assertEqual(student_manifest.get('short_name'), 'CBA Reservations')
        self.assertEqual(student_manifest.get('name'), 'CBA Equipment Reservations')
        self.assertEqual(student_manifest.get('id'), 'cba-reservations-student')
        self.assertEqual(student_manifest.get('start_url'), '/student/')
        self.assertEqual(student_manifest.get('display'), 'standalone')
        self.assertNotIn('IMS', student_manifest.get('short_name'))
        self.assertNotIn('Inventory', student_manifest.get('name'))

        # Service Worker
        sw_path = finders.find('sw.js')
        self.assertIsNotNone(sw_path, "sw.js must be discoverable by static finders")
        self.assertTrue(os.path.exists(sw_path))
        with open(sw_path, 'r', encoding='utf-8') as f:
            sw_content = f.read()
        self.assertIn('cba-ims', sw_content)

        # Offline Page
        offline_path = finders.find('offline.html')
        self.assertIsNotNone(offline_path, "offline.html must be discoverable by static finders")
        self.assertTrue(os.path.exists(offline_path))

        # PWA Icon
        icon_path = finders.find('icons/icon-192.png')
        self.assertIsNotNone(icon_path, "icon-192.png must be discoverable by static finders")
        self.assertTrue(os.path.exists(icon_path))

    def test_responsive_layout_elements_present(self):
        self.client.login(username='admin_pwa', password='Password123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        # Viewport meta tag
        self.assertIn('name="viewport"', content)
        self.assertIn('width=device-width', content)
        
        # Desktop permanent sidebar element
        self.assertIn('id="desktop-sidebar"', content)
        
        # Mobile/tablet offcanvas sidebar element
        self.assertIn('id="sidebarMenu"', content)
        self.assertIn('offcanvas', content)

        # Staff Manifest link
        self.assertIn('manifest.json', content)

    def test_student_and_staff_manifest_links_are_separated(self):
        """Student portal references student manifest, while staff layout references staff manifest."""
        # Student landing
        student_response = self.client.get(reverse('student_landing'))
        self.assertEqual(student_response.status_code, 200)
        student_content = student_response.content.decode('utf-8')
        self.assertIn('manifest_student.json', student_content)
        self.assertNotIn('/static/manifest.json', student_content)

        # Staff login page (/staff/)
        staff_login_response = self.client.get(reverse('staff_login'))
        self.assertEqual(staff_login_response.status_code, 200)
        staff_login_content = staff_login_response.content.decode('utf-8')
        self.assertIn('manifest.json', staff_login_content)
        self.assertNotIn('manifest_student.json', staff_login_content)

        # Staff dashboard (/dashboard/)
        self.client.login(username='admin_pwa', password='Password123!')
        staff_response = self.client.get(reverse('dashboard'))
        self.assertEqual(staff_response.status_code, 200)
        staff_content = staff_response.content.decode('utf-8')
        self.assertIn('manifest.json', staff_content)
        self.assertNotIn('manifest_student.json', staff_content)
